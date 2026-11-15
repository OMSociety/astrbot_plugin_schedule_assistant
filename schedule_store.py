"""本地日程存储。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, tzinfo
from typing import Any
from uuid import uuid4

from astrbot.api import logger

LOG_PREFIX = "[ScheduleAssistant]"


@dataclass
class ScheduleItem:
    id: str = field(default_factory=lambda: uuid4().hex[:8])
    title: str = ""
    time: str = ""
    end_time: str | None = None
    context: str = ""
    apple_uid: str | None = None
    all_day: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(
        cls,
        *,
        title: str,
        time: str,
        end_time: str | None = None,
        context: str = "",
        apple_uid: str | None = None,
        all_day: bool = False,
    ) -> "ScheduleItem":
        return cls(
            title=title,
            time=time,
            end_time=end_time,
            context=context,
            apple_uid=apple_uid,
            all_day=all_day,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduleItem":
        return cls(
            id=str(data.get("id") or uuid4().hex[:8]),
            title=str(data.get("title") or ""),
            time=str(data.get("time") or ""),
            end_time=data.get("end_time") or None,
            context=str(data.get("context") or ""),
            apple_uid=data.get("apple_uid") or None,
            all_day=bool(data.get("all_day", False)),
        )


class ScheduleStore:
    CACHE_TTL = 30.0

    def __init__(self, plugin):
        self.plugin = plugin
        self._log = getattr(plugin, "logger", logger)
        self._cache: dict[str, tuple[float, list[ScheduleItem]]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _schedules_key(umo: str) -> str:
        return f"schedules_{umo}"

    async def _load(self, umo: str) -> list[ScheduleItem]:
        cached = self._cache.get(umo)
        if cached and time.monotonic() - cached[0] < self.CACHE_TTL:
            return list(cached[1])
        raw = await self._read_kv(self._schedules_key(umo), [])
        items = [
            ScheduleItem.from_dict(entry) for entry in raw if isinstance(entry, dict)
        ]
        self._cache[umo] = (time.monotonic(), items)
        return list(items)

    async def _save(self, umo: str, items: list[ScheduleItem]) -> None:
        await self.plugin.put_kv_data(
            self._schedules_key(umo), [item.to_dict() for item in items]
        )
        self._cache[umo] = (time.monotonic(), list(items))

    async def _read_kv(self, key: str, default):
        try:
            return await self.plugin.get_kv_data(key, default)
        except Exception as exc:
            self._log.warning(f"{LOG_PREFIX} 读取本地数据失败 key={key}: {exc}")
            return default

    async def list_items(self, umo: str) -> list[ScheduleItem]:
        return await self._load(umo)

    async def get_item(self, umo: str, item_id: str) -> ScheduleItem | None:
        for item in await self._load(umo):
            if item.id == item_id:
                return item
        return None

    async def add_item(self, umo: str, item: ScheduleItem) -> None:
        async with self._lock:
            items = await self._load(umo)
            if any(existing.id == item.id for existing in items):
                item = ScheduleItem.from_dict({**item.to_dict(), "id": uuid4().hex[:8]})
            items.append(item)
            await self._save(umo, items)

    async def update_item(self, umo: str, item: ScheduleItem) -> bool:
        async with self._lock:
            items = await self._load(umo)
            for index, existing in enumerate(items):
                if existing.id == item.id:
                    items[index] = item
                    await self._save(umo, items)
                    return True
        return False

    async def remove_item(self, umo: str, item_id: str) -> bool:
        async with self._lock:
            items = await self._load(umo)
            remaining = [item for item in items if item.id != item_id]
            if len(remaining) == len(items):
                return False
            await self._save(umo, remaining)
            return True

    async def sync_from_apple_calendar(
        self,
        umo: str,
        apple_events: list[dict],
        *,
        allow_delete: bool,
        now: datetime | None = None,
    ) -> dict[str, int]:
        """把 Apple 日历事件并入本地日程。

        ``allow_delete`` 只在调用方确认本轮读取完整时传 True；读取不完整时，
        缺席的 UID 与「事件已被删除」无法区分，此时只做新增与更新。
        """
        stats = {"added": 0, "updated": 0, "deleted": 0}
        if not apple_events:
            return stats

        current = now or datetime.now().astimezone()
        tz = current.tzinfo
        lower = current - timedelta(days=1)
        future_cutoff = current + timedelta(days=7)

        async with self._lock:
            items = await self._load(umo)
            by_uid = {item.apple_uid: item for item in items if item.apple_uid}
            apple_uids: set[str] = set()
            processed_uids: set[str] = set()

            for event in apple_events:
                uid = event.get("uid")
                if not uid or uid in processed_uids:
                    continue
                processed_uids.add(uid)
                start_str = event.get("start") or ""
                if not start_str:
                    continue
                start_dt = self._parse_event_time(start_str, tz)
                if start_dt is None:
                    continue
                if start_dt < lower or start_dt > future_cutoff:
                    continue
                apple_uids.add(uid)

                wall = start_dt.astimezone(tz) if (tz and start_dt.tzinfo) else start_dt
                all_day = bool(event.get("all_day", False))
                schedule_time = (
                    wall.strftime("%Y-%m-%d")
                    if all_day
                    else wall.strftime("%Y-%m-%d %H:%M")
                )
                end_str = None
                end_raw = event.get("end") or ""
                if end_raw and not all_day:
                    end_dt = self._parse_event_time(end_raw, tz)
                    if end_dt is None:
                        end_str = str(end_raw)
                    else:
                        end_wall = (
                            end_dt.astimezone(tz) if (tz and end_dt.tzinfo) else end_dt
                        )
                        end_str = end_wall.strftime("%Y-%m-%d %H:%M")
                title = event.get("summary", "无标题")
                context = event.get("description", "")

                local = by_uid.get(uid)
                if local is None:
                    new_item = ScheduleItem(
                        id=uuid4().hex[:8],
                        title=title,
                        time=schedule_time,
                        end_time=end_str,
                        context=context,
                        apple_uid=uid,
                        all_day=all_day,
                    )
                    items.append(new_item)
                    by_uid[uid] = new_item
                    stats["added"] += 1
                    continue

                if (
                    local.title != title
                    or local.time != schedule_time
                    or local.end_time != end_str
                    or local.context != context
                    or local.all_day != all_day
                ):
                    local.title = title
                    local.time = schedule_time
                    local.end_time = end_str
                    local.context = context
                    local.all_day = all_day
                    stats["updated"] += 1

            if allow_delete:
                before = len(items)
                items = [
                    item
                    for item in items
                    if not item.apple_uid or item.apple_uid in apple_uids
                ]
                stats["deleted"] = before - len(items)
            else:
                self._log.debug(f"{LOG_PREFIX} 未获删除授权，本轮保留本地日程")

            if stats["added"] or stats["updated"] or stats["deleted"]:
                await self._save(umo, items)
        return stats

    @staticmethod
    def _parse_event_time(value: str, tz: tzinfo | None) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=tz) if tz else parsed
        return parsed.astimezone(tz) if tz else parsed
