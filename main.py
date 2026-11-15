"""日程助手插件：生命周期与依赖组装。"""

from __future__ import annotations

import contextlib
from typing import Any

from astrbot.api.star import Context, Star

from .apple_calendar import AppleCalendar
from .briefing import MorningBriefing
from .calendar_sync import CalendarSync
from .notion_client import NotionClient
from .schedule_store import ScheduleStore
from .scheduling import Scheduling
from .settings import load_settings
from .tools.schedule_tools import register_schedule_tools
from .weather import WeatherService


class ScheduleAssistant(Star):
    def __init__(self, context: Context, config: dict[str, Any] | None = None):
        super().__init__(context, config)
        self.config = config or {}
        self.settings = load_settings(self.config)
        self.store = ScheduleStore(self)
        self.weather: WeatherService | None = None
        self.notion: NotionClient | None = None
        self.apple: AppleCalendar | None = None
        self.briefing: MorningBriefing | None = None
        self.scheduling: Scheduling | None = None

    async def initialize(self) -> None:
        self.settings = load_settings(self.config, self.context.get_config())
        self.weather = WeatherService(
            self.settings.weather_api_key, self.settings.weather_city
        )
        self.notion = self._build_notion()
        self.apple = self._build_apple()
        self.briefing = MorningBriefing(
            self.store, self.weather, self.notion, self.apple, self.settings
        )
        calendar_sync = (
            CalendarSync(self.apple, self.store, self.settings)
            if self.apple is not None
            else None
        )
        self.scheduling = Scheduling(
            self, self.store, self.settings, self.briefing, calendar_sync
        )
        register_schedule_tools(self)
        await self.scheduling.start()

    async def terminate(self) -> None:
        if self.scheduling is not None:
            await self.scheduling.stop()
            self.scheduling = None
        if self.notion is not None:
            with contextlib.suppress(Exception):
                await self.notion.close()
            self.notion = None
        if self.apple is not None:
            with contextlib.suppress(Exception):
                await self.apple.close()
            self.apple = None

    # ---------------------------------------------------------------- 依赖构造

    def _build_notion(self) -> NotionClient | None:
        if not self.settings.maton_api_key or not self.settings.notion_db_ids:
            return None
        transaction, reading = self._parse_notion_dbs(self.settings.notion_db_ids)
        if not transaction and not reading:
            return None
        return NotionClient(
            self.settings.maton_api_key,
            transaction,
            reading,
            timezone=self.settings.timezone,
        )

    @staticmethod
    def _parse_notion_dbs(entries: tuple[str, ...]) -> tuple[str, str]:
        transaction = ""
        reading = ""
        unnamed: list[str] = []
        for entry in entries:
            text = str(entry).strip().replace("：", ":")
            if not text:
                continue
            if ":" in text:
                label, _, db_id = text.partition(":")
                label = label.strip()
                db_id = db_id.strip()
                if label in {"事务", "transaction"}:
                    transaction = db_id
                elif label in {"阅读", "reading"}:
                    reading = db_id
                else:
                    unnamed.append(text)
            else:
                unnamed.append(text)
        for db_id in unnamed:
            if not transaction:
                transaction = db_id
            elif not reading:
                reading = db_id
        return transaction, reading

    def _build_apple(self) -> AppleCalendar | None:
        if not self.settings.enable_apple_calendar_sync:
            return None
        has_account = bool(
            self.settings.apple_username and self.settings.apple_app_password
        )
        if not has_account and not self.settings.webcal_urls:
            self.logger.warning(
                "Apple 日历同步已开启，但既没有账号凭据也没有 webcal 地址，已跳过"
            )
            return None
        return AppleCalendar(
            username=self.settings.apple_username or None,
            app_password=self.settings.apple_app_password or None,
            webcal_urls=list(self.settings.webcal_urls) or None,
            calendar_id=self.settings.apple_calendar_id or None,
            caldav_host=self.settings.apple_caldav_host or None,
            timezone=self.settings.timezone,
        )
