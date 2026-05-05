"""
日程助手插件

提供日程管理、习惯提醒、早安播报、Apple日历同步、Notion待办等功能。
采用 MessagingService 封装发送逻辑，
主类只保留插件生命周期管理和定时任务调度。
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .apple_calendar import AppleCalendar
from .constants import (
    DEFAULT_BATH_TIME,
    DEFAULT_SLEEP_TIME,
    DEFAULT_WATER_END,
    DEFAULT_WATER_INTERVAL,
    DEFAULT_WATER_START,
    LOG_PREFIX,
    SCHEDULES_KEY,
)
from .live_dashboard import LiveDashboardMixin
from .messaging import MessagingService
from .notion_client import NotionClient
from .reminders.briefing import BriefingReminder
from .reminders.habits import BathReminder, SleepReminder, WaterReminder
from .reminders.schedule import ScheduleReminder, check_and_trigger_schedule_reminder
from .schedule_store import ScheduleItem, ScheduleStore
from .services.dashboard import BasicDashboardService, get_dashboard_status
from .services.llm import LLMService
from .services.notion import NotionService
from .services.weather import WeatherService
from .tools.schedule_tools import register_schedule_tools

SCHEDULE_REMINDER_LOG_THROTTLE_SECONDS = 300  # seconds (5 minutes)


class ScheduleAssistant(LiveDashboardMixin, Star):

    def __init__(self, context: Context, config: dict[str, Any]):
        super().__init__(context)
        self.config = config
        self.store = ScheduleStore(self)
        self.messaging = MessagingService(context, config)
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self.weather_service: WeatherService | None = None
        self.notion_service: NotionService | None = None
        self.llm_service: LLMService | None = None
        self.dashboard_service: BasicDashboardService | None = None
        self.live_dashboard_service = None
        self.apple_calendar: AppleCalendar | None = None
        self.notion: NotionClient | None = None
        self._services_ready = False
        self._tasks_registered = False
        self._tools_registered = False
        self._schedule_reminder_scan_lock = asyncio.Lock()
        self._apple_calendar_sync_lock = asyncio.Lock()
        self._schedule_reminder_last_log_ts = 0.0

        self._init_task: asyncio.Task | None = None
        self._runtime_cleaned = False
        self._cleanup_lock: asyncio.Lock | None = None

        self.default_user_id: str | None = None
        whitelist = self.config.get("whitelist_qq_ids", [])
        if whitelist:
            self.default_user_id = str(whitelist[0])

        # 启动后台初始化（兼容热重载：__init__ 在热重载时立即执行）
        self._init_task = asyncio.create_task(self._initialize())
        self._init_task.add_done_callback(self._on_init_done)

    def _on_init_done(self, task: asyncio.Task):
        try:
            exc = task.exception()
            if exc:
                logger.error(f"{LOG_PREFIX} 初始化任务异常: {exc}")
        except asyncio.CancelledError:
            pass

    async def _initialize(self):
        """AstrBot 初始化或热重载后启动插件定时任务"""
        logger.info(f"{LOG_PREFIX} 开始初始化...")
        await self._ensure_services()
        await self._register_tasks()
        logger.info(f"{LOG_PREFIX} 初始化完成")

    @filter.on_astrbot_loaded()
    async def on_loaded(self):
        """AstrBot 冷启动时的初始化兜底（热重载时不触发此钩子）"""
        # 如果 __init__ 中的任务已在运行，无需重复初始化
        if self._init_task and not self._init_task.done():
            logger.debug(f"{LOG_PREFIX} 冷启动初始化已在 __init__ 中启动，跳过")
            return
        # 如果是某种边界情况导致 __init__ 没启动，兜底执行
        await self._initialize()

    def _add_or_replace_job(self, func, trigger, *, job_id: str, **kwargs):
        options = {
            "id": job_id,
            "replace_existing": True,
        }
        options.update(kwargs)
        self.scheduler.add_job(func, trigger, **options)

    def _schedule_next_water_reminder(self, run_date: datetime):
        try:
            self.scheduler.remove_job("water_reminder")
        except Exception:
            pass
        self._add_or_replace_job(
            self._water_reminder,
            "date",
            job_id="water_reminder",
            run_date=run_date,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )

    async def _ensure_services(self):
        if self._services_ready:
            return
        self._services_ready = True

        # 注册 LLM 日程管理工具（需要等服务初始化完成后）
        if not self._tools_registered:
            register_schedule_tools(self)
            self._tools_registered = True

        api_key = self.config.get("weather_api_key")
        city = self.config.get("weather_city", "杭州")
        if api_key:
            self.weather_service = WeatherService(
                {"weather_api_key": api_key, "weather_city": city}
            )

        self.llm_service = LLMService(self.context, self.config)
        self.dashboard_service = BasicDashboardService()

        notion_db_ids = self.config.get("notion_db_ids", [])
        maton_key = self.config.get("maton_api_key")
        if notion_db_ids and maton_key:
            try:
                transaction_db = ""
                reading_db = ""
                for item in notion_db_ids:
                    if isinstance(item, dict):
                        name = item.get("name", "")
                        db_id = item.get("id", "")
                        if name == "事务" or name == "transaction":
                            transaction_db = db_id
                        elif name == "阅读" or name == "reading":
                            reading_db = db_id
                    elif isinstance(item, str):
                        raw = item.strip()
                        if ":" in raw:
                            name, db_id = raw.split(":", 1)
                            name = name.strip().lower()
                            db_id = db_id.strip()
                            if name in ("事务", "transaction"):
                                transaction_db = db_id
                            elif name in ("阅读", "reading"):
                                reading_db = db_id
                        elif not transaction_db:
                            transaction_db = raw
                            logger.warning(
                                f"{LOG_PREFIX} notion_db_ids 使用无前缀字符串，已按顺序第1个映射为「事务库」"  # noqa: E501
                            )
                        elif not reading_db:
                            reading_db = raw
                            logger.warning(
                                f"{LOG_PREFIX} notion_db_ids 使用无前缀字符串，已按顺序第2个映射为「阅读库」"  # noqa: E501
                            )
                        elif raw:
                            logger.warning(
                                f"{LOG_PREFIX} notion_db_ids 额外无前缀字符串未使用: {raw[:12]}..."  # noqa: E501
                            )
                self.notion = NotionClient(maton_key, transaction_db, reading_db)
                self.notion_service = NotionService(self.notion)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} Notion 初始化失败: {e}")
                self.notion = None
                self.notion_service = None

        self.briefing_reminder = BriefingReminder(
            self.config, self.context, self.llm_service
        )
        self.bath_reminder = BathReminder(
            self.config, self.default_user_id, self.llm_service, self.store
        )
        self.sleep_reminder = SleepReminder(
            self.config, self.default_user_id, self.llm_service, self.store
        )
        self.water_reminder = WaterReminder(
            self.config, self.default_user_id, self.llm_service, self.store
        )
        self.schedule_reminder = ScheduleReminder(
            self.llm_service, self.dashboard_service
        )

        conf = self.config
        if conf.get("enable_apple_calendar_sync"):
            apple_conf = conf.get("apple_calendar", {})
            username = apple_conf.get("username") if apple_conf else None
            app_password = apple_conf.get("app_password") if apple_conf else None
            if username and app_password:
                cal_id = apple_conf.get("calendar_id", "").strip() or None
                self.apple_calendar = AppleCalendar(
                    username=username,
                    app_password=app_password,
                    calendar_id=cal_id,
                )
                logger.info(
                    f"{LOG_PREFIX} Apple Calendar 已配置: {username[:3]}***, calendar_id={cal_id}"  # noqa: E501
                )
            else:
                logger.warning(
                    f"{LOG_PREFIX} Apple Calendar 未配置凭据（username 或 app_password 缺失）"  # noqa: E501
                )

        logger.info(f"{LOG_PREFIX} 外部服务初始化完成")

    async def _register_tasks(self):
        if self._tasks_registered:
            return
        self._tasks_registered = True
        conf = self.config

        if conf.get("enable_morning_report", True):
            morning_time = conf.get("morning_report_time", "09:00")
            morning_hour, morning_minute = map(int, morning_time.split(":"))
            self._add_or_replace_job(
                self._morning_briefing,
                CronTrigger(hour=morning_hour, minute=morning_minute),
                job_id="morning_briefing",
            )
            logger.info(f"{LOG_PREFIX} 早安播报已注册: {morning_time}")

        if conf.get("enable_bath_reminder", True):
            bath_time = conf.get("bath_time", DEFAULT_BATH_TIME)
            bath_hour, bath_minute = map(int, bath_time.split(":"))
            self._add_or_replace_job(
                self._bath_reminder,
                CronTrigger(hour=bath_hour, minute=bath_minute),
                job_id="bath_reminder",
            )
            logger.info(f"{LOG_PREFIX} 洗澡提醒已注册: {bath_time}")

        if conf.get("enable_sleep_reminder", True):
            sleep_time = conf.get("sleep_time", DEFAULT_SLEEP_TIME)
            sleep_hour, sleep_minute = map(int, sleep_time.split(":"))
            self._add_or_replace_job(
                self._sleep_reminder,
                CronTrigger(hour=sleep_hour, minute=sleep_minute),
                job_id="sleep_reminder",
            )
            logger.info(f"{LOG_PREFIX} 睡觉提醒已注册: {sleep_time}")

        if conf.get("enable_apple_calendar_sync"):
            sync_interval = conf.get("apple_calendar_sync_interval", 30)
            self._add_or_replace_job(
                self._apple_calendar_sync,
                "interval",
                job_id="apple_calendar_sync",
                minutes=sync_interval,
                # 防重入/堆积：上次未完成时不并行，错过窗口时合并为一次执行。
                max_instances=1,
                coalesce=True,
                misfire_grace_time=120,
            )
            logger.info(
                f"{LOG_PREFIX} Apple 日历同步任务已注册（每 {sync_interval} 分钟）"
            )

        if self.config.get("enable_schedule_reminder"):
            check_interval = conf.get("schedule_reminder_check_interval", 5)
            try:
                check_interval = max(2, int(check_interval))
            except (ValueError, TypeError):
                check_interval = 5
            self._add_or_replace_job(
                self._schedule_reminder_scan,
                "interval",
                job_id="schedule_reminder_scan",
                minutes=check_interval,
                # 防重入/堆积：单实例执行，misfire 时合并。
                max_instances=1,
                coalesce=True,
                misfire_grace_time=check_interval * 60,
            )
            logger.info(f"{LOG_PREFIX} 日程 LLM 提醒已启用（每 {check_interval} 分钟）")

        if conf.get("enable_water_reminder", True):
            water_interval = conf.get("water_interval", DEFAULT_WATER_INTERVAL)
            water_start = conf.get("water_start_time", DEFAULT_WATER_START)
            water_end = conf.get("water_end_time", DEFAULT_WATER_END)

            now = datetime.now()
            next_trigger = self._get_water_next_trigger(
                now, water_start, water_end, water_interval
            )
            initial_delay = max((next_trigger - now).total_seconds(), 30.0)

            self._schedule_next_water_reminder(
                datetime.now() + timedelta(seconds=initial_delay)
            )
            logger.info(
                f"{LOG_PREFIX} 喝水提醒首次触发: {next_trigger.strftime('%H:%M')} ({initial_delay / 60:.1f}分钟后)"  # noqa: E501
            )

        self._add_or_replace_job(
            self._clear_expired_overrides,
            CronTrigger(hour=0, minute=5),
            job_id="clear_expired_overrides",
        )
        if not self.scheduler.running:
            self.scheduler.start()

        logger.info(f"{LOG_PREFIX} 所有定时任务已注册，调度器已启动")

    def _get_water_next_trigger(
        self, now: datetime, water_start: str, water_end: str, water_interval: int
    ) -> datetime:
        start_h, start_m = map(int, water_start.split(":"))
        end_h, end_m = map(int, water_end.split(":"))
        today_start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        today_end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        if now < today_start:
            return today_start
        if now >= today_end:
            return today_start + timedelta(days=1)
        interval_min = timedelta(minutes=water_interval)
        elapsed = now - today_start
        next_time = today_start + (elapsed // interval_min + 1) * interval_min
        if next_time > today_end:
            return today_start + timedelta(days=1)
        return next_time

    def _extract_sender_name(self, event: AiocqhttpMessageEvent) -> str:
        """从事件对象中提取发送者昵称"""
        try:
            if hasattr(event, "get_sender_name"):
                name = event.get_sender_name()
                if isinstance(name, str) and name.strip():
                    return name.strip()
        except Exception:
            pass

        for attr in ("sender_nickname", "sender_name", "nickname", "name"):
            name = getattr(event, attr, None)
            if isinstance(name, str) and name.strip():
                return name.strip()

        sender = getattr(event, "sender", None)
        if isinstance(sender, dict):
            for key in ("nickname", "name", "card", "group_card"):
                val = sender.get(key)
                if isinstance(val, str) and val.strip() and val != str(event.get_sender_id()):
                    return val.strip()

        return ""

    async def _get_target_user_ids(
        self, include_known_users: bool = False
    ) -> list[str]:
        """获取目标用户ID列表"""
        user_ids = set()
        if self.default_user_id:
            user_ids.add(str(self.default_user_id))
        for uid in self.config.get("whitelist_qq_ids", []) or []:
            if uid:
                user_ids.add(str(uid))
        for uid in self.config.get("target_user_ids", []) or []:
            if uid:
                user_ids.add(str(uid))
        if include_known_users or self.config.get(
            "broadcast_to_all_known_users", False
        ):
            for uid in await self.store.get_all_users():
                if uid:
                    user_ids.add(str(uid))
        return sorted(user_ids)

    def _extract_block_lines(self, block: str) -> list[str]:
        """提取并清洗文本块中的行"""
        if not block or block in ("暂无", "获取失败"):
            return []
        return [line.strip() for line in block.split("\n") if line.strip()]

    def _merge_today_schedule_blocks(
        self, local_text: str, apple_text: str, limit: int = 12
    ) -> str:
        """合并本地日程和Apple日历文本，去重后返回"""
        merged = []
        seen = set()
        for line in self._extract_block_lines(local_text) + self._extract_block_lines(
            apple_text
        ):
            key = " ".join(line.split())
            if key in seen:
                continue
            seen.add(key)
            merged.append(key)
            if len(merged) >= limit:
                break
        if merged:
            return "\n".join(merged)
        if apple_text == "获取失败" and local_text in ("暂无", "", None):
            return "获取失败"
        return "暂无"

    async def _get_user_schedules(self, user_id: str) -> list[ScheduleItem]:
        """获取用户所有日程"""
        schedules_dict = await self.store.get_schedules(user_id)
        return schedules_dict.get(SCHEDULES_KEY, [])

    async def _get_today_local_schedules_text(
        self, user_id: str, limit: int = 8
    ) -> str:
        """获取今日本地日程文本"""
        schedules = await self._get_user_schedules(user_id)
        today = datetime.now().date()
        today_items = []
        for s in schedules:
            if not s.time:
                continue
            try:
                dt = datetime.fromisoformat(s.time)
            except Exception:
                try:
                    dt = datetime.strptime(s.time, "%Y-%m-%d %H:%M")
                except Exception:
                    continue
            if dt.date() == today:
                today_items.append((dt, s.title))
        if not today_items:
            return "暂无"
        today_items.sort(key=lambda x: x[0])
        return "\n".join(
            [
                f"⏰ {dt.strftime('%H:%M')} │ {title}"
                for dt, title in today_items[:limit]
            ]
        )

    async def _get_today_apple_calendar_text(self, limit: int = 8) -> str:
        """获取今日Apple日历文本"""
        if not self.apple_calendar:
            return "暂无"
        try:
            events = await self.apple_calendar.get_all_events(days=1)
            today = datetime.now().date()
            logger.info(
                f"{LOG_PREFIX} Apple日历获取到 {len(events)} 个事件，开始筛选今日({today})事件..."  # noqa: E501
            )

            rows = []
            for e in events:
                start_str = e.get("start", "")
                summary = e.get("summary", "无标题")

                if not start_str:
                    continue
                try:
                    start_dt = datetime.fromisoformat(start_str)
                except Exception:
                    continue
                if start_dt.date() != today:
                    continue
                if e.get("all_day"):
                    time_label = "全天"
                else:
                    time_label = start_dt.strftime("%H:%M")
                rows.append((start_dt, f"⏰ {time_label} │ {summary}"))

            if not rows:
                logger.info(f"{LOG_PREFIX} 今日 Apple 日历无日程")
                return "暂无"
            rows.sort(key=lambda x: x[0])
            logger.info(
                f"{LOG_PREFIX} 今日 Apple 日历事件筛选完成，共 {len(rows)} 个: {[s for _, s in rows]}"  # noqa: E501
            )
            return "\n".join([line for _, line in rows[:limit]])
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} Apple 今日日程读取失败: {e}")
            return "获取失败"

    async def _get_notion_pending_text(self, limit: int = 5) -> str:
        """获取Notion待办文本"""
        if not self.notion_service:
            return "暂无"
        try:
            pending = await self.notion_service.get_pending_tasks()
            if not pending:
                return "暂无"
            lines = []
            for task in pending[:limit]:
                ddl = self.notion_service.format_ddl(task.get("ddl", ""))
                title = task.get("title", "(无标题)")
                lines.append(f"- {ddl} | {title}" if ddl else f"- {title}")
            return "\n".join(lines) if lines else "暂无"
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} Notion 待办读取失败: {e}")
            return "获取失败"

    async def _get_user_nickname(self, user_id: str) -> str:
        """获取用户昵称，优先读取存储，再用配置兜底（避免返回纯数字QQ号）"""
        try:
            cached = await self.store.get_user_nickname(user_id)
            cached = (cached or "").strip()
            # 过滤：有效昵称不能是纯数字（QQ号）
            if cached and not cached.isdigit():
                return cached
        except Exception:
            pass
        fallback = str(self.config.get("user_nickname", "") or "").strip()
        if fallback and not fallback.isdigit():
            return fallback
        # 实在没有昵称，返回通用称呼
        return "你"

    async def _morning_briefing(self, target_user_id: str | None = None):
        try:
            await self._ensure_services()
            target_user_ids = (
                [str(target_user_id)]
                if target_user_id
                else await self._get_target_user_ids()
            )
            if not target_user_ids:
                return

            weather_current, weather_forecast = "", ""
            if self.weather_service:
                weather_current, weather_forecast = await self.weather_service.fetch()

            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            weekday_str = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
                now.weekday()
            ]

            dashboard_status = (
                await get_dashboard_status() if self.dashboard_service else "暂无"
            )
            late_night_text = ""
            if self.apple_calendar:
                try:
                    late_night = await self.apple_calendar.get_late_night_events()
                    late_night_text = "、".join(
                        [e.get("summary", "无标题") for e in late_night[:3]]
                    )
                except Exception:
                    late_night_text = ""

            for user_id in target_user_ids:
                nickname = await self._get_user_nickname(user_id)
                local_text = await self._get_today_local_schedules_text(user_id)
                apple_text = await self._get_today_apple_calendar_text()
                agenda_text = self._merge_today_schedule_blocks(local_text, apple_text)
                notion_text = await self._get_notion_pending_text()

                briefing = await self.briefing_reminder.generate_full_report(
                    username=nickname,
                    date=date_str,
                    weekday=weekday_str,
                    weather_current=weather_current,
                    weather_forecast=weather_forecast,
                    agenda=agenda_text,
                    notion_todos=notion_text,
                    dashboard=dashboard_status,
                    late_night=late_night_text,
                    user_id=user_id,
                )
                await self.messaging.send_to_user(user_id, briefing)
            logger.info(f"{LOG_PREFIX} 早安播报已发送 users={target_user_ids}")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 早安播报失败: {e}")

    async def _run_habit_reminder(
        self, reminder_obj, label: str, target_user_id: str | None = None
    ) -> list[str]:
        """通用习惯提醒执行逻辑，返回目标用户列表（调用方可追加后续操作）。"""
        try:
            await self._ensure_services()
            target_user_ids = (
                [str(target_user_id)]
                if target_user_id
                else await self._get_target_user_ids()
            )
            if not target_user_ids:
                return []

            dashboard = (
                await self.dashboard_service.get_status()
                if self.dashboard_service
                else ""
            )
            for user_id in target_user_ids:
                history = await self.store.get_conversation_history(user_id)
                history_text = (
                    self.store.format_history_for_prompt(history[-5:])
                    if history
                    else ""
                )
                message = await reminder_obj.generate(
                    await self._get_user_nickname(user_id),
                    dashboard,
                    history_text,
                    user_id=user_id,
                )
                if message:
                    await self.messaging.send_to_user(user_id, message)
            logger.info(f"{LOG_PREFIX} {label}提醒已发送 users={target_user_ids}")
            return target_user_ids
        except Exception as e:
            logger.error(f"{LOG_PREFIX} {label}提醒失败: {e}")
            return []

    async def _bath_reminder(self, target_user_id: str | None = None):
        await self._run_habit_reminder(self.bath_reminder, "洗澡", target_user_id)

    async def _sleep_reminder(self, target_user_id: str | None = None):
        await self._run_habit_reminder(self.sleep_reminder, "睡觉", target_user_id)

    async def _water_reminder(self, target_user_id: str | None = None):
        sent_users = await self._run_habit_reminder(
            self.water_reminder, "喝水", target_user_id
        )
        if not sent_users:
            return

        water_interval = self.config.get("water_interval", DEFAULT_WATER_INTERVAL)
        water_start = self.config.get("water_start_time", DEFAULT_WATER_START)
        water_end = self.config.get("water_end_time", DEFAULT_WATER_END)

        next_trigger = self._get_water_next_trigger(
            datetime.now(),
            water_start,
            water_end,
            water_interval,
        )
        delay = max((next_trigger - datetime.now()).total_seconds(), 30.0)

        self._schedule_next_water_reminder(datetime.now() + timedelta(seconds=delay))

    async def _schedule_reminder_scan(self):
        lock = self._schedule_reminder_scan_lock
        try:
            await asyncio.wait_for(lock.acquire(), timeout=0)
        except asyncio.TimeoutError:
            logger.debug(f"{LOG_PREFIX} 日程提醒扫描仍在运行，跳过本轮")
            return
        try:
            now_ts = time.monotonic()
            if (
                now_ts - self._schedule_reminder_last_log_ts
                >= SCHEDULE_REMINDER_LOG_THROTTLE_SECONDS
            ):
                logger.debug(f"{LOG_PREFIX} 执行日程提醒扫描")
                self._schedule_reminder_last_log_ts = now_ts

            await self._ensure_services()
            if not hasattr(self, "schedule_reminder"):
                return

            try:
                raw_minutes = self.config.get("schedule_reminder_minutes", 10)
                if raw_minutes in (None, ""):
                    raw_minutes = 10
                if isinstance(raw_minutes, str):
                    raw_minutes = raw_minutes.strip()
                    if not raw_minutes.isdigit():
                        logger.warning(
                            f"{LOG_PREFIX} schedule_reminder_minutes 非数字，使用默认值 10"  # noqa: E501
                        )
                        raw_minutes = 10
                minutes_ahead = int(raw_minutes)
            except Exception:
                minutes_ahead = 10
            if minutes_ahead <= 0:
                minutes_ahead = 10

            for user_id in await self._get_target_user_ids(include_known_users=True):
                try:
                    triggered = await check_and_trigger_schedule_reminder(
                        schedule_store=self.store,
                        llm_service=self.llm_service,
                        dashboard_service=self.dashboard_service,
                        user_id=user_id,
                        minutes_window=minutes_ahead,
                    )
                    for item in triggered:
                        if item.get("reminder_text"):
                            await self.messaging.send_to_user(
                                user_id, item["reminder_text"]
                            )
                except Exception as e:
                    logger.warning(f"{LOG_PREFIX} 用户 {user_id} 日程提醒扫描失败: {e}")
        finally:
            lock.release()

    async def _apple_calendar_sync(self):
        lock = self._apple_calendar_sync_lock
        try:
            await asyncio.wait_for(lock.acquire(), timeout=0)
        except asyncio.TimeoutError:
            logger.debug(f"{LOG_PREFIX} Apple 同步仍在运行，跳过本轮")
            return
        try:
            if not hasattr(self, "apple_calendar") or not self.apple_calendar:
                return
            try:
                events = await self.apple_calendar.get_all_events(days=7)
                if not events:
                    logger.debug(f"{LOG_PREFIX} Apple Calendar 无事件，跳过同步")
                    return
                user_ids = await self._get_target_user_ids(include_known_users=True)
                if not user_ids:
                    logger.debug(
                        f"{LOG_PREFIX} Apple Calendar 已读取 {len(events)} 个事件，但无可同步用户"  # noqa: E501
                    )
                    return
                recent_events_added = False
                for user_id in user_ids:
                    stats = await self.store.sync_from_apple_calendar(user_id, events)
                    logger.debug(
                        f"{LOG_PREFIX} Apple→本地同步 user={user_id} "
                        f"added={stats['added']} updated={stats['updated']} deleted={stats['deleted']}"  # noqa: E501
                    )
                    if stats.get("added", 0) > 0:
                        recent_events_added = True

                # 如果新增了近期事件，触发一次即时扫描（30秒后）
                if recent_events_added and self.config.get("enable_schedule_reminder"):
                    asyncio.create_task(self._delayed_schedule_reminder_scan())
            except Exception as e:
                logger.error(f"{LOG_PREFIX} Apple Calendar 同步失败: {e}")
        finally:
            lock.release()

    async def _delayed_schedule_reminder_scan(self):
        """延迟触发日程提醒扫描，用于 Apple 同步后补扫"""
        await asyncio.sleep(30)
        try:
            await self._schedule_reminder_scan()
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 即时扫描失败: {e}")

    async def _clear_expired_overrides(self):
        for user_id in await self._get_target_user_ids(include_known_users=True):
            await self.store.clear_expired_overrides(user_id)
        logger.debug(f"{LOG_PREFIX} 已清理过期临时修改")

    # ============ 消息处理入口 ============

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def handle_private_message(self, event: AiocqhttpMessageEvent):
        user_id = str(event.get_sender_id())
        msg_text = event.message_str.strip()

        # 记录平台用于后续发送
        platform_id = self.messaging._extract_platform_id_from_event(event)
        if platform_id:
            self.messaging.remember_user_platform(user_id, platform_id)

        if msg_text:
            await self.store.add_conversation_message(user_id, "user", msg_text)

        # 记录/更新用户昵称
        sender_name = self._extract_sender_name(event)
        if sender_name:
            await self.store.set_user_nickname(user_id, sender_name)

    async def terminate(self):
        """插件卸载时清理定时任务"""
        try:
            if hasattr(self.scheduler, "get_jobs"):
                for job in list(self.scheduler.get_jobs()):
                    try:
                        self.scheduler.remove_job(job.id)
                    except Exception:
                        pass
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 关闭调度器时出错: {e}")
        if self.notion:
            try:
                await self.notion.close()
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} 关闭 NotionClient 失败: {e}")
        if self.apple_calendar:
            try:
                await self.apple_calendar.close()
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} 关闭 AppleCalendar 失败: {e}")


async def __initialize(context: Context) -> ScheduleAssistant:
    # 配置文件中 schedule_assistant 是扁平结构（无顶层包装），
    # 直接取 get_config() 的返回值，无需再 get("schedule_assistant")
    config = context.get_config()
    assistant = ScheduleAssistant(context, config)
    return assistant
