"""
ScheduleStore - 基于 AstrBot Preference API 的日程数据持久化模块

使用 AstrBot 的 Preference 系统存储用户日程数据，替代原有的本地 JSON 文件方案。

主要改进：
- 使用 context.get_db().get_preference() 读取数据
- 使用 context.get_db().insert_preference_or_update() 保存数据
- 支持多用户数据隔离
- 自动处理并发安全（由 AstrBot 数据库层保证）
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
    """单个日程/习惯的数据模型
    
    Attributes:
        id: 唯一标识符（自动生成 8 位短 UUID）
        type: 类型 ("schedule" 单次日程 | "habit" 重复习惯)
        title: 标题/名称
        time: 时间 (HH:MM 格式用于习惯, YYYY-MM-DD HH:MM 用于单次日程)
        recur: 重复周期 ("daily" | "weekly" | None)
        context: 用户原始描述
        enabled: 是否启用
        snoozed_until: 推迟到的 ISO 时间 (YYYY-MM-DD HH:MM)
        last_triggered: 上次触发时间 (ISO 时间)
        temp_override: 临时修改时间 (格式: YYYY-MM-DD HH:MM，仅今天有效)
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: str = ""  # "schedule" | "habit"
    title: str = ""
    time: str = ""  # "HH:MM" for habits, "YYYY-MM-DD HH:MM" for one-time
    recur: Optional[str] = None  # "daily" | "weekly" | None
    context: str = ""  # original user description
    enabled: bool = True
    snoozed_until: Optional[str] = None  # ISO datetime
    last_triggered: Optional[str] = None
    temp_override: Optional[str] = None  # 临时修改时间，今日有效

    def to_dict(self) -> dict:
        """序列化为字典，用于存储到数据库"""
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "ScheduleItem":
        """从字典反序列化，自动处理缺失的 id 字段"""
        # 确保 id 存在（兼容旧数据）
        if not data.get("id"):
            data["id"] = str(uuid.uuid4())[:8]
        return ScheduleItem(**data)


class ScheduleStore:
    """基于 AstrBot Preference API 的日程数据管理器
    
    每个用户的数据结构存储在 preference 中:
    scope: "schedule_assistant"
    scope_id: user_id
    key: "data"
    value: {
        "schedules": [...],  # 单次日程列表 (ScheduleItem dicts)
        "habits": [...],     # 重复习惯列表 (ScheduleItem dicts)
        "water_last": "..."  # 上次喝水时间 ISO 字符串
    }
    """

    def __init__(self, context: "Context"):
        """初始化 ScheduleStore
        
        Args:
            context: AstrBot Context，用于访问数据库 Preference API
        """
        self.context = context
        logger.info(f"{LOG_PREFIX} ScheduleStore 初始化完成，使用 AstrBot Preference API")

    def _get_db(self):
        """获取数据库实例"""
        return self.context.get_db()

    async def _get_user_data(self, user_id: str) -> Dict[str, Any]:
        """异步获取用户数据
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户日程数据字典，如果不存在返回默认空结构
        """
        try:
            pref = await self._get_db().get_preference(PREFERENCE_SCOPE, user_id, "data")
            if pref and pref.value:
                return pref.value
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 读取用户 {user_id} 数据失败: {e}")
        
        # 返回默认空结构
        return {SCHEDULES_KEY: [], HABITS_KEY: [], WATER_LAST_KEY: ""}

    async def _save_user_data(self, user_id: str, data: Dict[str, Any]) -> None:
        """保存用户数据到 Preference
        
        Args:
            user_id: 用户ID
            data: 要保存的数据字典
        """
        try:
            await self._get_db().insert_preference_or_update(
                scope=PREFERENCE_SCOPE,
                scope_id=user_id,
                key="data",
                value=data
            )
            logger.debug(f"{LOG_PREFIX} 用户 {user_id} 数据已保存")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 保存用户 {user_id} 数据失败: {e}")

    async def add_item(self, user_id: str, item: ScheduleItem) -> None:
        """添加日程或习惯
        
        习惯会去重（同标题只保留一个）
        
        Args:
            user_id: 用户ID
            item: 要添加的日程项（注意：id 自动生成，无需传入）
        """
        data = await self._get_user_data(user_id)
        item_dict = item.to_dict()
        
        if item.type == "habit":
            # 习惯去重：同标题只保留一个
            data[HABITS_KEY] = [h for h in data[HABITS_KEY] 
                                if h.get("title") != item.title]
            data[HABITS_KEY].append(item_dict)
            logger.info(f"{LOG_PREFIX} 用户 {user_id} 添加习惯: {item.title}")
        else:
            data[SCHEDULES_KEY].append(item_dict)
            logger.info(f"{LOG_PREFIX} 用户 {user_id} 添加日程: {item.title}")
        
        await self._save_user_data(user_id, data)

    async def list_all_items(self, user_id: str) -> List[ScheduleItem]:
        """列出用户所有日程项（含日程和习惯）
        
        Args:
            user_id: 用户ID
            
        Returns:
            ScheduleItem 对象列表
        """
        data = await self._get_user_data(user_id)
        items = []
        
        for s in data.get(SCHEDULES_KEY, []):
            items.append(ScheduleItem.from_dict(s))
        
        for h in data.get(HABITS_KEY, []):
            items.append(ScheduleItem.from_dict(h))
        
        return items

    async def get_schedules(self, user_id: str) -> Dict[str, List[ScheduleItem]]:
        """获取用户的日程和习惯分开列表
        
        Args:
            user_id: 用户ID
            
        Returns:
            {"schedules": [...], "habits": [...]}
        """
        data = await self._get_user_data(user_id)
        return {
            SCHEDULES_KEY: [ScheduleItem.from_dict(s) for s in data.get(SCHEDULES_KEY, [])],
            HABITS_KEY: [ScheduleItem.from_dict(h) for h in data.get(HABITS_KEY, [])],
        }

    async def remove_item(self, user_id: str, item_id: str) -> bool:
        """根据ID删除日程项
        
        Args:
            user_id: 用户ID
            item_id: 要删除的项ID
            
        Returns:
            是否成功删除
        """
        data = await self._get_user_data(user_id)
        
        before_count = len(data.get(SCHEDULES_KEY, [])) + len(data.get(HABITS_KEY, []))
        
        data[SCHEDULES_KEY] = [s for s in data.get(SCHEDULES_KEY, []) 
                               if s.get("id") != item_id]
        data[HABITS_KEY] = [h for h in data.get(HABITS_KEY, []) 
                            if h.get("id") != item_id]
        
        after_count = len(data.get(SCHEDULES_KEY, [])) + len(data.get(HABITS_KEY, []))
        
        if before_count != after_count:
            await self._save_user_data(user_id, data)
            logger.info(f"{LOG_PREFIX} 用户 {user_id} 删除项: {item_id}")
            return True
        
        return False

    async def snooze_item(self, user_id: str, item_id: str, minutes: int) -> bool:
        """推迟日程项指定分钟数
        
        Args:
            user_id: 用户ID
            item_id: 要推迟的项ID
            minutes: 推迟分钟数
            
        Returns:
            是否成功推迟
        """
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
            logger.info(f"{LOG_PREFIX} 用户 {user_id} 推迟项 {item_id} 到 {new_time}")
            return True
        
        return False

    async def enable_item(self, user_id: str, item_id: str, enabled: bool) -> bool:
        """启用/禁用日程项
        
        Args:
            user_id: 用户ID
            item_id: 要操作的项ID
            enabled: 是否启用
            
        Returns:
            是否成功操作
        """
        data = await self._get_user_data(user_id)
        
        found = False
        for key in [SCHEDULES_KEY, HABITS_KEY]:
            for item in data.get(key, []):
                if item.get("id") == item_id:
                    item["enabled"] = enabled
                    found = True
        
        if found:
            await self._save_user_data(user_id, data)
            return True
        
        return False

    async def get_water_last(self, user_id: str) -> str:
        """获取用户上次喝水时间戳
        
        Args:
            user_id: 用户ID
            
        Returns:
            ISO 时间戳字符串 (YYYY-MM-DD HH:MM:SS)
        """
        data = await self._get_user_data(user_id)
        return data.get(WATER_LAST_KEY, "")

    async def set_water_last(self, user_id: str, ts: str) -> None:
        """设置用户上次喝水时间戳
        
        Args:
            user_id: 用户ID
            ts: 时间戳字符串
        """
        data = await self._get_user_data(user_id)
        data[WATER_LAST_KEY] = ts
        await self._save_user_data(user_id, data)

    async def set_temp_override(self, user_id: str, habit_title: str, new_time: str) -> bool:
        """临时修改习惯时间（仅今天生效）
        
        存储格式: "YYYY-MM-DD HH:MM"
        
        Args:
            user_id: 用户ID
            habit_title: 习惯标题
            new_time: 新时间 (HH:MM)
            
        Returns:
            是否成功修改
        """
        data = await self._get_user_data(user_id)
        today = datetime.now().strftime("%Y-%m-%d")
        
        found = False
        for habit in data.get(HABITS_KEY, []):
            if habit.get("title") == habit_title:
                habit["temp_override"] = f"{today} {new_time}"
                found = True
        
        if found:
            await self._save_user_data(user_id, data)
            logger.info(f"{LOG_PREFIX} 用户 {user_id} 临时修改习惯 {habit_title} 为 {new_time}")
            return True
        
        return False

    async def get_effective_time(self, user_id: str, habit_title: str, default_time: str) -> str:
        """获取习惯的有效时间（优先返回临时修改时间）
        
        如果临时修改过期（不是今天），返回默认时间
        
        Args:
            user_id: 用户ID
            habit_title: 习惯标题
            default_time: 默认时间 (HH:MM)
            
        Returns:
            有效时间 (HH:MM)
        """
        data = await self._get_user_data(user_id)
        today = datetime.now().strftime("%Y-%m-%d")
        
        for habit in data.get(HABITS_KEY, []):
            if habit.get("title") == habit_title:
                temp = habit.get("temp_override", "")
                if temp and temp.startswith(today):
                    return temp.split(" ")[1] if " " in temp else default_time
        
        return default_time

    async def clear_expired_overrides(self, user_id: str) -> None:
        """清理过期的临时修改（只保留今天的）
        
        Args:
            user_id: 用户ID
        """
        data = await self._get_user_data(user_id)
        today = datetime.now().strftime("%Y-%m-%d")
        changed = False
        
        for habit in data.get(HABITS_KEY, []):
            temp = habit.get("temp_override", "")
            if temp and not temp.startswith(today):
                habit.pop("temp_override", None)
                changed = True
        
        if changed:
            await self._save_user_data(user_id, data)
