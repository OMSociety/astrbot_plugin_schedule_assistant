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
from .reminders.briefing import BriefingReminder


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

        # 插件加载时自动初始化（参考 Minecraft 适配器写法）
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

        # Weather
        api_key = self.config.get("weather_api_key")
        city = self.config.get("weather_city", "杭州")
        if api_key:
            self.weather_service = WeatherService({"weather_api_key": api_key, "weather_city": city})

        # LLM
        maton_key = self.config.get("maton_api_key")
        if maton_key:
            try:
                self.llm_service = LLMService(maton_key)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} LLM 服务初始化失败: {e}")

        # Dashboard
        self.dashboard_service = DashboardService()

        # Notion（支持多数据库配置）
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
        self.briefing_reminder = BriefingReminder(self.llm_service, self.weather_service, self.dashboard_service)
        self.bath_reminder = BathReminder(self.llm_service, self.dashboard_service)
        self.sleep_reminder = SleepReminder(self.llm_service, self.dashboard_service)
        self.water_reminder = WaterReminder(self.llm_service, self.dashboard_service)
        self.schedule_reminder = ScheduleReminder(self.llm_service, self.dashboard_service)
