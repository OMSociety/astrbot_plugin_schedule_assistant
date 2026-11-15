"""早安播报的数据组装。"""

from __future__ import annotations

from datetime import datetime, timedelta

from astrbot.api import logger

from . import notices
from .schedule_store import ScheduleItem
from .settings import Settings


class MorningBriefing:
    def __init__(self, store, weather, notion, apple_calendar, settings: Settings):
        self.store = store
        self.weather = weather
        self.notion = notion
        self.apple = apple_calendar
        self.settings = settings

    async def build(self, umo: str, now: datetime | None = None) -> str:
        now = now or datetime.now(self.settings.timezone)
        horizon = now + timedelta(hours=24)
        entries: dict[tuple[str, str], datetime] = {}

        for item in await self.store.list_items(umo):
            start = _item_start(item, self.settings.timezone)
            if start is None or not _in_window(start, item.all_day, now, horizon):
                continue
            entries[(notices.time_label(item), item.title)] = start

        if self.apple is not None:
            try:
                events, _ = await self.apple.get_all_events(days=2)
            except Exception as exc:
                logger.warning(f"早安播报读取 Apple 日历失败: {exc}")
                events = []
            for event in events:
                entry = _apple_entry(event, self.settings.timezone)
                if entry is None:
                    continue
                label, start, all_day = entry
                if not _in_window(start, all_day, now, horizon):
                    continue
                entries.setdefault(
                    (label, str(event.get("summary") or "无标题")), start
                )

        ordered = sorted(entries.items(), key=lambda pair: pair[1])
        agenda = notices.format_agenda(
            [(label, title) for (label, title), _start in ordered]
        )

        weather_current = ""
        weather_forecast = ""
        if self.weather is not None:
            weather_current, weather_forecast = await self.weather.fetch()

        notion_text: str | None = None
        if self.notion is not None:
            tasks = await self.notion.get_pending_transactions()
            if tasks is None:
                notion_text = "获取失败"
            else:
                lines = []
                for task in tasks[:5]:
                    ddl = notices.format_ddl(
                        str(task.get("ddl") or ""), self.settings.timezone
                    )
                    lines.append(
                        f"- {ddl or '无截止'} | {task.get('title') or '(无标题)'}"
                    )
                notion_text = "\n".join(lines) or "暂无"

        return notices.morning(
            date_label=f"{now:%Y-%m-%d}",
            weekday=notices.weekday_label(now.date()),
            weather_current=weather_current,
            weather_forecast=weather_forecast,
            agenda=agenda,
            notion_todos=notion_text,
            custom=self.settings.prompt_morning,
        )


def _item_start(item: ScheduleItem, tz) -> datetime | None:
    try:
        parsed = notices.parse_item_time(item.time)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _in_window(
    start: datetime, all_day: bool, now: datetime, horizon: datetime
) -> bool:
    if all_day:
        return start.date() == now.date()
    return now - timedelta(minutes=1) <= start < horizon


def _apple_entry(event: dict, tz) -> tuple[str, datetime, bool] | None:
    start_str = str(event.get("start") or "")
    try:
        start = datetime.fromisoformat(start_str)
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    else:
        start = start.astimezone(tz)
    all_day = bool(event.get("all_day"))
    if all_day:
        return "全天", start, True
    label = f"{start:%H:%M}"
    end_str = str(event.get("end") or "")
    if end_str:
        try:
            end = datetime.fromisoformat(end_str)
            if end.tzinfo is None:
                end = end.replace(tzinfo=tz)
            else:
                end = end.astimezone(tz)
            label = f"{label}-{end:%H:%M}"
        except ValueError:
            pass
    return label, start, False
