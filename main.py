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
from .constants import (
    LOG_PREFIX,
    DEFAULT_BATH_TIME,
    DEFAULT_SLEEP_TIME,
    DEFAULT_WATER_START,
    DEFAULT_WATER_END,
    DEFAULT_WATER_INTERVAL,
    MAX_WATER_INTERVAL_MINUTES,
    SCHEDULE_SCAN_WINDOW_MINUTES,
)
from .services import WeatherService, NotionService, LLMService
from .services.dashboard import DashboardService
from .reminders import BathReminder, SleepReminder, WaterReminder, BriefingReminder



# 模块级调度器单例，避免 AstrBot 重载时多实例并存
_shared_scheduler = None

class ScheduleAssistant(Star):
    """Main class for Schedule Assistant
    
    Provides schedule management, habit reminders, intelligent morning reports.
    Uses AstrBot Preference API for data persistence.
    """
    
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def _capture_conversation(self, event: AiocqhttpMessageEvent):
        """
        捕获对话消息并存入历史（用于提醒时的上下文注入）
        仅记录默认用户的消息和助手回复。
        """
        if not event.message_str or not event.message_str.strip():
            return
        user_id = event.get_sender_id()
        if user_id != self.default_user_id:
            return
        # 存入用户消息
        await self.store.add_conversation_message(user_id, "user", event.message_str.strip())

    @staticmethod
    def _get_water_next_trigger(now: datetime, water_start: str, water_end: str, interval: int) -> datetime:
        """Calculate the next water reminder trigger time

        Rules:
        1. If within water hours --> find next interval-minute cycle
        2. If before start time --> wait for start_time
        3. If after end time --> wait for tomorrow start_time
        """
        start_h, start_m = map(int, water_start.split(":"))
        end_h, end_m = map(int, water_end.split(":"))
        
        start_time = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end_time = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        
        # 情况3:已过结束时间 --> 明天开始
        if now > end_time:
            return start_time + timedelta(days=1)
        
        # 情况2:未到或正好到开始时间 --> 等开始
        if now <= start_time:
            return start_time

        # 情况1:在水时段内,找下一个interval分钟周期的整点
        current = start_time
        while current <= now:
            current += timedelta(minutes=interval)
        
        # 如果算出的时间超过了 end_time,说明今天没下次了,等明天
        if current > end_time:
            return start_time + timedelta(days=1)
        
        return current

    @staticmethod
    def _is_valid_hhmm(value: str) -> bool:
        """校验时间格式是否为 HH:MM。"""
        if not isinstance(value, str) or not re.match(r"^\d{1,2}:\d{2}$", value):
            return False
        try:
            h, m = map(int, value.split(":"))
            return 0 <= h <= 23 and 0 <= m <= 59
        except ValueError:
            return False

    @staticmethod
    def _parse_ymdhm(value: str) -> Optional[datetime]:
        """解析 YYYY-MM-DD HH:MM，失败返回 None。"""
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M")
        except ValueError:
            return None

    def _validate_and_normalize_config(self, raw_config: Optional[dict]) -> dict:
        """校验并标准化配置，避免单个错误配置导致任务注册失败。"""
        cfg = dict(raw_config or {})

        def _normalize_time(key: str, default: str):
            value = str(cfg.get(key, default) or default).strip()
            if not self._is_valid_hhmm(value):
                logger.warning(f"{LOG_PREFIX} 配置 {key} 非法（{value}），回退默认值 {default}")
                value = default
            cfg[key] = value

        _normalize_time("morning_report_time", "09:00")
        _normalize_time("bath_time", DEFAULT_BATH_TIME)
        _normalize_time("sleep_time", DEFAULT_SLEEP_TIME)
        _normalize_time("water_start_time", DEFAULT_WATER_START)
        _normalize_time("water_end_time", DEFAULT_WATER_END)

        try:
            water_interval = int(cfg.get("water_interval", DEFAULT_WATER_INTERVAL))
        except (ValueError, TypeError):
            water_interval = DEFAULT_WATER_INTERVAL
        if water_interval <= 0 or water_interval > MAX_WATER_INTERVAL_MINUTES:
            logger.warning(
                f"{LOG_PREFIX} 配置 water_interval 非法（{water_interval}），回退默认值 {DEFAULT_WATER_INTERVAL}"
            )
            water_interval = DEFAULT_WATER_INTERVAL
        cfg["water_interval"] = water_interval

        whitelist = cfg.get("whitelist_qq_ids", [])
        if not isinstance(whitelist, list):
            whitelist = []
        cfg["whitelist_qq_ids"] = [str(x).strip() for x in whitelist if str(x).strip()]
        return cfg

    def __init__(self, context: Context, config: dict = None):
        """Initialize ScheduleAssistant
        
        Args:
            context: AstrBot 上下文
            config: 插件配置字典(从 AstrBot 配置系统传入)
        """
        super().__init__(context)
        
        # 配置必须最先初始化，后续代码依赖 self.config
        self.config = self._validate_and_normalize_config(config)
        
        # 使用 AstrBot Storage API 替代本地 JSON
        self.store = ScheduleStore(context)
        
        # Notion 客户端（配置统一从 AstrBot 传入）
        self.notion = NotionClient(
            api_key=self.config.get("maton_api_key", ""),
            transaction_db_id=self.config.get("transaction_db_id", ""),
            reading_db_id=self.config.get("reading_db_id", "")
        )
        
        # Apple 日历客户端(可选)
        self.calendar = None
        if self.config.get("apple_calendar_enabled", False):
            self.calendar = AppleCalendar(
                username=self.config.get("apple_id"),
                app_password=self.config.get("apple_app_password"),
                webcal_urls=self.config.get("webcal_urls", [])
            )
        
        # 定时任务调度器
        # 复用模块级单例调度器（避免重载时多实例并存）
        global _shared_scheduler
        if _shared_scheduler is None:
            _shared_scheduler = AsyncIOScheduler()
        self.scheduler = _shared_scheduler
        
        # 防重入锁 - 防止任务重复触发
        self._water_reminder_running = False
        
        # 从配置读取用户设置
        whitelist = self.config.get("whitelist_qq_ids", [])
        self.default_user_id = str(
            self.config.get("default_user_id", "") or
            (whitelist[0] if whitelist else "")
        ).strip()
        self.default_username = ""  # 从QQ API获取，获取不到用「用户」
        
        # 初始化服务层
        self.weather_service = WeatherService(self.config)
        self.notion_service = NotionService(self.notion)
        self.dashboard_service = DashboardService()
        self.llm_service = LLMService(self.context)

        # 初始化提醒类
        self._reminder_bath = BathReminder(self.config, self.dashboard_service.func, self.llm_service, self.store)
        self._reminder_sleep = SleepReminder(self.config, self.dashboard_service.func, self.llm_service, self.store)
        self._reminder_water = WaterReminder(self.config, self.dashboard_service.func, self.llm_service, self.store)
        self._reminder_briefing = BriefingReminder(self.config, self.context, self.llm_service)

        # 在 __init__ 中直接注册定时任务
        self._register_jobs()
        
        logger.info(f"{LOG_PREFIX} 插件初始化完成,定时任务已注册")

    # Wrapper methods for scheduler job references (actual reminder logic is in reminder classes)
    async def _bath_reminder(self):
        await self._reminder_bath._trigger(self)

    async def _sleep_reminder(self):
        await self._reminder_sleep._trigger(self)

    async def _water_reminder(self):
        await self._reminder_water._trigger(self)

    def _register_jobs(self):
        """注册所有定时任务
        
        包括:早安播报,洗澡提醒,睡觉提醒,喝水提醒,Notion DDL检查
        """
        try:
            # 显式清空所有旧任务（防止 AstrBot 重载时残留）
            for job in list(self.scheduler.get_jobs()):
                try:
                    self.scheduler.remove_job(job.id)
                    logger.debug(f"{LOG_PREFIX} 清理旧任务: {{job.id}}")
                except Exception:
                    pass

            # Morning briefing at 9:00
            morning_report_time = self.config.get("morning_report_time", "09:00")
            morning_hour, morning_minute = map(int, morning_report_time.split(":"))
            self.scheduler.add_job(
                self._morning_briefing,
                CronTrigger(hour=morning_hour, minute=morning_minute),
                id="morning_briefing",
                replace_existing=True
            )
            
            # Bath reminder
            bath_time = self.config.get("bath_time", DEFAULT_BATH_TIME)
            bath_hour, bath_minute = map(int, bath_time.split(":"))
            self.scheduler.add_job(
                self._bath_reminder,
                CronTrigger(hour=bath_hour, minute=bath_minute),
                id="bath_reminder",
                replace_existing=True
            )
            
            # Sleep reminder
            sleep_time = self.config.get("sleep_time", DEFAULT_SLEEP_TIME)
            sleep_hour, sleep_minute = map(int, sleep_time.split(":"))
            self.scheduler.add_job(
                self._sleep_reminder,
                CronTrigger(hour=sleep_hour, minute=sleep_minute),
                id="sleep_reminder",
                replace_existing=True
            )
            
            # Water reminder - 智能计算首次触发时间
            water_start = self.config.get("water_start_time", DEFAULT_WATER_START)
            water_end = self.config.get("water_end_time", DEFAULT_WATER_END)
            water_interval = self.config.get("water_interval", DEFAULT_WATER_INTERVAL)
            
            # 使用辅助函数计算下次触发时间(支持重载时立即触发)
            now = datetime.now()
            next_trigger = self._get_water_next_trigger(now, water_start, water_end, water_interval)
            initial_delay = max((next_trigger - now).total_seconds(), 30.0)  # 至少等30秒，防止立即触发
            
            # 显式移除旧的喝水任务（replace_existing=True 对 date 触发器无效）
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
                CronTrigger(minute=0),  # 每小时整点
                id="notion_ddl_check",
                replace_existing=True
            )
            
            # 每天凌晨清理过期的临时修改(00:05执行,避开0点高峰)
            self.scheduler.add_job(
                self._clear_expired_overrides,
                CronTrigger(hour=0, minute=5),
                id="clear_expired_overrides",
                replace_existing=True
            )
            
            # 每小时扫描一次用户日程，到期触发私信提醒
            self.scheduler.add_job(
                self._schedule_scan,
                CronTrigger(minute=1),  # 每小时01分执行，避开整点高峰
                id="schedule_scan",
                replace_existing=True
            )
            
            # 立即启动 scheduler
            if not self.scheduler.running:
                self.scheduler.start()
            
            logger.info(f"{LOG_PREFIX} 所有定时任务已注册,调度器已启动")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 定时任务注册失败: {e}")

    async def on_load(self):
        """插件加载回调(AstrBot 生命周期)"""
        logger.info(f"{LOG_PREFIX} 插件加载完成")

    async def on_unload(self):
        """插件卸载/重启时清理资源
        
        停止调度器、关闭外部会话，避免连接泄漏。
        """
        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
                logger.info(f"{LOG_PREFIX} 调度器已停止")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 调度器停止失败: {e}")
        
        # 关闭 Notion 会话
        if self.notion:
            try:
                await self.notion.close()
                logger.info(f"{LOG_PREFIX} Notion 会话已关闭")
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} Notion 会话关闭失败: {e}")
        
        # 关闭日历会话（如果存在）
        if self.calendar:
            try:
                await self.calendar.close()
                logger.info(f"{LOG_PREFIX} 日历会话已关闭")
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} 日历会话关闭失败: {e}")

    # ==================== 定时任务回调 ====================
    
    async def _morning_briefing(self):
        """
        早安播报任务
        
        每天早上 9:00 自动推送综合日程简报，所有内容由LLM生成。
        """
        try:
            now = datetime.now()
            weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            user_id = self.default_user_id
            # 自动从白名单获取用户名
            if not self.default_username:
                username = await self._get_username_from_qq(user_id)
            else:
                username = self.default_username
            
            # ========== 并发获取所有数据 ==========
            weather_current, weather_forecast = await self.weather_service.fetch()
            calendar_info = await self._fetch_calendar_events()
            schedule_info = await self._fetch_local_schedules(user_id)
            notion_info = await self.notion_service.get_pending_str()
            late_night = await self._fetch_late_night_events()
            dashboard = await self.dashboard_service.func()

            # ========== LLM 生成完整播报 ==========
            full_report = await self._reminder_briefing.generate_full_report(
                username=username,
                date=now.strftime('%Y-%m-%d'),
                weekday=weekdays[now.weekday()],
                weather_current=weather_current,
                weather_forecast=weather_forecast,
                calendar=calendar_info,
                schedules=schedule_info,
                notion=notion_info,
                dashboard=dashboard,
                late_night=late_night or ""
            )
            
            await self._send_to_user(user_id, full_report)
            logger.info(f"{LOG_PREFIX} 早安播报已发送")
            
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 早安播报失败: {e}")


    async def _get_username_from_qq(self, user_id: str) -> str:
        """
        根据用户ID获取QQ昵称
        
        Args:
            user_id: QQ号
            
        Returns:
            用户昵称，获取失败则返回原ID
        """
        try:
            # 通过 platform_manager 获取用户信息
            for platform in self.context.platform_manager.platform_insts:
                try:
                    # 尝试获取陌生人信息
                    info = await platform.bot.call_action(
                        action="get_stranger_info",
                        user_id=int(user_id),
                        no_cache=True
                    )
                    if info and info.get("nickname"):
                        return info.get("nickname", user_id)
                    elif info and info.get("nick"):
                        return info.get("nick", user_id)
                except Exception:
                    pass
            return user_id
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 获取用户 {user_id} 昵称失败: {e}")
            return user_id

    # 天气缓存：30分钟内不重复请求
    _weather_cache: dict = {"data": ("", ""), "timestamp": 0}
    _CACHE_TTL = 1800  # 30分钟

    async def _fetch_calendar_events(self) -> str:
        """获取今日日历事件
        
        Returns:
            格式化的事件列表字符串（仅今日）
        """
        if not self.calendar:
            return "未启用日历同步"
        
        try:
            # 拉取2天（今天+明天），避免跨天日程被截断
            events = await self.calendar.get_all_events(days=2)
            
            # 过滤出今日的事件
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            today_events = [e for e in events if e.get("start", "")[:10] == today]
            
            if today_events:
                return "\n".join([
                    f"{e['start'][11:16] if len(e['start']) > 11 else ''} {e['summary']}"
                    for e in today_events[:5]
                ])
            return "暂无今日日程"
        except asyncio.TimeoutError:
            logger.warning(f"{LOG_PREFIX} 日历获取超时")
            return "日历获取超时"
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 日历获取失败: {e}")
            return "日历获取失败"

    async def _fetch_local_schedules(self, user_id: str) -> str:
        """获取本地所有日程
        
        Args:
            user_id: 用户ID
            
        Returns:
            格式化的日程列表字符串
        """
        try:
            items = await self.store.list_all_items(user_id)
            today_items = [i for i in items if i.type == "schedule"]
            if today_items:
                return "\n".join([f"{i.time} {i.title}" for i in today_items[:5]])
            return "暂无日程"
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 本地日程获取失败: {e}")
            return "获取失败"

    async def _fetch_late_night_events(self) -> str:
        """获取今日凌晨事件，判断是否熬夜
        
        Returns:
            凌晨事件描述，无则返回空字符串
        """
        if not self.calendar:
            return ""
        
        try:
            events = await self.calendar.get_late_night_events()
            if events:
                lines = [f"{e['start'][11:16]} {e['summary']}" for e in events]
                return "\n".join(lines)
            return ""
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 熬夜检测失败: {e}")
            return ""

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
        """添加日程或习惯
        
        Args:
            title (str): 日程/习惯的名称
            time (str): 执行时间,格式为 HH:MM,such as "09:00"
            recur (str, optional): 重复周期,可选值: daily, weekly（不支持 monthly）,空字符串表示不重复
            description (str, optional): 日程描述
        """
        user_id = str(event.sender_info.user_id)
        
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

    @filter.llm_tool(
        name="remove_schedule",
        description="删除指定的日程或习惯。支持模糊匹配。边界：匹配到第一项即删除并返回。"
    )
    async def remove_schedule_llm(
        self, 
        event: AiocqhttpMessageEvent, 
        title: str
    ) -> Generator[str, Any, None]:
        """删除日程或习惯
        
        Args:
            title (str): 要删除的日程/习惯名称(支持模糊匹配)
        """
        user_id = str(event.sender_info.user_id)
        items = await self.store.list_all_items(user_id)
        
        for item in items:
            if title.lower() in item.title.lower():
                if await self.store.remove_item(user_id, item.id):
                    yield event.plain_result(f"已删除: {item.title}")
                    return
        
        yield event.plain_result(f"未找到: {title}")

    @filter.llm_tool(
        name="list_schedules",
        description="查看当前用户的日程和习惯列表。边界：仅展示当前用户数据。"
    )
    async def list_schedules_llm(self, event: AiocqhttpMessageEvent) -> Generator[str, Any, None]:
        """查看所有日程和习惯列表
        """
        user_id = str(event.sender_info.user_id)
        items = await self.store.list_all_items(user_id)
        
        if not items:
            yield event.plain_result("暂无日程")
            return
        
        lines = ["📅 日程列表:"]
        for item in items:
            recur_text = ""
            if item.recur == "daily":
                recur_text = " 🔄 每天"
            elif item.recur == "weekly":
                recur_text = " 🔄 每周"
            lines.append(f"  • {item.title} @ {item.time}{recur_text}")
        
        yield event.plain_result("\n".join(lines))

    @filter.llm_tool(
        name="snooze_schedule",
        description="推迟指定日程或习惯提醒。参数：title-名称，minutes-分钟数。边界：snooze 生效后按新时间触发一次并自动清空。"
    )
    async def snooze_schedule_llm(
        self, 
        event: AiocqhttpMessageEvent, 
        title: str, 
        minutes: int
    ) -> Generator[str, Any, None]:
        """推迟日程提醒
        
        Args:
            title (str): 要推迟的日程名称
            minutes (int): 推迟的分钟数
        """
        user_id = str(event.sender_info.user_id)
        items = await self.store.list_all_items(user_id)
        
        for item in items:
            if title.lower() in item.title.lower():
                if await self.store.snooze_item(user_id, item.id, minutes):
                    yield event.plain_result(f"已将 {item.title} 推迟 {minutes} 分钟")
                    return
        
        yield event.plain_result(f"未找到: {title}")

    @filter.llm_tool(
        name="temp_override_habit",
        description="临时修改习惯提醒时间，仅当天生效。参数：habit_name-习惯名，new_time-HH:MM。边界：只影响习惯，不影响单次日程。"
    )
    async def temp_override_habit_llm(
        self, 
        event: AiocqhttpMessageEvent, 
        habit_name: str, 
        new_time: str
    ) -> Generator[str, Any, None]:
        """临时修改习惯的提醒时间(仅今天生效)
        
        Args:
            habit_name (str): 习惯名称
            new_time (str): 新的提醒时间,格式为 HH:MM
        """
        user_id = str(event.sender_info.user_id)
        
        if await self.store.set_temp_override(user_id, habit_name, new_time):
            yield event.plain_result(f"已临时修改 {habit_name} 为 {new_time}(今天生效)")
        else:
            yield event.plain_result(f"未找到: {habit_name}")

    @filter.llm_tool(
        name="get_notion_tasks",
        description="查看 Notion 中未完成待办任务。边界：依赖 Maton API Key 与数据库配置。"
    )
    async def get_notion_tasks_llm(self, event: AiocqhttpMessageEvent) -> Generator[str, Any, None]:
        """查看 Notion 中标记为 PENDING 的待办任务
        """
        try:
            pending = await self.notion.get_pending_transactions()
            if not pending:
                yield event.plain_result("📝 Notion 待办为空")
                return
            
            lines = ["📝 Notion 待办:"]
            for task in pending[:10]:
                ddl = task.get('ddl')
                ddl_str = f" | 截止 {ddl[:10]}" if ddl else ""
                lines.append(f"  • {task['title']}{ddl_str} [{task['status']}]")
            if len(pending) > 10:
                lines.append(f"  ...还有 {len(pending) - 10} 项")
            
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            yield event.plain_result(f"获取 Notion 任务失败: {str(e)}")

    @filter.llm_tool(
        name="skip_water",
        description="跳过本次喝水提醒并记录当前时间。边界：仅影响当前用户的喝水间隔计算。"
    )
    async def skip_water_llm(self, event: AiocqhttpMessageEvent) -> Generator[str, Any, None]:
        """跳过本次喝水提醒
        """
        user_id = str(event.sender_info.user_id)
        await self.store.set_water_last(user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        yield event.plain_result("好的,已Skip this water reminder~")


    async def _notion_ddl_check(self):
        """Notion DDL 检查任务
        
        每小时检查一次即将到期的 Notion 任务.
        """
        try:
            if not self.notion:
                return
            tasks = await self.notion.get_pending_transactions()
            now = datetime.now()
            
            for task in tasks:
                # 检查是否快到期(24小时内)
                due = task.get('ddl')
                if due:
                    try:
                        due_date = datetime.fromisoformat(due.replace('Z', '+00:00'))
                        due_date_local = due_date.astimezone().replace(tzinfo=None)
                        diff = (due_date_local - now).total_seconds()
                        if 0 < diff < 86400:  # 24小时内
                            title = task.get('title', '未命名任务')
                            ddl_time = due_date_local.strftime('%m-%d %H:%M')
                            logger.info(f"{LOG_PREFIX} DDL提醒: {title} 将在 {diff/3600:.1f} 小时后到期")
                            # 发送私信提醒
                            await self._send_to_user(
                                self.default_user_id,
                                f"📌 DDL提醒：{title} 截止于 {ddl_time}，还剩 {int(diff/3600)} 小时了~"
                            )
                    except Exception as e:
                        logger.debug(f"{LOG_PREFIX} 解析任务截止日期失败: {e}")
                        
        except Exception as e:
            logger.error(f"{LOG_PREFIX} DDL检查失败: {e}")


    async def _schedule_scan(self):
        """每小时扫描一次用户日程，到期触发私信提醒
        
        扫描今日所有单次日程和重复习惯，决定是否触发提醒。
        扫描窗口为最近65分钟, 确保非整点时间也能被稳定命中。
        """
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

                # 1) snooze 优先级最高：未到点则不触发，到了按 snooze 时间触发
                if item.snoozed_until:
                    snooze_dt = self._parse_ymdhm(item.snoozed_until)
                    if snooze_dt:
                        if snooze_dt > now:
                            continue
                        due_time = snooze_dt
                    else:
                        # 脏数据自动清理，回退正常时间判断
                        item.snoozed_until = None
                        item_changed = True

                # 2) 正常时间判定
                if due_time is None:
                    # 单次日程：优先解析完整时间 YYYY-MM-DD HH:MM
                    if item.type == "schedule":
                        try:
                            due_time = datetime.strptime(item.time, "%Y-%m-%d %H:%M")
                        except ValueError:
                            # 兼容旧数据/LLM 输入：仅 HH:MM 则按今天计算
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
                        # 习惯：优先使用当天 temp_override
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

                # 防重复触发：当前扫描窗口内只触发一次
                if item.last_triggered:
                    try:
                        last_dt = datetime.fromisoformat(item.last_triggered)
                        if last_dt >= window_start:
                            continue
                    except ValueError:
                        logger.warning(f"{LOG_PREFIX} last_triggered 格式非法，已清理: {item.title} ({item.last_triggered})")
                        item.last_triggered = None
                        item_changed = True
                
                # 触发提醒
                item.last_triggered = now.isoformat()
                item.snoozed_until = None  # snooze 到点后清空
                if item.type == "schedule":
                    # 单次任务触发后自动关闭，避免重复提醒
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


    async def _clear_expired_overrides(self):
        """每日清理过期的临时修改
        
        在凌晨00:05执行,清理所有习惯的过期temp_override.
        """
        try:
            user_id = self.default_user_id
            if user_id:
                await self.store.clear_expired_overrides(user_id)
                logger.info(f"{LOG_PREFIX} 已清理过期的临时修改")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 清理过期临时修改失败: {e}")


    async def _send_to_user(self, user_id: str, message: str):
        """发送私聊消息给用户
        
        Args:
            user_id: 用户ID
            message: 消息内容
        """
        try:
            # 检查白名单
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
            # 过滤表情标签（&&tag&&格式），避免标签被当作正文发送
            message = re.sub(r'&&[^&]+&&', '', message)
            chain = MessageChain().message(message)
            await self.context.send_message(session, chain)
            logger.info(f"{LOG_PREFIX} 消息已发送给用户 {user_id}")
            
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 发送消息失败: {e}")

    # ==================== LLM Tools ====================
    

async def __initialize(context: Context):
    """插件初始化入口
    
    Args:
        context: AstrBot 上下文
        
    Returns:
        ScheduleAssistant 实例
    """
    # 从配置获取
    config = context.get_config().get("schedule_assistant", {})
    assistant = ScheduleAssistant(context, config)
    return assistant
