import json
import re
import asyncio
import aiohttp
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
    CONVERSATION_KEY,
    CONVERSATION_MAX_MESSAGES,
)

from .services.weather import WeatherService
from .services.notion import NotionService
from .services.dashboard import DashboardService, get_dashboard_status
from .services.llm import LLMService
from .reminders.briefing import BriefingReminder
from .reminders.bath import BathReminder
from .reminders.sleep import SleepReminder
from .reminders.water import WaterReminder


class ScheduleAssistant(Star):
    def __init__(self, context: Context, config: Dict[str, Any]):
        super().__init__(context)
        self.config = config
        self.store = ScheduleStore(context)
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        # 服务初始化（按需，失败不影响其他功能）
        self.weather_service: Optional[WeatherService] = None
        self.notion_service: Optional[NotionService] = None
        self._services_ready = False
        self._tasks_registered = False
        self._init_task: Optional[asyncio.Task] = None

        # 常用配置
        self.default_user_id: Optional[str] = None
        whitelist = self.config.get("whitelist_qq_ids", [])
        if whitelist:
            self.default_user_id = str(whitelist[0])

        # 插件加载时自动初始化
        self._init_task = self._schedule_task(self._initialize(), "initialize")

    def _schedule_task(self, coro, task_name: str) -> Optional[asyncio.Task]:
        """创建后台任务，统一处理异常"""
        try:
            task = asyncio.create_task(coro)
            task.add_done_callback(lambda t: self._on_task_done(task_name, t))
            return task
        except RuntimeError as e:
            logger.error(f"{LOG_PREFIX} 无法启动后台任务 {task_name}: {e}")
            return None

    def _on_task_done(self, task_name: str, task: asyncio.Task):
        """后台任务完成时的回调"""
        try:
            exc = task.exception()
            if exc:
                logger.error(f"{LOG_PREFIX} 后台任务 {task_name} 异常: {exc}")
        except asyncio.CancelledError:
            pass

    async def _initialize(self):
        """插件初始化：加载外部服务 + 注册定时任务"""
        logger.info(f"{LOG_PREFIX} 正在初始化...")

        # 1. 初始化外部服务
        await self._ensure_services()

        # 2. 注册定时任务
        await self._register_tasks()

        logger.info(f"{LOG_PREFIX} 初始化完成")

    async def _ensure_services(self):
        """初始化外部服务（失败不阻断主流程）"""
        if self._services_ready:
            return
        self._services_ready = True
        conf = self.config

        # Weather
        api_key = self.config.get("weather_api_key")
        city = self.config.get("weather_city", "杭州")
        if api_key:
            self.weather_service = WeatherService({"weather_api_key": api_key, "weather_city": city})

        # LLM
        try:
            self.llm_service = LLMService(self.context)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} LLM 服务初始化失败: {e}")


        # Dashboard
        self.dashboard_service = DashboardService()

        # Notion
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
                self.notion = NotionClient(
                    maton_key,
                    transaction_db,
                    reading_db,
                )
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} Notion 初始化失败: {e}")

        # 提醒服务
        self.briefing_reminder = BriefingReminder(self.config, self.context, self.llm_service)
        self.bath_reminder = BathReminder(self.config, self.default_user_id, self.llm_service, self.store)
        self.sleep_reminder = SleepReminder(self.config, self.default_user_id, self.llm_service, self.store)
        self.water_reminder = WaterReminder(self.config, self.default_user_id, self.llm_service, self.store)
        self.schedule_reminder = ScheduleReminder(self.llm_service, self.dashboard_service)

        # Apple Calendar（按需初始化）
        if conf.get("enable_apple_calendar_sync"):
            apple_conf = conf.get("apple_calendar", {})
            self.apple_calendar = AppleCalendar(
                username=apple_conf.get("username"),
                app_password=apple_conf.get("app_password"),
            )

        logger.info(f"{LOG_PREFIX} 外部服务初始化完成")

    async def _register_tasks(self):
        """注册所有定时任务（仅注册一次）"""
        if self._tasks_registered:
            return
        self._tasks_registered = True
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
            logger.info(f"{LOG_PREFIX} 睡觉提醒已注册: {sleep_time}")

        # Apple 日历同步
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

        # 日程 LLM 提醒
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


        # Notion DDL 检查
        self.scheduler.add_job(
            self._notion_ddl_check,
            CronTrigger(minute=0),
            id="notion_ddl_check",
            replace_existing=True
        )

        # 清理过期临时修改
        self.scheduler.add_job(
            self._clear_expired_overrides,
            CronTrigger(hour=0, minute=5),
            id="clear_expired_overrides",
            replace_existing=True
        )

        # 用户日程扫描
        self.scheduler.add_job(
            self._schedule_scan,
            CronTrigger(minute=1),
            id="schedule_scan",
            replace_existing=True
        )

        # 启动调度器
        if not self.scheduler.running:
            self.scheduler.start()


        logger.info(f"{LOG_PREFIX} 所有定时任务已注册，调度器已启动")

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
        elapsed = now - today_start
        next_time = today_start + (elapsed // interval_min + 1) * interval_min
        if next_time > today_end:
            return today_start + timedelta(days=1)
        return next_time

    async def _send_to_user(self, user_id: str, message: str):
        """发送消息给用户（私聊）"""
        try:
            platform = self._get_platform_id()
            session = f"{platform}:PrivateMessage:{user_id}"
            chain = MessageChain([Plain(message)])
            await self.context.context.context.send_message(session, chain)
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 发送消息失败: {e}")

    async def _get_user_schedules(self, user_id: str) -> List[ScheduleItem]:
        """获取用户日程列表"""
        schedules_dict = await self.store.get_schedules(user_id)
        return schedules_dict.get(SCHEDULES_KEY, [])

    async def _morning_briefing(self):
        """早安播报"""
        try:
            await self._ensure_services()
            user_id = self.default_user_id
            if not user_id:
                return

            weather_current, weather_forecast = "", ""
            if self.weather_service:
                weather_current, weather_forecast = await self.weather_service.fetch()


            schedules = await self._get_user_schedules(user_id)
            schedules_text = "\n".join([f"⏰ {s.time[:16]} │ {s.title}" for s in schedules[:5]]) if schedules else "暂无"

            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            weekday_str = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]

            dashboard_status = await get_dashboard_status() if hasattr(self, 'dashboard_service') else "暂无"


            briefing = await self.briefing_reminder.generate_full_report(
                username="用户",
                date=date_str,
                weekday=weekday_str,
                weather_current=weather_current,
                weather_forecast=weather_forecast,
                calendar="暂无",
                schedules=schedules_text,
                notion="暂无",
                dashboard=dashboard_status,
                late_night=""
            )
            await self._send_to_user(user_id, briefing)
            logger.info(f"{LOG_PREFIX} 早安播报已发送")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 早安播报失败: {e}")

    async def _bath_reminder(self):
        """洗澡提醒"""
        try:
            await self._ensure_services()
            user_id = self.default_user_id
            if not user_id:
                return

            dashboard = await get_dashboard_status() if hasattr(self, 'dashboard_service') and self.dashboard_service else ""
            history = await self.store.get_conversation_history(user_id)
            history_text = self.store.format_history_for_prompt(history[-5:]) if history else ""
            message = await self.bath_reminder.generate("用户", dashboard, history_text)
            if message:
                await self._send_to_user(user_id, message)
                logger.info(f"{LOG_PREFIX} 洗澡提醒已发送")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 洗澡提醒失败: {e}")


    async def _sleep_reminder(self):
        """睡觉提醒"""
        try:
            await self._ensure_services()
            user_id = self.default_user_id
            if not user_id:
                return

            dashboard = await get_dashboard_status() if hasattr(self, 'dashboard_service') and self.dashboard_service else ""
            history = await self.store.get_conversation_history(user_id)
            history_text = self.store.format_history_for_prompt(history[-5:]) if history else ""
            message = await self.sleep_reminder.generate("用户", dashboard, history_text)
            if message:
                await self._send_to_user(user_id, message)
                logger.info(f"{LOG_PREFIX} 睡觉提醒已发送")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 睡觉提醒失败: {e}")

    async def _water_reminder(self):
        """喝水提醒"""
        try:
            await self._ensure_services()
            user_id = self.default_user_id
            if not user_id:
                return

            dashboard = await get_dashboard_status() if hasattr(self, 'dashboard_service') and self.dashboard_service else ""
            history = await self.store.get_conversation_history(user_id)
            history_text = self.store.format_history_for_prompt(history[-5:]) if history else ""

            message = await self.water_reminder.generate("用户", dashboard, history_text)
            if message:
                await self._send_to_user(user_id, message)
                logger.info(f"{LOG_PREFIX} 喝水提醒已发送")

            water_interval = self.config.get("water_interval", DEFAULT_WATER_INTERVAL)
            water_start = self.config.get("water_start_time", DEFAULT_WATER_START)
            water_end = self.config.get("water_end_time", DEFAULT_WATER_END)

            next_trigger = self._get_water_next_trigger(
                datetime.now() + timedelta(minutes=water_interval),
                water_start, water_end, water_interval
            )
            delay = max((next_trigger - datetime.now()).total_seconds(), 30.0)


            try:
                self.scheduler.remove_job("water_reminder")
            except Exception:
                pass
            self.scheduler.add_job(
                self._water_reminder,
                "date",
                run_date=datetime.now() + timedelta(seconds=delay),
                id="water_reminder",
                replace_existing=True
            )
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 喝水提醒失败: {e}")

    async def _schedule_scan(self):
        """定期扫描用户会话"""
        logger.debug(f"{LOG_PREFIX} 执行日程扫描")


    async def _notion_ddl_check(self):
        """检查 Notion DDL"""
        logger.debug(f"{LOG_PREFIX} 执行 Notion DDL 检查")

    async def _schedule_reminder_scan(self):
        """日程 LLM 提醒扫描"""
        logger.debug(f"{LOG_PREFIX} 执行日程提醒扫描")
        if not hasattr(self, "llm_service") or not self.llm_service:
            return

        now = datetime.now()
        window_end = now + timedelta(minutes=80)

        for user_id in self.store.get_all_users():
            items = await self.store.list_all_items(user_id)
            for item in items:
                if item.time and now <= datetime.fromisoformat(item.time.replace(" ", "T")) <= window_end:
                    try:
                        message = await self.schedule_reminder.generate_reminder_text(
                            item_title=item.title,
                            item_time=item.time,
                            item_context=item.context,
                            item_type=item.type,
                            minutes_ahead=10,
                        )
                        if message:
                            await self._send_to_user(user_id, message)
                    except Exception as e:
                        logger.warning(f"{LOG_PREFIX} LLM 提醒生成失败: {e}")

    async def _apple_calendar_sync(self):
        """Apple 日历同步"""
        if not hasattr(self, 'apple_calendar') or not self.apple_calendar:
            return
        try:
            events = await self.apple_calendar.get_all_events(days=7)
            logger.info(f"{LOG_PREFIX} Apple Calendar 同步到 {len(events)} 个事件")
            # TODO: 写入本地日程
        except Exception as e:
            logger.error(f"{LOG_PREFIX} Apple Calendar 同步失败: {e}")


    async def _clear_expired_overrides(self):
        """清理过期临时修改"""
        if self.default_user_id:
            await self.store.clear_expired_overrides(self.default_user_id)
        logger.debug(f"{LOG_PREFIX} 已清理过期临时修改")

    def _get_platform_id(self) -> str:
        """获取当前平台标识"""
        return self.context.get_platform_name()


    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def handle_private_message(self, event: AiocqhttpMessageEvent):
        """处理私聊消息"""
        user_id = str(event.get_sender_id())
        msg_text = event.message_str.strip()

        if msg_text:
            await self.store.add_conversation_message(user_id, "user", msg_text)

        # 解析命令
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
            await self._morning_briefing()
            await event.reply("早安播报已生成~")
        elif msg_text == "喝水":
            await self._water_reminder()
            await event.reply("喝水提醒已触发~")
        else:
            pass

    async def _handle_command(self, event: AiocqhttpMessageEvent, user_id: str, cmd: str):
        """处理斜杠命令"""
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
            await self._water_reminder()
            await event.reply("喝水提醒已触发~")
        elif cmd == "/早安" or cmd == "/天气":
            await self._morning_briefing()
            await event.reply("早安播报已生成~")
        elif cmd == "/洗澡":
            await self._bath_reminder()
            await event.reply("洗澡提醒已触发~")
        elif cmd == "/睡觉":
            await self._sleep_reminder()
            await event.reply("睡觉提醒已触发~")

    async def _handle_add(self, event: AiocqhttpMessageEvent, user_id: str, text: str):
        """处理添加日程"""
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
        """处理删除日程"""
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
        """处理查看日程"""
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
        """处理跳过提醒"""
        reminder_type = text.replace("跳过", "").strip()
        if reminder_type in ("喝水", "bath"):
            await event.reply(f"已跳过本次{reminder_type}提醒~")
        elif reminder_type in ("洗澡", "睡觉"):
            await event.reply(f"已跳过本次{reminder_type}提醒~")
        else:
            await event.reply("请告诉我跳过什么~ 如「跳过喝水」")

    async def _handle_modify_time(self, event: AiocqhttpMessageEvent, user_id: str, text: str):
        """处理临时修改习惯时间"""
        parts = text.replace("修改时间", "").strip().split(" ")
        if len(parts) >= 2:
            habit_name = parts[0]
            new_time = parts[1]
            success = await self.store.set_temp_override(user_id, habit_name, new_time)
            if success:
                await event.reply(f"已临时修改{habit_name}时间为 {new_time}~（仅今日生效）")
            else:
                await event.reply("不支持的 habit 类型，支持：喝水/洗澡/睡觉")
        else:
            await event.reply("格式不对哦~ 如「修改时间 喝水 10:30」")

    async def _handle_help(self, event: AiocqhttpMessageEvent):
        """处理帮助"""
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
/睡觉 - 立即提醒睡觉"""
        await event.reply(help_text)


async def __initialize(context: Context) -> ScheduleAssistant:
    """插件初始化入口"""
    config = context.get_config().get("schedule_assistant", {})
    assistant = ScheduleAssistant(context, config)
    return assistant
