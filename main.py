import json
import re
import asyncio
import aiohttp
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot import logger
from astrbot.api.star import Star, Context
from astrbot.api.event import filter
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.api.platform import MessageType
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.message.components import Plain

from astrbot.core.provider.entities import ProviderType
from .schedule_store import ScheduleStore, ScheduleItem
from .notion_client import NotionClient
from .apple_calendar import AppleCalendar
from .reminders.schedule import ScheduleReminder, check_and_trigger_schedule_reminder

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
    CONVERSATION_KEY,
    CONVERSATION_MAX_MESSAGES,
)

from .services.weather import WeatherService
from .services.notion import NotionService
from .services.dashboard import DashboardService, get_dashboard_status
from .services.llm import LLMService
from .reminders.briefing import BriefingReminder
from .reminders.habits import BathReminder, SleepReminder, WaterReminder
from .tools.schedule_tools import register_schedule_tools

SCHEDULE_REMINDER_LOG_THROTTLE_SECONDS = 300  # seconds (5 minutes)


class ScheduleAssistant(Star):
    # Single-process active-instance guard to prevent duplicate jobs after hot reload.
    _instance_seq: int = 0
    _active_generation: int = 0
    _active_instance: Optional["ScheduleAssistant"] = None

    def __init__(self, context: Context, config: Dict[str, Any]):
        super().__init__(context)
        cls = type(self)
        cls._instance_seq += 1
        self._instance_generation = cls._instance_seq

        self.config = config
        self.store = ScheduleStore(context)
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self.weather_service: Optional[WeatherService] = None
        self.notion_service: Optional[NotionService] = None
        self.llm_service: Optional[LLMService] = None
        self.dashboard_service: Optional[DashboardService] = None
        self.apple_calendar: Optional[AppleCalendar] = None
        self.notion: Optional[NotionClient] = None
        self._services_ready = False
        self._tasks_registered = False
        self._init_task: Optional[asyncio.Task] = None
        self._tools_registered = False
        self._runtime_cleaned = False
        self._cleanup_lock: Optional[asyncio.Lock] = None
        self._schedule_reminder_scan_lock: Optional[asyncio.Lock] = None
        self._apple_calendar_sync_lock: Optional[asyncio.Lock] = None
        self._schedule_reminder_last_log_ts = 0.0

        self.default_user_id: Optional[str] = None
        whitelist = self.config.get("whitelist_qq_ids", [])
        if whitelist:
            self.default_user_id = str(whitelist[0])
        self._session_type = str(self.config.get("default_session_type", "FriendMessage") or "FriendMessage")
        self._global_platform_id = str(self.config.get("send_platform_id", "") or "").strip()
        self._user_platform_bindings = self._parse_user_platform_bindings()
        self._recent_user_platforms: Dict[str, str] = {}

        self._init_task = self._schedule_task(self._initialize(), "initialize")

    def _schedule_task(self, coro, task_name: str) -> Optional[asyncio.Task]:
        try:
            task = asyncio.create_task(coro)
            task.add_done_callback(lambda t: self._on_task_done(task_name, t))
            return task
        except RuntimeError as e:
            logger.error(f"{LOG_PREFIX} 无法启动后台任务 {task_name}: {e}")
            return None

    def _on_task_done(self, task_name: str, task: asyncio.Task):
        try:
            exc = task.exception()
            if exc:
                logger.error(f"{LOG_PREFIX} 后台任务 {task_name} 异常: {exc}")
        except asyncio.CancelledError:
            pass

    async def _initialize(self):
        self._ensure_runtime_locks()
        await self._claim_active_instance()
        if not self._is_active_instance():
            return
        logger.info(f"{LOG_PREFIX} 正在初始化...")
        await self._ensure_services()
        await self._register_tasks()
        logger.info(f"{LOG_PREFIX} 初始化完成")

    def _is_active_instance(self) -> bool:
        cls = type(self)
        return (
            not self._runtime_cleaned
            and cls._active_instance is self
            and cls._active_generation == self._instance_generation
        )

    async def _claim_active_instance(self):
        cls = type(self)
        old_instance = cls._active_instance
        if old_instance and old_instance is not self:
            logger.warning(
                f"{LOG_PREFIX} 检测到旧实例仍在运行，准备清理旧实例 generation={old_instance._instance_generation}"
            )
            await old_instance._cleanup_runtime(reason="replaced_by_new_instance")
        cls._active_instance = self
        cls._active_generation = self._instance_generation

    def _add_or_replace_job(self, func, trigger, *, job_id: str, **kwargs):
        options = {
            "id": job_id,
            "replace_existing": True,
        }
        options.update(kwargs)
        self.scheduler.add_job(func, trigger, **options)

    def _ensure_runtime_locks(self):
        if self._cleanup_lock is None:
            self._cleanup_lock = asyncio.Lock()
        if self._schedule_reminder_scan_lock is None:
            self._schedule_reminder_scan_lock = asyncio.Lock()
        if self._apple_calendar_sync_lock is None:
            self._apple_calendar_sync_lock = asyncio.Lock()

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

    async def _close_external_clients(self):
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

    async def _cleanup_runtime(self, reason: str = "terminate"):
        self._ensure_runtime_locks()
        if self._runtime_cleaned:
            return
        async with self._cleanup_lock:
            if self._runtime_cleaned:
                return
            self._runtime_cleaned = True

            init_task = self._init_task
            current_task = asyncio.current_task()
            if init_task and init_task is not current_task and not init_task.done():
                init_task.cancel()
                try:
                    await init_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.warning(f"{LOG_PREFIX} 等待初始化任务结束时出错: {e}")

            try:
                if hasattr(self.scheduler, "get_jobs"):
                    for job in list(self.scheduler.get_jobs()):
                        try:
                            self.scheduler.remove_job(job.id)
                            logger.debug(f"{LOG_PREFIX} 已移除任务: {job.id}")
                        except Exception:
                            pass
                if self.scheduler.running:
                    self.scheduler.shutdown(wait=False)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} 关闭调度器时出错: {e}")

            await self._close_external_clients()

            cls = type(self)
            if cls._active_instance is self:
                cls._active_instance = None
                cls._active_generation = 0
            logger.info(f"{LOG_PREFIX} 插件运行时资源已清理 reason={reason}")

    async def _ensure_services(self):
        if self._services_ready:
            return
        self._services_ready = True

        conf = self.config

        # 注册 LLM 日程管理工具（需要等服务初始化完成后）
        if not self._tools_registered:
            register_schedule_tools(self)
            self._tools_registered = True

        api_key = self.config.get("weather_api_key")
        city = self.config.get("weather_city", "杭州")
        if api_key:
            self.weather_service = WeatherService({"weather_api_key": api_key, "weather_city": city})

        self.llm_service = LLMService(self.context)
        self.dashboard_service = DashboardService()

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
                            logger.warning(f"{LOG_PREFIX} notion_db_ids 使用无前缀字符串，已按顺序第1个映射为「事务库」")
                        elif not reading_db:
                            reading_db = raw
                            logger.warning(f"{LOG_PREFIX} notion_db_ids 使用无前缀字符串，已按顺序第2个映射为「阅读库」")
                        elif raw:
                            logger.warning(f"{LOG_PREFIX} notion_db_ids 额外无前缀字符串未使用: {raw[:12]}...")
                self.notion = NotionClient(maton_key, transaction_db, reading_db)
                self.notion_service = NotionService(self.notion)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} Notion 初始化失败: {e}")
                self.notion = None
                self.notion_service = None

        self.briefing_reminder = BriefingReminder(self.config, self.context, self.llm_service)
        self.bath_reminder = BathReminder(self.config, self.default_user_id, self.llm_service, self.store)
        self.sleep_reminder = SleepReminder(self.config, self.default_user_id, self.llm_service, self.store)
        self.water_reminder = WaterReminder(self.config, self.default_user_id, self.llm_service, self.store)
        self.schedule_reminder = ScheduleReminder(self.llm_service, self.dashboard_service)

        if conf.get("enable_apple_calendar_sync"):
            apple_conf = conf.get("apple_calendar", {})
            username = apple_conf.get("username") if apple_conf else None
            app_password = apple_conf.get("app_password") if apple_conf else None
            if username and app_password:
                self.apple_calendar = AppleCalendar(username=username, app_password=app_password)
                logger.info(f"{LOG_PREFIX} Apple Calendar 已配置: {username[:3]}***")
            else:
                logger.warning(f"{LOG_PREFIX} Apple Calendar 未配置凭据（username 或 app_password 缺失）")

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
            logger.info(f"{LOG_PREFIX} Apple 日历同步任务已注册（每 {sync_interval} 分钟）")

        if conf.get("enable_schedule_reminder"):
            self._add_or_replace_job(
                self._schedule_reminder_scan,
                CronTrigger(second=30),
                job_id="schedule_reminder_scan",
                # 防重入/堆积：单实例执行，misfire 时合并，避免重启后集中补跑。
                max_instances=1,
                coalesce=True,
                misfire_grace_time=30,
            )
            logger.info(f"{LOG_PREFIX} 日程 LLM 提醒已启用（每分钟）")

        if conf.get("enable_water_reminder", True):
            water_interval = conf.get("water_interval", DEFAULT_WATER_INTERVAL)
            water_start = conf.get("water_start_time", DEFAULT_WATER_START)
            water_end = conf.get("water_end_time", DEFAULT_WATER_END)

            now = datetime.now()
            next_trigger = self._get_water_next_trigger(now, water_start, water_end, water_interval)
            initial_delay = max((next_trigger - now).total_seconds(), 30.0)

            self._schedule_next_water_reminder(datetime.now() + timedelta(seconds=initial_delay))
            logger.info(f"{LOG_PREFIX} 喝水提醒首次触发: {next_trigger.strftime('%H:%M')} ({initial_delay/60:.1f}分钟后)")

        self._add_or_replace_job(
            self._clear_expired_overrides,
            CronTrigger(hour=0, minute=5),
            job_id="clear_expired_overrides",
        )
        if not self.scheduler.running:
            self.scheduler.start()

        logger.info(f"{LOG_PREFIX} 所有定时任务已注册，调度器已启动")

    def _get_water_next_trigger(self, now: datetime, water_start: str, water_end: str, water_interval: int) -> datetime:
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

    def _parse_user_platform_bindings(self) -> Dict[str, str]:
        bindings: Dict[str, str] = {}
        raw_bindings = self.config.get("user_platform_bindings", []) or []
        for item in raw_bindings:
            user_id = ""
            platform_id = ""
            if isinstance(item, dict):
                user_id = str(item.get("user_id", "")).strip()
                platform_id = str(item.get("platform_id", "")).strip()
            elif isinstance(item, str) and ":" in item:
                user_id, platform_id = item.split(":", 1)
                user_id = user_id.strip()
                platform_id = platform_id.strip()
            if user_id and platform_id:
                bindings[user_id] = platform_id
        return bindings

    def _get_available_platform_ids(self) -> List[str]:
        ids: List[str] = []
        try:
            for platform in self.context.platform_manager.platform_insts:
                pid = platform.meta().id
                if pid:
                    ids.append(str(pid))
        except Exception:
            pass
        if not ids:
            fallback_platform = self._global_platform_id or "aiocqhttp"
            logger.warning(f"{LOG_PREFIX} 未发现已注册平台，使用回退平台: {fallback_platform}")
            ids = [fallback_platform]
        return ids

    def _extract_platform_id_from_event(self, event: AiocqhttpMessageEvent) -> Optional[str]:
        for attr in ("platform_id", "platform", "platform_name"):
            value = getattr(event, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for attr in ("session_id", "session", "unified_msg_origin"):
            value = getattr(event, attr, None)
            if isinstance(value, str) and ":" in value:
                return value.split(":", 1)[0].strip()
        if isinstance(event, AiocqhttpMessageEvent):
            return "aiocqhttp"
        return None

    def _remember_user_platform(self, user_id: str, event: AiocqhttpMessageEvent):
        platform_id = self._extract_platform_id_from_event(event)
        if platform_id:
            self._recent_user_platforms[str(user_id)] = platform_id

    async def _get_target_user_ids(self, include_known_users: bool = False) -> List[str]:
        user_ids = set()
        if self.default_user_id:
            user_ids.add(str(self.default_user_id))
        for uid in self.config.get("whitelist_qq_ids", []) or []:
            if uid:
                user_ids.add(str(uid))
        for uid in self.config.get("target_user_ids", []) or []:
            if uid:
                user_ids.add(str(uid))
        if include_known_users or self.config.get("broadcast_to_all_known_users", False):
            for uid in await self.store.get_all_users():
                if uid:
                    user_ids.add(str(uid))
        return sorted(user_ids)

    def _build_platform_candidates(self, user_id: str, preferred_platform: Optional[str] = None) -> List[str]:
        candidates: List[str] = []
        if preferred_platform:
            candidates.append(str(preferred_platform).strip())
        recent = self._recent_user_platforms.get(str(user_id))
        if recent:
            candidates.append(recent)
        bound = self._user_platform_bindings.get(str(user_id))
        if bound:
            candidates.append(bound)
        if self._global_platform_id:
            candidates.append(self._global_platform_id)
        candidates.extend(self._get_available_platform_ids())
        seen = set()
        ordered = []
        for pid in candidates:
            if pid and pid not in seen:
                ordered.append(pid)
                seen.add(pid)
        return ordered

    def _extract_block_lines(self, block: str, remove_pipe: bool = False) -> List[str]:
        if not block or block in ("暂无", "获取失败"):
            return []
        rows = []
        for line in block.split("\n"):
            clean = line.strip()
            if not clean:
                continue
            if remove_pipe:
                clean = clean.replace("|", " ")
            rows.append(clean)
        return rows

    def _merge_today_schedule_blocks(self, local_text: str, apple_text: str, limit: int = 12) -> str:
        merged = []
        seen = set()
        for line in self._extract_block_lines(local_text) + self._extract_block_lines(apple_text):
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

    async def _send_to_user(self, user_id: str, message: str, platform_id: Optional[str] = None):
        try:
            chain = MessageChain([Plain(message)])
            available = set(self._get_available_platform_ids())
            sessions_tried = []
            for platform in self._build_platform_candidates(user_id, platform_id):
                if platform not in available:
                    logger.warning(
                        f"{LOG_PREFIX} 发送目标平台不可用: platform={platform} user={user_id} available={sorted(available)}"
                    )
                    continue
                session = f"{platform}:{self._session_type}:{user_id}"
                sessions_tried.append(session)
                try:
                    await self.context.send_message(session, chain)
                    self._recent_user_platforms[str(user_id)] = platform
                    logger.info(f"{LOG_PREFIX} 发送成功 user={user_id} platform={platform}")
                    return
                except Exception as send_err:
                    logger.warning(
                        f"{LOG_PREFIX} 发送失败 user={user_id} platform={platform} err={send_err}"
                    )
            logger.error(f"{LOG_PREFIX} 发送消息失败，已尝试所有可用平台: user={user_id} sessions={sessions_tried}")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 发送消息异常: user={user_id} err={e}")

    async def _get_user_schedules(self, user_id: str) -> List[ScheduleItem]:
        schedules_dict = await self.store.get_schedules(user_id)
        return schedules_dict.get(SCHEDULES_KEY, [])

    async def _get_today_local_schedules_text(self, user_id: str, limit: int = 8) -> str:
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
        return "\n".join([f"⏰ {dt.strftime('%H:%M')} │ {title}" for dt, title in today_items[:limit]])

    async def _get_today_apple_calendar_text(self, limit: int = 8) -> str:
        if not self.apple_calendar:
            return "暂无"
        try:
            events = await self.apple_calendar.get_all_events(days=1)
            today = datetime.now().date()
            logger.info(f"{LOG_PREFIX} Apple日历获取到 {len(events)} 个事件，开始筛选今日({today})事件...")

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
            logger.info(f"{LOG_PREFIX} 今日 Apple 日历事件筛选完成，共 {len(rows)} 个: {[s for _, s in rows]}")
            return "\n".join([line for _, line in rows[:limit]])
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} Apple 今日日程读取失败: {e}")
            return "获取失败"

    async def _get_notion_pending_text(self, limit: int = 5) -> str:
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

    async def _morning_briefing(self, target_user_id: Optional[str] = None):
        if not self._is_active_instance():
            return
        try:
            await self._ensure_services()
            target_user_ids = [str(target_user_id)] if target_user_id else await self._get_target_user_ids()
            if not target_user_ids:
                return

            weather_current, weather_forecast = "", ""
            if self.weather_service:
                weather_current, weather_forecast = await self.weather_service.fetch()

            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            weekday_str = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]

            dashboard_status = await get_dashboard_status() if self.dashboard_service else "暂无"
            late_night_text = ""
            if self.apple_calendar:
                try:
                    late_night = await self.apple_calendar.get_late_night_events()
                    late_night_text = "、".join([e.get("summary", "无标题") for e in late_night[:3]])
                except Exception:
                    late_night_text = ""

            for user_id in target_user_ids:
                local_text = await self._get_today_local_schedules_text(user_id)
                apple_text = await self._get_today_apple_calendar_text()
                agenda_text = self._merge_today_schedule_blocks(local_text, apple_text)
                notion_text = await self._get_notion_pending_text()

                briefing = await self.briefing_reminder.generate_full_report(
                    username="用户",
                    date=date_str,
                    weekday=weekday_str,
                    weather_current=weather_current,
                    weather_forecast=weather_forecast,
                    agenda=agenda_text,
                    notion_todos=notion_text,
                    dashboard=dashboard_status,
                    late_night=late_night_text
                )
                await self._send_to_user(user_id, briefing)
            logger.info(f"{LOG_PREFIX} 早安播报已发送 users={target_user_ids}")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 早安播报失败: {e}")

    async def _bath_reminder(self, target_user_id: Optional[str] = None):
        if not self._is_active_instance():
            return
        try:
            await self._ensure_services()
            target_user_ids = [str(target_user_id)] if target_user_id else await self._get_target_user_ids()
            if not target_user_ids:
                return

            dashboard = await get_dashboard_status() if self.dashboard_service else ""
            for user_id in target_user_ids:
                history = await self.store.get_conversation_history(user_id)
                history_text = self.store.format_history_for_prompt(history[-5:]) if history else ""
                message = await self.bath_reminder.generate("用户", dashboard, history_text)
                if message:
                    await self._send_to_user(user_id, message)
            logger.info(f"{LOG_PREFIX} 洗澡提醒已发送 users={target_user_ids}")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 洗澡提醒失败: {e}")

    async def _sleep_reminder(self, target_user_id: Optional[str] = None):
        if not self._is_active_instance():
            return
        try:
            await self._ensure_services()
            target_user_ids = [str(target_user_id)] if target_user_id else await self._get_target_user_ids()
            if not target_user_ids:
                return

            dashboard = await get_dashboard_status() if self.dashboard_service else ""
            for user_id in target_user_ids:
                history = await self.store.get_conversation_history(user_id)
                history_text = self.store.format_history_for_prompt(history[-5:]) if history else ""
                message = await self.sleep_reminder.generate("用户", dashboard, history_text)
                if message:
                    await self._send_to_user(user_id, message)
            logger.info(f"{LOG_PREFIX} 睡觉提醒已发送 users={target_user_ids}")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 睡觉提醒失败: {e}")

    async def _water_reminder(self, target_user_id: Optional[str] = None):
        if not self._is_active_instance():
            return
        try:
            await self._ensure_services()
            target_user_ids = [str(target_user_id)] if target_user_id else await self._get_target_user_ids()
            if not target_user_ids:
                return

            dashboard = await get_dashboard_status() if self.dashboard_service else ""
            for user_id in target_user_ids:
                history = await self.store.get_conversation_history(user_id)
                history_text = self.store.format_history_for_prompt(history[-5:]) if history else ""
                message = await self.water_reminder.generate("用户", dashboard, history_text)
                if message:
                    await self._send_to_user(user_id, message)
            logger.info(f"{LOG_PREFIX} 喝水提醒已发送 users={target_user_ids}")

            water_interval = self.config.get("water_interval", DEFAULT_WATER_INTERVAL)
            water_start = self.config.get("water_start_time", DEFAULT_WATER_START)
            water_end = self.config.get("water_end_time", DEFAULT_WATER_END)

            next_trigger = self._get_water_next_trigger(
                datetime.now() + timedelta(minutes=water_interval),
                water_start, water_end, water_interval
            )
            delay = max((next_trigger - datetime.now()).total_seconds(), 30.0)

            self._schedule_next_water_reminder(datetime.now() + timedelta(seconds=delay))
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 喝水提醒失败: {e}")

    async def _schedule_scan(self):
        if not self._is_active_instance():
            return
        logger.debug(f"{LOG_PREFIX} 执行日程扫描")

    async def _schedule_reminder_scan(self):
        self._ensure_runtime_locks()
        if not self._is_active_instance():
            return
        lock = self._schedule_reminder_scan_lock
        try:
            await asyncio.wait_for(lock.acquire(), timeout=0)
        except asyncio.TimeoutError:
            logger.debug(f"{LOG_PREFIX} 日程提醒扫描仍在运行，跳过本轮")
            return
        try:
            now_ts = time.monotonic()
            if now_ts - self._schedule_reminder_last_log_ts >= SCHEDULE_REMINDER_LOG_THROTTLE_SECONDS:
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
                        logger.warning(f"{LOG_PREFIX} schedule_reminder_minutes 非数字，使用默认值 10")
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
                            await self._send_to_user(user_id, item["reminder_text"])
                except Exception as e:
                    logger.warning(f"{LOG_PREFIX} 用户 {user_id} 日程提醒扫描失败: {e}")
        finally:
            lock.release()

    async def _apple_calendar_sync(self):
        self._ensure_runtime_locks()
        if not self._is_active_instance():
            return
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
                user_ids = await self._get_target_user_ids(include_known_users=True)
                if not user_ids:
                    logger.debug(f"{LOG_PREFIX} Apple Calendar 已读取 {len(events)} 个事件，但无可同步用户")
                    return
                for user_id in user_ids:
                    stats = await self.store.sync_from_apple_calendar(user_id, events)
                    logger.debug(
                        f"{LOG_PREFIX} Apple→本地同步 user={user_id} "
                        f"added={stats['added']} updated={stats['updated']} deleted={stats['deleted']}"
                    )
            except Exception as e:
                logger.error(f"{LOG_PREFIX} Apple Calendar 同步失败: {e}")
        finally:
            lock.release()

    async def _clear_expired_overrides(self):
        if not self._is_active_instance():
            return
        for user_id in await self._get_target_user_ids(include_known_users=True):
            await self.store.clear_expired_overrides(user_id)
        logger.debug(f"{LOG_PREFIX} 已清理过期临时修改")

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def handle_private_message(self, event: AiocqhttpMessageEvent):
        user_id = str(event.get_sender_id())
        msg_text = event.message_str.strip()
        self._remember_user_platform(user_id, event)

        if msg_text:
            await self.store.add_conversation_message(user_id, "user", msg_text)

        if msg_text.startswith("/"):
            await self._handle_command(event, user_id, msg_text)
        elif msg_text.startswith("添加") or msg_text.startswith("新增"):
            await self._handle_add(event, user_id, msg_text)
        elif msg_text.startswith("删除") or msg_text.startswith("取消"):
            await self._handle_delete(event, user_id, msg_text)
        elif msg_text.startswith("查看") or msg_text.startswith("列表"):
            await self._handle_list(event, user_id)
        elif msg_text.startswith("跳过"):
            await self._handle_skip(event, user_id, msg_text)
        elif msg_text.startswith("修改时间"):
            await self._handle_modify_time(event, user_id, msg_text)
        elif msg_text == "帮助" or msg_text == "help":
            await self._handle_help(event)
        elif msg_text == "早安" or msg_text == "天气":
            await self._morning_briefing(user_id)
            await event.reply("早安播报已生成~")
        elif msg_text == "喝水":
            await self._water_reminder(user_id)
            await event.reply("喝水提醒已触发~")
        else:
            pass

    async def _handle_command(self, event: AiocqhttpMessageEvent, user_id: str, cmd: str):
        if cmd.startswith("/日程"):
            sub = cmd[3:].strip()
            if sub in ("", "列表", "查看"):
                await self._handle_list(event, user_id)
            elif sub.startswith("添加") or sub.startswith("新增"):
                await self._handle_add(event, user_id, sub)
            elif sub.startswith("删除") or sub.startswith("取消"):
                await self._handle_delete(event, user_id, sub)
            elif sub.startswith("跳过"):
                await self._handle_skip(event, user_id, sub)
            elif sub.startswith("修改时间"):
                await self._handle_modify_time(event, user_id, sub)
            elif sub == "帮助":
                await self._handle_help(event)
            else:
                await event.reply("未知命令，输入 /日程帮助 查看可用命令~")
        elif cmd == "/喝水":
            await self._water_reminder(user_id)
            await event.reply("喝水提醒已触发~")
        elif cmd == "/早安" or cmd == "/天气":
            await self._morning_briefing(user_id)
            await event.reply("早安播报已生成~")
        elif cmd == "/洗澡":
            await self._bath_reminder(user_id)
            await event.reply("洗澡提醒已触发~")
        elif cmd == "/睡觉":
            await self._sleep_reminder(user_id)
            await event.reply("睡觉提醒已触发~")

    async def _handle_add(self, event: AiocqhttpMessageEvent, user_id: str, text: str):
        time_match = re.search(r'(\d{1,2})[:：时](\d{0,2})', text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or "0")
            content = re.sub(r'(\d{1,2})[:：时](\d{0,2})', '', text).strip()
            content = content.replace("添加", "").replace("新增", "").strip()

            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                await event.reply("时间格式有误，请检查~ (小时 0-23，分钟 0-59)")
                return

            item = ScheduleItem(
                type="schedule",
                title=content or "待办",
                time=datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M"),
            )
            await self.store.add_item(user_id, item)
            await event.reply(f"日程已添加：{content or '待办'} @ {hour:02d}:{minute:02d}")
        else:
            await event.reply("请告诉我时间哦~ 比如「添加 14:30 开会」")

    async def _handle_delete(self, event: AiocqhttpMessageEvent, user_id: str, text: str):
        idx_match = re.search(r'#?(\d+)', text)
        if idx_match:
            idx = int(idx_match.group(1)) - 1
            schedules = await self._get_user_schedules(user_id)
            if 0 <= idx < len(schedules):
                item = schedules[idx]
                await self.store.remove_item(user_id, item.id)
                await event.reply(f"已删除：{item.title}")
            else:
                await event.reply("编号超出范围~")
        else:
            await event.reply("请告诉我要删除的编号~ 比如「删除 #1」")

    async def _handle_list(self, event: AiocqhttpMessageEvent, user_id: str):
        schedules = await self._get_user_schedules(user_id)
        if not schedules:
            await event.reply("暂无日程安排，输入「添加 14:30 开会」来添加~")
            return

        lines = ["📅 你的日程："]
        for i, item in enumerate(schedules, 1):
            time_str = item.time[:16] if item.time else "未定"
            lines.append(f"{i}. {item.title} @ {time_str}")
        await event.reply("\n".join(lines))

    async def _handle_skip(self, event: AiocqhttpMessageEvent, user_id: str, text: str):
        reminder_type = text.replace("跳过", "").strip()
        if reminder_type in ("喝水", "bath"):
            await event.reply(f"已跳过本次{reminder_type}提醒~")
        elif reminder_type in ("洗澡", "睡觉"):
            await event.reply(f"已跳过本次{reminder_type}提醒~")
        else:
            await event.reply("请告诉我跳过什么~ 如「跳过喝水」")

    async def _handle_modify_time(self, event: AiocqhttpMessageEvent, user_id: str, text: str):
        parts = text.replace("修改时间", "").strip().split(" ")
        if len(parts) >= 2:
            habit_name = parts[0]
            new_time = parts[1]
            success = await self.store.set_temp_override(user_id, habit_name, new_time)
            if success:
                await event.reply(f"已临时修改{habit_name}时间为 {new_time}~（仅今天生效）")
            else:
                await event.reply("不支持的 habit 类型，支持：喝水/洗澡/睡觉")
        else:
            await event.reply("格式不对哦~ 如「修改时间 喝水 10:30」")

    async def _handle_help(self, event: AiocqhttpMessageEvent):
        help_text = """📌 日程小贴士使用指南

📝 添加日程：添加 14:30 开会
📋 查看日程：查看 / 日程列表
🗑️ 删除日程：删除 #1
⏭️ 跳过提醒：跳过喝水
⏰ 修改习惯时间：修改时间 喝水 10:30

💡 快捷命令：
/喝水 - 立即提醒喝水
/早安 - 生成早安播报
/洗澡 - 立即提醒洗澡
/睡觉 - 立即提醒睡觉

✨ 也可以直接用自然语言管理日程：
"帮我加个明天9点开组会"
"看看这周有什么安排"
"删除明天的读书会"
"""
        await event.reply(help_text)

    async def terminate(self):
        """插件卸载时清理定时任务"""
        await self._cleanup_runtime(reason="terminate")

    async def on_unload(self):
        await self._cleanup_runtime(reason="on_unload")


async def __initialize(context: Context) -> ScheduleAssistant:
    config = context.get_config().get("schedule_assistant", {})
    assistant = ScheduleAssistant(context, config)
    return assistant
