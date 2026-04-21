"""
Schedule Assistant Plugin

Intelligent Schedule Assistant,支持自然语言创建日程,定时habit reminders,结合Live Dashboard
状态智能生成提醒,上下午感知提醒,私聊定向推送等功能.

作者: Slandre & Flandre
"""

import json
import re
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Generator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot import logger
from astrbot.api.star import Star, Context
from astrbot.api.event import filter
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.api.platform import MessageType

from astrbot.core.provider.entities import ProviderType
from .schedule_store import ScheduleStore, ScheduleItem
from .notion_client import NotionClient
from .apple_calendar import AppleCalendar
from .reminders.schedule import ScheduleReminder

from .constants import (
    PREFERENCE_SCOPE,
    SCHEDULES_KEY,
    HABITS_KEY,
    WATER_LAST_KEY,
    LOG_PREFIX,
    DEFAULT_BATH_TIME,
    DEFAULT_SLEEP_TIME,
    DEFAULT_WATER_START,
    DEFAULT_WATER_END,
    DEFAULT_WATER_INTERVAL,
    SCHEDULE_SCAN_WINDOW_MINUTES,
)

from .services.weather import WeatherService
from .services.notion import NotionService
from .services.dashboard import DashboardService
from .services.llm import LLMService
from .reminders.briefing import BriefingReminder
from .reminders.bath import BathReminder
from .reminders.sleep import SleepReminder
from .reminders.water import WaterReminder


class ScheduleAssistant(Star):
    """日程助手插件主类"""

    def __init__(self, context: Context, config: Dict[str, Any]):
        super().__init__(context)
        self.config = config
        self.store = ScheduleStore(context)
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

        # 服务初始化（按需，失败不影响其他功能）
        self.weather_service: Optional[WeatherService] = None
        self.notion_service: Optional[NotionService] = None
        self.dashboard_service: Optional[DashboardService] = None
        self.llm_service: Optional[LLMService] = None
        self._services_ready = False

        # 外部客户端
        self.notion: Optional[NotionClient] = None

        # 常用配置
        self.default_user_id: Optional[str] = None
        whitelist = self.config.get("whitelist_qq_ids", [])
        if whitelist:
            self.default_user_id = str(whitelist[0])

    # ── 服务初始化 ─────────────────────────────────────────────────────────

    def _get_platform_id(self) -> str:
        """获取当前平台标识"""
        return self.context.get_platform_name()

    async def _ensure_services(self):
        """延迟初始化外部服务（失败不阻断主流程）"""
        if self._services_ready:
            return
        self._services_ready = True

        # Weather
        api_key = self.config.get("weather_api_key")
        city = self.config.get("weather_city", "杭州")
        if api_key:
            self.weather_service = WeatherService(api_key, city)

        # LLM
        maton_key = self.config.get("maton_api_key")
        if maton_key:
            try:
                self.llm_service = LLMService(maton_key)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} LLM 服务初始化失败: {e}")

        # Dashboard
        self.dashboard_service = DashboardService()

        # Notion
        transaction_db = self.config.get("transaction_db_id")
        reading_db = self.config.get("reading_db_id")
        maton_key = self.config.get("maton_api_key")
        if transaction_db and maton_key:
            try:
                self.notion = NotionClient(
                    transaction_db_id=transaction_db,
                    reading_db_id=reading_db,
                    maton_api_key=maton_key,
                )
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} Notion 初始化失败: {e}")

        # 提醒服务
        self.briefing_reminder = BriefingReminder(self.llm_service, self.weather_service, self.dashboard_service)
        self.bath_reminder = BathReminder(self.llm_service, self.dashboard_service)
        self.sleep_reminder = SleepReminder(self.llm_service, self.dashboard_service)
        self.water_reminder = WaterReminder(self.llm_service, self.dashboard_service)
        self.schedule_reminder = ScheduleReminder(self.llm_service, self.dashboard_service)

        logger.info(f"{LOG_PREFIX} 外部服务初始化完成")

    # ── 定时任务 ─────────────────────────────────────────────────────────

    async def _register_tasks(self):
        """注册所有定时任务（仅注册，不启动）"""
        conf = self.config

        # 早安播报
        if conf.get("enable_morning_report", True):
            morning_time = conf.get("morning_report_time", "09:00")
            morning_hour, morning_minute = map(int, morning_time.split(":"))
            self.scheduler.add_job(
                self._morning_briefing,
                CronTrigger(hour=morning_hour, minute=morning_minute),
                id="morning_briefing",
                replace_existing=True,
            )
            logger.info(f"{LOG_PREFIX} 早安播报已注册: {morning_time}")

        # 洗澡提醒
        if conf.get("enable_bath_reminder", True):
            bath_time = conf.get("bath_time", DEFAULT_BATH_TIME)
            bath_hour, bath_minute = map(int, bath_time.split(":"))
            self.scheduler.add_job(
                self._bath_reminder,
                CronTrigger(hour=bath_hour, minute=bath_minute),
                id="bath_reminder",
                replace_existing=True,
            )
            logger.info(f"{LOG_PREFIX} 洗澡提醒已注册: {bath_time}")

        # 睡觉提醒
        if conf.get("enable_sleep_reminder", True):
            sleep_time = conf.get("sleep_time", DEFAULT_SLEEP_TIME)
            sleep_hour, sleep_minute = map(int, sleep_time.split(":"))
            self.scheduler.add_job(
                self._sleep_reminder,
                CronTrigger(hour=sleep_hour, minute=sleep_minute),
                id="sleep_reminder",
                replace_existing=True,
            )

            # Apple 日历双向同步定时任务
            if conf.get("enable_apple_calendar_sync"):
                sync_interval = conf.get("apple_calendar_sync_interval", 30)
                self.scheduler.add_job(
                    self._apple_calendar_sync,
                    "interval",
                    minutes=sync_interval,
                    id="apple_calendar_sync",
                    replace_existing=True,
                    max_instances=1,
                )
                logger.info(f"{LOG_PREFIX} Apple 日历同步任务已注册（每 {sync_interval} 分钟）")

            # 日程 LLM 提醒定时扫描
            if conf.get("enable_schedule_reminder"):
                self.scheduler.add_job(
                    self._schedule_reminder_scan,
                    CronTrigger(second=30),
                    id="schedule_reminder_scan",
                    replace_existing=True,
                )
                logger.info(f"{LOG_PREFIX} 日程 LLM 提醒已启用")

        # 喝水提醒
        if conf.get("enable_water_reminder", True):
            water_interval = conf.get("water_interval", DEFAULT_WATER_INTERVAL)
            water_start = conf.get("water_start_time", DEFAULT_WATER_START)
            water_end = conf.get("water_end_time", DEFAULT_WATER_END)

            now = datetime.now()
            next_trigger = self._get_water_next_trigger(now, water_start, water_end, water_interval)
            initial_delay = max((next_trigger - now).total_seconds(), 30.0)

            try:
                self.scheduler.remove_job("water_reminder")
            except Exception:
                pass
            self.scheduler.add_job(
                self._water_reminder,
                "date",
                run_date=datetime.now() + timedelta(seconds=initial_delay),
                id="water_reminder",
                replace_existing=True
            )
            logger.info(f"{LOG_PREFIX} 喝水提醒首次触发: {next_trigger.strftime('%H:%M')} ({initial_delay/60:.1f}分钟后)")

            # 每小时检查一次 Notion DDL
            self.scheduler.add_job(
                self._notion_ddl_check,
                CronTrigger(minute=0),
                id="notion_ddl_check",
                replace_existing=True
            )

            # 每天凌晨清理过期的临时修改
            self.scheduler.add_job(
                self._clear_expired_overrides,
                CronTrigger(hour=0, minute=5),
                id="clear_expired_overrides",
                replace_existing=True
            )

            # 每小时扫描一次用户日程
            self.scheduler.add_job(
                self._schedule_scan,
                CronTrigger(minute=1),
                id="schedule_scan",
                replace_existing=True
            )

            # 立即启动 scheduler
            if not self.scheduler.running:
                self.scheduler.start()

            logger.info(f"{LOG_PREFIX} 所有定时任务已注册,调度器已启动")

    def _get_water_next_trigger(self, now: datetime, water_start: str, water_end: str, water_interval: int) -> datetime:
        """计算喝水提醒下次触发时间"""
        start_h, start_m = map(int, water_start.split(":"))
        end_h, end_m = map(int, water_end.split(":"))
        today_start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        today_end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)

        if now < today_start:
            return today_start
        if now >= today_end:
            return today_start + timedelta(days=1)

        interval_min = timedelta(minutes=water_interval)
        next_t = today_start
        while next_t <= now:
            next_t += interval_min
        if next_t > today_end:
            return today_start + timedelta(days=1)
        return next_t

    # ── 生命周期 ─────────────────────────────────────────────────────────

    async def on_load(self):
        """插件加载回调"""
        logger.info(f"{LOG_PREFIX} 插件加载完成")

    async def on_unload(self):
        """插件卸载时清理资源"""
        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
                logger.info(f"{LOG_PREFIX} 调度器已停止")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 调度器停止失败: {e}")
        if self.notion:
            await self.notion.close()

    # ── 定时任务实现 ─────────────────────────────────────────────────────

    async def _morning_briefing(self):
        try:
            await self._ensure_services()
            user_id = self.default_user_id
            if not user_id:
                return
            briefing = await self.briefing_reminder.generate_briefing(user_id)
            await self._send_to_user(user_id, briefing)
            logger.info(f"{LOG_PREFIX} 早安播报已发送")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 早安播报失败: {e}")

    async def _bath_reminder(self):
        try:
            await self._ensure_services()
            user_id = self.default_user_id
            if not user_id:
                return
            msg = await self.bath_reminder.generate_reminder(user_id)
            await self._send_to_user(user_id, msg)
            logger.info(f"{LOG_PREFIX} 洗澡提醒已发送")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 洗澡提醒失败: {e}")

    async def _sleep_reminder(self):
        try:
            await self._ensure_services()
            user_id = self.default_user_id
            if not user_id:
                return
            msg = await self.sleep_reminder.generate_reminder(user_id)
            await self._send_to_user(user_id, msg)
            logger.info(f"{LOG_PREFIX} 睡觉提醒已发送")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 睡觉提醒失败: {e}")

    async def _water_reminder(self):
        try:
            await self._ensure_services()
            user_id = self.default_user_id
            if not user_id:
                return
            msg = await self.water_reminder.generate_reminder(user_id)
            await self._send_to_user(user_id, msg)
            logger.info(f"{LOG_PREFIX} 喝水提醒已发送")

            conf = self.config
            water_interval = conf.get("water_interval", DEFAULT_WATER_INTERVAL)
            water_start = conf.get("water_start_time", DEFAULT_WATER_START)
            water_end = conf.get("water_end_time", DEFAULT_WATER_END)

            now = datetime.now()
            next_trigger = self._get_water_next_trigger(now, water_start, water_end, water_interval)
            delay = max((next_trigger - now).total_seconds(), 30.0)

            try:
                self.scheduler.remove_job("water_reminder")
            except Exception:
                pass
            self.scheduler.add_job(
                self._water_reminder,
                "date",
                run_date=datetime.now() + timedelta(seconds=delay),
                id="water_reminder",
                replace_existing=True,
            )
            logger.debug(f"{LOG_PREFIX} 下次喝水提醒: {next_trigger.strftime('%H:%M')}")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 喝水提醒失败: {e}")

    async def _notion_ddl_check(self):
        try:
            if not self.notion:
                return
            user_id = self.default_user_id
            if not user_id:
                return
            tasks = await self.notion.get_deadline_tasks(hours=24)
            for task in tasks:
                title = task.get("title", "未命名")
                deadline = task.get("deadline", "")
                page_url = task.get("url", "")
                due_str = ""
                if deadline:
                    try:
                        due_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                        due_str = f"截止时间: {due_dt.strftime('%m-%d %H:%M')}"
                    except Exception:
                        due_str = f"截止时间: {deadline}"
                await self._send_to_user(
                    user_id,
                    f"⚠️ Notion 待办即将到期：{title}\n{due_str}\n🔗 {page_url}"
                )
                logger.info(f"{LOG_PREFIX} Notion DDL 提醒: {title}")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} Notion DDL 检查失败: {e}")

    async def _apple_calendar_sync(self):
        """Apple 日历 → 本地定时同步（以 Apple 为准）"""
        try:
            user_id = self.default_user_id
            if not user_id:
                return

            conf = self.config
            apple_conf = conf.get("apple_calendar", {})
            if not apple_conf.get("enable_sync"):
                return

            username = apple_conf.get("username")
            app_password = apple_conf.get("app_password")
            target_calendar_id = apple_conf.get("calendar_id", "")

            if not username or not app_password:
                return

            ac = AppleCalendar(username=username, app_password=app_password)
            events = await ac.get_all_events(days=7)
            await ac.close()

            if events:
                stats = await self.store.sync_from_apple_calendar(user_id, events, target_calendar_id)
                if any(stats.values()):
                    logger.info(f"{LOG_PREFIX} Apple 日历同步: 新增={stats['added']} 更新={stats['updated']} 删除={stats['deleted']}")

        except Exception as e:
            logger.error(f"{LOG_PREFIX} Apple 日历同步失败: {e}")

    async def _schedule_reminder_scan(self):
        """每分钟扫描即将到来的日程，用 LLM 生成自然语言提醒"""
        try:
            user_id = self.default_user_id
            if not user_id:
                return

            if not self.config.get("enable_schedule_reminder"):
                return

            from .reminders.schedule import check_and_trigger_schedule_reminder

            triggered = await check_and_trigger_schedule_reminder(
                schedule_store=self.store,
                llm_service=self.llm_service,
                dashboard_service=self.dashboard_service,
                user_id=user_id,
                minutes_window=80,
            )

            for t in triggered:
                await self._send_to_user(user_id, t["reminder_text"])
                logger.info(f"{LOG_PREFIX} LLM 提醒: {t['title']} ({t['minutes_until']}分钟后)")

        except Exception as e:
            logger.error(f"{LOG_PREFIX} 日程提醒扫描失败: {e}")

    async def _clear_expired_overrides(self):
        """每日清理过期的临时修改"""
        try:
            user_id = self.default_user_id
            if user_id:
                await self.store.clear_expired_overrides(user_id)
                logger.info(f"{LOG_PREFIX} 已清理过期的临时修改")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 清理过期临时修改失败: {e}")

    async def _schedule_scan(self):
        """每小时扫描一次用户日程，到期触发私信提醒"""
        try:
            user_id = self.default_user_id
            if not user_id:
                return

            now = datetime.now()
            window_start = now - timedelta(minutes=SCHEDULE_SCAN_WINDOW_MINUTES)

            items = await self.store.list_all_items(user_id)

            for item in items:
                if not item.enabled:
                    continue

                due_time: Optional[datetime] = None
                item_changed = False

                if item.snoozed_until:
                    snooze_dt = self._parse_ymdhm(item.snoozed_until)
                    if snooze_dt:
                        if snooze_dt > now:
                            continue
                        due_time = snooze_dt
                    else:
                        item.snoozed_until = None
                        item_changed = True

                if due_time is None:
                    if item.type == "schedule":
                        try:
                            due_time = datetime.strptime(item.time, "%Y-%m-%d %H:%M")
                        except ValueError:
                            if self._is_valid_hhmm(item.time):
                                h, m = map(int, item.time.split(":"))
                                due_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
                            else:
                                logger.warning(f"{LOG_PREFIX} 跳过非法单次日程时间: {item.title} ({item.time})")
                                item.enabled = False
                                item_changed = True
                                await self.store.update_item(user_id, item)
                                continue
                    else:
                        trigger_hhmm = item.time
                        if item.temp_override:
                            override_dt = self._parse_ymdhm(item.temp_override)
                            if override_dt and override_dt.date() == now.date():
                                trigger_hhmm = override_dt.strftime("%H:%M")
                        if not self._is_valid_hhmm(trigger_hhmm):
                            logger.warning(f"{LOG_PREFIX} 跳过非法习惯时间: {item.title} ({trigger_hhmm})")
                            continue
                        h, m = map(int, trigger_hhmm.split(":"))
                        due_time = now.replace(hour=h, minute=m, second=0, microsecond=0)

                if not due_time or not (window_start <= due_time <= now):
                    if item_changed:
                        await self.store.update_item(user_id, item)
                    continue

                if item.last_triggered:
                    try:
                        last_dt = datetime.fromisoformat(item.last_triggered)
                        if last_dt >= window_start:
                            continue
                    except ValueError:
                        logger.warning(f"{LOG_PREFIX} last_triggered 格式非法: {item.title} ({item.last_triggered})")
                        item.last_triggered = None
                        item_changed = True

                item.last_triggered = now.isoformat()
                item.snoozed_until = None
                if item.type == "schedule":
                    item.enabled = False
                await self.store.update_item(user_id, item)

                recur_text = {"daily": "每天", "weekly": "每周"}.get(item.recur or "", "")
                await self._send_to_user(
                    user_id,
                    f"📅 {recur_text}{item.title}提醒~ 时间到啦！"
                )
                logger.info(f"{LOG_PREFIX} 日程触发: {item.title} (类型: {item.type})")

        except Exception as e:
            logger.error(f"{LOG_PREFIX} 日程扫描失败: {e}")

    # ── 工具函数 ─────────────────────────────────────────────────────────

    def _is_valid_hhmm(self, time_str: str) -> bool:
        if not time_str:
            return False
        parts = time_str.split(":")
        if len(parts) != 2:
            return False
        try:
            h, m = int(parts[0]), int(parts[1])
            return 0 <= h <= 23 and 0 <= m <= 59
        except (ValueError, TypeError):
            return False

    def _parse_ymdhm(self, s: str) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None

    async def _send_to_user(self, user_id: str, message: str):
        """发送私聊消息给用户"""
        try:
            allowed = self.config.get("whitelist_qq_ids", [])

            if user_id not in allowed:
                logger.warning(f"{LOG_PREFIX} 用户 {user_id} 不在白名单,跳过发送")
                return

            from astrbot.core.platform.message_session import MessageSession

            session = MessageSession(
                platform_name=self._get_platform_id(),
                message_type=MessageType.FRIEND_MESSAGE,
                session_id=user_id
            )

            from astrbot.api.event import MessageChain
            message = re.sub(r'&&[^&]+&&', '', message)
            chain = MessageChain().message(message)
            await self.context.send_message(session, chain)
            logger.info(f"{LOG_PREFIX} 消息已发送给用户 {user_id}")

        except Exception as e:
            logger.error(f"{LOG_PREFIX} 发送消息失败: {e}")

    # ==================== LLM Tools ====================

    @filter.llm_tool(
        name="add_schedule",
        description="添加新的日程或习惯。参数：title-名称，time-时间(HH:MM or YYYY-MM-DD HH:MM)，recur-重复周期（仅支持 daily/weekly，空则单次）。边界：单次日程触发后自动关闭。"
    )
    async def add_schedule_llm(
        self,
        event: AiocqhttpMessageEvent,
        title: str,
        time: str,
        recur: Optional[str] = None,
        description: str = ""
    ) -> Generator[str, Any, None]:
        """添加日程或习惯"""
        user_id = str(event.get_sender_id())

        item = ScheduleItem(
            type="habit" if recur else "schedule",
            title=title,
            time=time,
            recur=recur,
            context=description
        )

        await self.store.add_item(user_id, item)

        recur_text = ""
        if recur == "daily":
            recur_text = ",每天重复"
        elif recur == "weekly":
            recur_text = ",每周重复"

        yield event.plain_result(f"已添加: {title} @ {time}{recur_text}")

        # 写入 Apple 日历
        apple_conf = self.config.get("apple_calendar", {})
        if apple_conf.get("enable_sync") and not recur:
            username = apple_conf.get("username")
            app_password = apple_conf.get("app_password")
            if username and app_password:
                try:
                    from datetime import datetime as dt
                    dt_start = dt.strptime(time, "%Y-%m-%d %H:%M")
                    ac = AppleCalendar(username=username, app_password=app_password)
                    uid = await ac.create_event(
                        summary=title,
                        start=dt_start,
                        calendar_id=apple_conf.get("calendar_id"),
                        description=description,
                    )
                    await ac.close()
                    if uid:
                        all_items = await self.store.list_all_items(user_id)
                        for it in reversed(all_items):
                            if it.title == title and it.time == time and not getattr(it, "apple_uid", None):
                                it.apple_uid = uid
                                await self.store.update_item(user_id, it)
                                break
                except Exception as e:
                    logger.warning(f"{LOG_PREFIX} 写入 Apple 日历失败: {e}")

    @filter.llm_tool(
        name="remove_schedule",
        description="删除指定的日程或习惯。支持模糊匹配。边界：匹配到第一项即删除并返回。"
    )
    async def remove_schedule_llm(
        self,
        event: AiocqhttpMessageEvent,
        title: str
    ) -> Generator[str, Any, None]:
        """删除日程或习惯"""
        user_id = str(event.get_sender_id())

        items = await self.store.list_all_items(user_id)
        for item in items:
            if title in item.title:
                success = await self.store.remove_item(user_id, item.id)
                if success:
                    yield event.plain_result(f"已删除: {item.title}")
                    return

        yield event.plain_result(f"未找到包含「{title}」的日程或习惯")

    @filter.llm_tool(
        name="list_schedules",
        description="查看当前用户所有日程和习惯。返回格式：日程列表 + 习惯列表。"
    )
    async def list_schedules_llm(
        self,
        event: AiocqhttpMessageEvent
    ) -> Generator[str, Any, None]:
        """查看所有日程"""
        user_id = str(event.get_sender_id())

        data = await self.store.get_schedules(user_id)
        schedules = data.get(SCHEDULES_KEY, [])
        habits = data.get(HABITS_KEY, [])

        lines = []
        if schedules:
            lines.append("📅 单次日程:")
            for s in schedules:
                time_info = s.time if isinstance(s.time, str) else str(s.time)
                recur_info = f" [已过期]" if s.type == "schedule" and s.time < datetime.now().strftime("%Y-%m-%d %H:%M") else ""
                lines.append(f"  • {s.title} @ {time_info}{recur_info}")
        else:
            lines.append("📅 无单次日程")

        if habits:
            lines.append("\n🔄 习惯:")
            for h in habits:
                recur_map = {"daily": "每天", "weekly": "每周"}
                recur_info = recur_map.get(h.recur or "", "每天")
                status = "✅" if h.enabled else "❌"
                lines.append(f"  {status} {h.title} @ {h.time} ({recur_info})")
        else:
            lines.append("\n🔄 无习惯")

        yield event.plain_result("\n".join(lines))

    @filter.llm_tool(
        name="snooze_schedule",
        description="推迟指定的日程或习惯提醒。参数：title-日程名称（支持模糊匹配），minutes-推迟分钟数。"
    )
    async def snooze_schedule_llm(
        self,
        event: AiocqhttpMessageEvent,
        title: str,
        minutes: int = 10
    ) -> Generator[str, Any, None]:
        """推迟日程或习惯"""
        user_id = str(event.get_sender_id())

        items = await self.store.list_all_items(user_id)
        for item in items:
            if title in item.title:
                success = await self.store.snooze_item(user_id, item.id, minutes)
                if success:
                    new_time = (datetime.now() + timedelta(minutes=minutes)).strftime("%H:%M")
                    yield event.plain_result(f"好的，{item.title}推迟到 {new_time} 再提醒~")
                    return

        yield event.plain_result(f"未找到包含「{title}」的日程或习惯")

    @filter.llm_tool(
        name="temp_override_habit",
        description="临时修改习惯提醒时间（仅今天生效）。参数：habit_name-习惯名称，new_time-新时间(HH:MM)。"
    )
    async def temp_override_habit_llm(
        self,
        event: AiocqhttpMessageEvent,
        habit_name: str,
        new_time: str
    ) -> Generator[str, Any, None]:
        """临时修改习惯时间"""
        user_id = str(event.get_sender_id())

        if not self._is_valid_hhmm(new_time):
            yield event.plain_result(f"时间格式不对哦，应该是 HH:MM，比如 09:00")
            return

        data = await self.store.get_schedules(user_id)
        habits = data.get(HABITS_KEY, [])
        found = None
        for h in habits:
            if habit_name in h.title:
                found = h
                break

        if not found:
            yield event.plain_result(f"未找到习惯「{habit_name}」")
            return

        success = await self.store.set_temp_override(user_id, found.title, new_time)
        if success:
            yield event.plain_result(f"好的，{found.title} 今天临时改到 {new_time}，明天恢复原时间~")
        else:
            yield event.plain_result(f"修改失败，请稍后重试")

    @filter.llm_tool(
        name="get_notion_tasks",
        description="查看 Notion 中标记为 PENDING 的待办任务，显示任务名称、截止时间和 DDL 倒计时。"
    )
    async def get_notion_tasks_llm(
        self,
        event: AiocqhttpMessageEvent
    ) -> Generator[str, Any, None]:
        """查看 Notion 待办"""
        if not self.notion:
            yield event.plain_result("Notion 功能未配置或初始化失败")
            return

        try:
            tasks = await self.notion.get_pending_tasks()
            if not tasks:
                yield event.plain_result("✅ Notion 待办列表为空，放轻松~")
                return

            lines = [f"📋 Notion 待办（共 {len(tasks)} 项）:"]
            for t in tasks[:10]:
                title = t.get("title", "未命名")
                deadline = t.get("deadline", "")
                url = t.get("url", "")

                due_str = ""
                if deadline:
                    try:
                        due_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                        now = datetime.now(due_dt.tzinfo)
                        diff = due_dt - now
                        if diff.days < 0:
                            due_str = "（已逾期）"
                        elif diff.days == 0:
                            due_str = "（今天截止）"
                        else:
                            due_str = f"（还剩 {diff.days} 天）"
                        time_str = due_dt.strftime("%m-%d %H:%M")
                    except Exception:
                        time_str = str(deadline)
                else:
                    time_str = "无截止时间"

                lines.append(f"• {title} {due_str}")
                if time_str:
                    lines.append(f"  截止: {time_str}")

            if len(tasks) > 10:
                lines.append(f"...还有 {len(tasks) - 10} 项")

            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 获取 Notion 待办失败: {e}")
            yield event.plain_result(f"获取 Notion 待办失败: {str(e)}")

    @filter.llm_tool(
        name="skip_water",
        description="跳过本次喝水提醒。主要用于计算下次喝水间隔。参数：reason-跳过原因（可选）。"
    )
    async def skip_water_llm(
        self,
        event: AiocqhttpMessageEvent,
        reason: str = ""
    ) -> Generator[str, Any, None]:
        """跳过喝水提醒"""
        user_id = str(event.get_sender_id())

        await self.store.set_water_last(user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        water_interval = self.config.get("water_interval", DEFAULT_WATER_INTERVAL)
        next_time = (datetime.now() + timedelta(minutes=water_interval)).strftime("%H:%M")

        reason_text = f"（{reason}）" if reason else ""
        yield event.plain_result(f"好的，本次跳过 {reason_text}，下次喝水提醒约 {next_time} ~")

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def handle_private_message(self, event: AiocqhttpMessageEvent):
        """处理私聊消息（用于初始化外部服务）"""
        user_id = str(event.get_sender_id())

        msg_text = event.message_str.strip()
        if msg_text:
            await self.store.add_conversation_message(user_id, "user", msg_text)

        asyncio.create_task(self._ensure_services())
        asyncio.create_task(self._register_tasks())


async def __initialize(context: Context):
    """插件初始化入口"""
    config = context.get_config().get("schedule_assistant", {})
    assistant = ScheduleAssistant(context, config)
    return assistant