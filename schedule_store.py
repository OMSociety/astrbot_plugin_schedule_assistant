"""日程数据存储模块

提供日程和习惯的数据持久化，基于 AstrBot 的 preference 存储系统。
支持单次日程、定期习惯、喝水记录、临时覆盖等数据管理。
"""
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, TYPE_CHECKING

from astrbot import logger

from .constants import PREFERENCE_SCOPE, SCHEDULES_KEY, HABITS_KEY, WATER_LAST_KEY, LOG_PREFIX

if TYPE_CHECKING:
    from astrbot.api.star import Context

__all__ = ['ScheduleItem', 'ScheduleStore']


@dataclass
class ScheduleItem:
    """日程/习惯数据项"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: str = ""
    title: str = ""
    time: str = ""
    recur: Optional[str] = None
    context: str = ""
    enabled: bool = True
    snoozed_until: Optional[str] = None
    last_triggered: Optional[str] = None
    temp_override: Optional[str] = None
    apple_uid: Optional[str] = None

    def to_dict(self) -> dict:
        """序列化为字典"""
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "ScheduleItem":
        """从字典反序列化，过滤未知字段"""
        valid_fields = {'id', 'type', 'title', 'time', 'recur', 'context', 'enabled', 'snoozed_until', 'last_triggered', 'temp_override', 'apple_uid'}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        if not filtered.get("id"):
            filtered["id"] = str(uuid.uuid4())[:8]
        return ScheduleItem(**filtered)


class ScheduleStore:
    """日程数据存储器"""
    def __init__(self, context: "Context"):
        self.context = context
        logger.info(f"{LOG_PREFIX} ScheduleStore 初始化完成")

    def _get_db(self):
        return self.context.get_db()

    async def _get_user_index(self) -> List[str]:
        try:
            pref = await self._get_db().get_preference(PREFERENCE_SCOPE, "_meta_", "users")
            users = pref.value if pref and pref.value else []
            return [str(u) for u in users if u]
        except Exception:
            return []

    async def _save_user_index(self, users: List[str]) -> None:
        try:
            uniq = sorted({str(u) for u in users if u})
            await self._get_db().insert_preference_or_update(scope=PREFERENCE_SCOPE, scope_id="_meta_", key="users", value=uniq)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 保存用户索引失败: {e}")

    async def _touch_user(self, user_id: str) -> None:
        if not user_id:
            return
        users = await self._get_user_index()
        if user_id not in users:
            users.append(user_id)
            await self._save_user_index(users)

    async def _get_user_data(self, user_id: str) -> Dict[str, Any]:
        try:
            pref = await self._get_db().get_preference(PREFERENCE_SCOPE, user_id, "data")
            if pref and pref.value:
                return pref.value
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 读取用户 {user_id} 数据失败: {e}")
        return {SCHEDULES_KEY: [], HABITS_KEY: [], WATER_LAST_KEY: ""}

    async def _save_user_data(self, user_id: str, data: Dict[str, Any]) -> None:
        try:
            await self._get_db().insert_preference_or_update(scope=PREFERENCE_SCOPE, scope_id=user_id, key="data", value=data)
            await self._touch_user(user_id)
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 保存用户 {user_id} 数据失败: {e}")

    async def add_item(self, user_id: str, item: ScheduleItem) -> None:
        data = await self._get_user_data(user_id)
        item_dict = item.to_dict()
        if item.type == "habit":
            data[HABITS_KEY] = [h for h in data[HABITS_KEY] if h.get("title") != item.title]
            data[HABITS_KEY].append(item_dict)
        else:
            data[SCHEDULES_KEY].append(item_dict)
        await self._save_user_data(user_id, data)

    async def list_all_items(self, user_id: str) -> List[ScheduleItem]:
        data = await self._get_user_data(user_id)
        items = []
        for s in data.get(SCHEDULES_KEY, []):
            items.append(ScheduleItem.from_dict(s))
        for h in data.get(HABITS_KEY, []):
            items.append(ScheduleItem.from_dict(h))
        return items

    async def get_schedules(self, user_id: str) -> Dict[str, List[ScheduleItem]]:
        data = await self._get_user_data(user_id)
        return {
            SCHEDULES_KEY: [ScheduleItem.from_dict(s) for s in data.get(SCHEDULES_KEY, [])],
            HABITS_KEY: [ScheduleItem.from_dict(h) for h in data.get(HABITS_KEY, [])],
        }

    async def get_all_users(self) -> List[str]:
        return sorted(set(await self._get_user_index()))

    async def remove_item(self, user_id: str, item_id: str) -> bool:
        data = await self._get_user_data(user_id)
        before = len(data.get(SCHEDULES_KEY, [])) + len(data.get(HABITS_KEY, []))
        data[SCHEDULES_KEY] = [s for s in data.get(SCHEDULES_KEY, []) if s.get("id") != item_id]
        data[HABITS_KEY] = [h for h in data.get(HABITS_KEY, []) if h.get("id") != item_id]
        after = len(data.get(SCHEDULES_KEY, [])) + len(data.get(HABITS_KEY, []))
        if before != after:
            await self._save_user_data(user_id, data)
            return True
        return False

    async def update_item(self, user_id: str, item: "ScheduleItem") -> bool:
        data = await self._get_user_data(user_id)
        item_dict = item.to_dict()
        for key in [SCHEDULES_KEY, HABITS_KEY]:
            for i, stored in enumerate(data.get(key, [])):
                if stored.get("id") == item.id:
                    data[key][i] = item_dict
                    await self._save_user_data(user_id, data)
                    return True
        return False

    async def snooze_item(self, user_id: str, item_id: str, minutes: int) -> bool:
        new_time = (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
        data = await self._get_user_data(user_id)
        found = False
        for key in [SCHEDULES_KEY, HABITS_KEY]:
            for item in data.get(key, []):
                if item.get("id") == item_id:
                    item["snoozed_until"] = new_time
                    found = True
        if found:
            await self._save_user_data(user_id, data)
        return found

    async def enable_item(self, user_id: str, item_id: str, enabled: bool) -> bool:
        data = await self._get_user_data(user_id)
        found = False
        for key in [SCHEDULES_KEY, HABITS_KEY]:
            for item in data.get(key, []):
                if item.get("id") == item_id:
                    item["enabled"] = enabled
                    found = True
        if found:
            await self._save_user_data(user_id, data)
        return found

    async def get_water_last(self, user_id: str) -> str:
        data = await self._get_user_data(user_id)
        return data.get(WATER_LAST_KEY, "")

    async def set_water_last(self, user_id: str, ts: str) -> None:
        data = await self._get_user_data(user_id)
        data[WATER_LAST_KEY] = ts
        await self._save_user_data(user_id, data)

    async def set_temp_override(self, user_id: str, habit_title: str, new_time: str) -> bool:
        data = await self._get_user_data(user_id)
        today = datetime.now().strftime("%Y-%m-%d")
        found = False
        for habit in data.get(HABITS_KEY, []):
            if habit.get("title") == habit_title:
                habit["temp_override"] = f"{today} {new_time}"
                found = True
        if found:
            await self._save_user_data(user_id, data)
        return found

    async def get_effective_time(self, user_id: str, habit_title: str, default_time: str) -> str:
        data = await self._get_user_data(user_id)
        today = datetime.now().strftime("%Y-%m-%d")
        for habit in data.get(HABITS_KEY, []):
            if habit.get("title") == habit_title:
                temp = habit.get("temp_override", "")
                if temp and temp.startswith(today):
                    return temp.split(" ")[1] if " " in temp else default_time
        return default_time

    async def sync_from_apple_calendar(self, user_id: str, apple_events: List[Dict]) -> Dict[str, int]:
        data = await self._get_user_data(user_id)
        schedules = data.get(SCHEDULES_KEY, [])
        uid_map = {s["apple_uid"]: s for s in schedules if s.get("apple_uid")}
        apple_uids = set()
        stats = {"added": 0, "updated": 0, "deleted": 0}
        for evt in apple_events:
            uid = evt.get("uid")
            if not uid:
                continue
            apple_uids.add(uid)
            start_str = evt.get("start", "")
            if not start_str:
                continue
            try:
                start_dt = datetime.fromisoformat(start_str)
                schedule_time = start_dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                schedule_time = start_str
            if uid in uid_map:
                local = uid_map[uid]
                if local.get("title") != evt.get("summary") or local.get("time") != schedule_time:
                    local["title"] = evt.get("summary", "无标题")
                    local["time"] = schedule_time
                    stats["updated"] += 1
            else:
                schedules.append({"id": str(uuid.uuid4())[:8], "type": "schedule", "title": evt.get("summary", "无标题"), "time": schedule_time, "recur": None, "context": evt.get("description", ""), "enabled": True, "snoozed_until": None, "last_triggered": None, "temp_override": None, "apple_uid": uid})
                stats["added"] += 1
        before_count = len(schedules)
        schedules = [s for s in schedules if not s.get("apple_uid") or s["apple_uid"] in apple_uids]
        stats["deleted"] = before_count - len(schedules)
        data[SCHEDULES_KEY] = schedules
        await self._save_user_data(user_id, data)
        return stats
