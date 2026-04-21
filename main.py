import re
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from star import Star
from star.llm import LLMService
from star.middlewares.types import MessageEvent
from star.decorators import on_agent, per_day, per_N_minutes
from star.utils import get_service
from star.platform import aiocqhttp

from .schedule_store import ScheduleStore, ScheduleItem, ReminderType
from .weather_service import WeatherService
from .notion_client import NotionClient

LOG_PREFIX = "[ScheduleAssistant]"
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_BATH_TIME = "22:00"
DEFAULT_SLEEP_TIME = "23:00"
DEFAULT_WATER_INTERVAL = 90  # 分钟
DEFAULT_WATER_START = "09:30"
DEFAULT_WATER_END = "21:30"


class ScheduleAssistant(Star):
    def __init__(self, context, config: Dict[str, Any]):
        super().__init__(context)
        self.config = config
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self.schedule_store = ScheduleStore()

        # 服务（延迟初始化）
        self.dashboard_service: Optional[DashboardService] = None
        self.llm_service: Optional[LLMService] = None
        self._services_ready = False
        self._tasks_registered = False

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
        try:
            self.llm_service = get_service(LLMService)
        except Exception:
            logger.warning(f"{LOG_PREFIX} 未找到 LLM Service，LLM 提醒功能不可用")

        # Dashboard
        try:
            self.dashboard_service = get_service(DashboardService)
        except Exception:
            pass

        # Notion
        maton_key = self.config.get("maton_api_key")
        db_ids_raw = self.config.get("notion_db_ids", [])
        if maton_key and db_ids_raw:
            db_map: Dict[str, str] = {}
            for item in db_ids_raw:
                if ":" in item:
                    name, db_id = item.split(":", 1)
                    db_map[name.strip()] = db_id.strip()
                else:
                    db_map["default"] = item.strip()
            self.notion = NotionClient(maton_key, db_map)

    async def _ensure_notion(self):
        """确保 Notion 客户端已初始化"""
        if self.notion is None:
            await self._ensure_services()
        return self.notion is not None

    # ── 消息处理 ───────────────────────────────────────────────────────────

    async def handle_private_message(self, event: MessageEvent):
        """处理私聊消息"""
        # 获取用户 ID
        user_id = str(event.get_sender_id())
        platform = self._get_platform_id()
        session_id = f"{platform}:{user_id}"

        # 延迟初始化外部服务
        asyncio.create_task(self._ensure_services())
        asyncio.create_task(self._register_tasks())

        msg_text = event.message_str.strip()
        if msg_text:
            await self.store.add_conversation_message(user_id, "user", msg_text)

        # 解析命令
        if msg_text.startswith("/"):
            await self._handle_command(event, user_id, msg_text, session_id)
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
        else:
            # 通用对话 → 更新最后交互时间
            self.schedule_store.touch_user(user_id)

    async def _handle_command(self, event: MessageEvent, user_id: str, cmd: str, session_id: str):
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

    async def _handle_add(self, event: MessageEvent, user_id: str, text: str):
        """处理添加日程"""
        # 提取时间（简化匹配）
        time_match = re.search(r'(\d{1,2})[:：时](\d{0,2})', text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or "0")
            # 移除时间部分，剩余为内容
            content = re.sub(r'(\d{1,2})[:：时](\d{0,2})', '', text).strip()
            content = content.replace("添加", "").replace("新增", "").strip()

            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                await event.reply("时间格式有误，请检查~ (小时 0-23，分钟 0-59)")
                return

            item = ScheduleItem(
                user_id=user_id,
                content=content or "待办",
                remind_type=ReminderType.ONCE,
                remind_time=datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
            )
            self.schedule_store.add_item(item)
            await event.reply(f"日程已添加：{content or '待办'} @ {hour:02d}:{minute:02d}")
        else:
            await event.reply("请告诉我时间哦~ 比如「添加 14:30 开会」")

    async def _handle_delete(self, event: MessageEvent, user_id: str, text: str):
        """处理删除日程"""
        # 提取编号或关键词
        idx_match = re.search(r'#?(\d+)', text)
        if idx_match:
            idx = int(idx_match.group(1)) - 1
            items = self.schedule_store.get_user_items(user_id)
            if 0 <= idx < len(items):
                item = items[idx]
                self.schedule_store.remove_item(item.id)
                await event.reply(f"已删除：{item.content}")
            else:
                await event.reply("编号超出范围~")
        else:
            await event.reply("请告诉我要删除的编号~ 比如「删除 #1」")

    async def _handle_list(self, event: MessageEvent, user_id: str):
        """处理查看日程"""
        items = self.schedule_store.get_user_items(user_id)
        if not items:
            await event.reply("暂无日程安排，输入「添加 14:30 开会」来添加~")
            return

        lines = ["📅 你的日程："]
        for i, item in enumerate(items, 1):
            time_str = item.remind_time.strftime("%m-%d %H:%M") if item.remind_time else "未定"
            lines.append(f"{i}. {item.content} @ {time_str}")
        await event.reply("\n".join(lines))

    async def _handle_skip(self, event: MessageEvent, user_id: str, text: str):
        """处理跳过提醒"""
        reminder_type = text.replace("跳过", "").strip()
        skip_map = {
            "喝水": "water_reminder",
            "洗澡": "bath_reminder",
            "睡觉": "sleep_reminder",
        }
        job_id = skip_map.get(reminder_type)
        if job_id:
            await self.schedule_store.skip_reminder(user_id, job_id)
            await event.reply(f"已跳过本次{reminder_type}提醒~")
        else:
            await event.reply("请告诉我跳过什么~ 如「跳过喝水」")

    async def _handle_modify_time(self, event: MessageEvent, user_id: str, text: str):
        """处理临时修改习惯时间"""
        # 格式：修改时间 喝水 10:30
        parts = text.replace("修改时间", "").strip().split(" ")
        if len(parts) >= 2:
            habit_name = parts[0]
            new_time = parts[1]
            success = await self.schedule_store.temp_override_habit(user_id, habit_name, new_time)
            if success:
                await event.reply(f"已临时修改{habit_name}时间为 {new_time}~（仅今日生效）")
            else:
                await event.reply("不支持的 habit 类型，支持：喝水/洗澡/睡觉")
        else:
            await event.reply("格式不对哦~ 如「修改时间 喝水 10:30」")

    async def _handle_help(self, event: MessageEvent):
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

    # ── 定时任务 ─────────────────────────────────────────────────────────

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
                logger.debug(f"{LOG_PREFIX} Apple 日历同步任务已注册（每 {sync_interval} 分钟）")
            
            # 日程 LLM 提醒定时扫描（每分钟一次，覆盖 80 分钟窗口）
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
        elapsed = now - today_start
        next_time = today_start + (elapsed // interval_min + 1) * interval_min
        if next_time > today_end:
            return today_start + timedelta(days=1)
        return next_time

    async def _send_to_user(self, user_id: str, message: str):
        """发送消息给用户"""
        platform = self._get_platform_id()
        try:
            sender = self.context.get_sender()
            await sender.send_to_user(user_id, message)
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 发送消息失败: {e}")

    async def _morning_briefing(self):
        """早安播报"""
        logger.debug(f"{LOG_PREFIX} 执行早安播报")

        # 构建播报内容
        parts = ["🌅 早安~", f"现在是 {datetime.now().strftime('%H:%M')}"]

        # 天气
        if hasattr(self, "weather_service"):
            try:
                weather = await self.weather_service.get_current()
                if weather:
                    parts.append(f"📍 {weather.get('location', '未知')}")
                    parts.append(f"🌡️ {weather.get('temperature', '--')}°C")
                    parts.append(f"💨 {weather.get('wind', '--')}")
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} 天气获取失败: {e}")

        # 日程概览
        if self.default_user_id:
            items = self.schedule_store.get_user_items(self.default_user_id)
            if items:
                upcoming = [f"{i.content}@{i.remind_time.strftime('%H:%M')}" for i in items[:3]]
                parts.append("📅 " + ", ".join(upcoming))

        # 喝水提醒
        parts.append("💧 别忘了喝水哦~")

        message = "\n".join(parts)
        if self.default_user_id:
            await self._send_to_user(self.default_user_id, message)

    async def _bath_reminder(self):
        """洗澡提醒"""
        logger.debug(f"{LOG_PREFIX} 执行洗澡提醒")
        if self.default_user_id:
            await self._send_to_user(self.default_user_id, "🛁 该洗澡啦~")

    async def _sleep_reminder(self):
        """睡觉提醒"""
        logger.debug(f"{LOG_PREFIX} 执行睡觉提醒")
        if self.default_user_id:
            await self._send_to_user(self.default_user_id, "😴 该睡觉啦，早点休息~")

    async def _water_reminder(self):
        """喝水提醒"""
        logger.debug(f"{LOG_PREFIX} 执行喝水提醒")

        # 计算下次触发
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

        if self.default_user_id:
            await self._send_to_user(self.default_user_id, f"💧 该喝水啦~ 下次提醒 {next_trigger.strftime('%H:%M')}")

    async def _schedule_scan(self):
        """定期扫描用户会话并同步到 Notion"""
        logger.debug(f"{LOG_PREFIX} 执行日程扫描")
        if await self._ensure_notion():
            try:
                # 扫描最近活跃用户
                active_users = self.schedule_store.get_active_users(minutes=60)
                for user_id in active_users:
                    messages = self.schedule_store.get_recent_conversations(user_id, limit=10)
                    if messages and self.notion:
                        # 简化的智能提取
                        await self._extract_and_sync(messages, user_id)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} 日程扫描失败: {e}")

    async def _extract_and_sync(self, messages: List[Dict], user_id: str):
        """从对话中提取日程并同步到 Notion"""
        # 简化实现：检查是否包含时间关键词
        for msg in messages:
            content = msg.get("content", "")
            if any(kw in content for kw in ["明天", "后天", "周五", "周六", "下周一"]):
                logger.debug(f"{LOG_PREFIX} 检测到潜在日程: {content}")

    async def _notion_ddl_check(self):
        """检查 Notion DDL 并发送提醒"""
        if await self._ensure_notion():
            try:
                ddls = await self.notion.get_upcoming_ddls(days=1)
                for ddl in ddls:
                    if self.default_user_id:
                        await self._send_to_user(
                            self.default_user_id,
                            f"⚠️ 明天到期：{ddl.get('title', '未知事项')}"
                        )
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} Notion DDL 检查失败: {e}")

    async def _schedule_reminder_scan(self):
        """日程 LLM 提醒扫描"""
        if not hasattr(self, "llm_service") or not self.llm_service:
            return

        # 获取 80 分钟内的待办
        now = datetime.now()
        window_end = now + timedelta(minutes=80)

        for user_id in self.schedule_store.get_all_users():
            items = self.schedule_store.get_user_items(user_id)
            for item in items:
                if item.remind_time and now <= item.remind_time <= window_end:
                    # 生成 LLM 提醒
                    try:
                        reminder_msg = await self._generate_reminder(item)
                        await self._send_to_user(user_id, reminder_msg)
                    except Exception as e:
                        logger.warning(f"{LOG_PREFIX} LLM 提醒生成失败: {e}")

    async def _generate_reminder(self, item: ScheduleItem) -> str:
        """使用 LLM 生成自然语言提醒"""
        if not self.llm_service:
            return f"📌 提醒：{item.content}"

        try:
            response = await self.llm_service.chat(
                prompt=f"用户有一个日程：「{item.content}」，提醒时间是 {item.remind_time.strftime('%H:%M')}。用一句话自然地提醒用户，控制在20字以内。"
            )
            return response.strip() if response else f"📌 提醒：{item.content}"
        except Exception:
            return f"📌 提醒：{item.content}"

    async def _apple_calendar_sync(self):
        """Apple 日历同步"""
        logger.debug(f"{LOG_PREFIX} 执行 Apple 日历同步")
        # 占位：需要 CalDAV 客户端实现

    async def _clear_expired_overrides(self):
        """清理过期的临时修改"""
        self.schedule_store.clear_expired_overrides()
        logger.debug(f"{LOG_PREFIX} 已清理过期临时修改")

    # ── 会话存储 ─────────────────────────────────────────────────────────

    @property
    def store(self) -> ScheduleStore:
        return self.schedule_store


async def __initialize(context) -> ScheduleAssistant:
    """插件初始化入口"""
    config = context.get_config().get("schedule_assistant", {})
    assistant = ScheduleAssistant(context, config)
    return assistant
