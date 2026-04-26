```python
"""日程管理 LLM 工具

提供自然语言操作日程的能力：
- 创建日程
- 删除日程
- 查看日程列表
- 修改日程时间/标题
"""
from datetime import datetime, timedelta
from typing import Optional

from dateutil.relativedelta import relativedelta
from dateutil import parser as date_parser
from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot import logger
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.agent.run_context import ContextWrapper

from ..schedule_store import ScheduleItem


# ============ Tool 定义 ============

@dataclass(config=dict(arbitrary_types_allowed=True))
class CreateScheduleTool(FunctionTool[AstrAgentContext]):
    """创建新日程工具"""
    
    name: str = "create_schedule"
    description: str = "创建新日程。用于当用户想要添加一个日程安排时调用。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "日程标题/内容，如「开会」「组会」「读书会」等",
                },
                "datetime_str": {
                    "type": "string",
                    "description": "日期时间，格式如「2024-01-15 14:30」「明天9点」「后天下午3点」「今天晚上8点」",
                },
                "description": {
                    "type": "string",
                    "description": "可选的备注描述",
                },
            },
            "required": ["title", "datetime_str"],
        }
    )

    def __init__(self, **data):
        super().__init__(**data)
        self.store = None
        self.default_user_id = None

    def inject_store(self, store, default_user_id):
        """注入 store 和 default_user_id"""
        self.store = store
        self.default_user_id = default_user_id

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        try:
            title = kwargs.get("title", "").strip()
            datetime_str = kwargs.get("datetime_str", "").strip()
            description = kwargs.get("description", "").strip()

            if not title or not datetime_str:
                return f"请提供日程标题和时间"

            now = datetime.now()
            dt = None
            
            if "明天" in datetime_str:
                time_part = datetime_str.replace("明天", "").strip()
                dt = now + relativedelta(days=1)
                if time_part:
                    t = datetime.strptime(time_part.replace("点", ":00").replace("：", ":"), "%H:%M")
                    dt = dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            elif "后天" in datetime_str:
                time_part = datetime_str.replace("后天", "").strip()
                dt = now + relativedelta(days=2)
                if time_part:
                    t = datetime.strptime(time_part.replace("点", ":00").replace("：", ":"), "%H:%M")
                    dt = dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            elif "今天" in datetime_str:
                time_part = datetime_str.replace("今天", "").strip()
                dt = now
                if time_part:
                    t = datetime.strptime(time_part.replace("点", ":00").replace("：", ":"), "%H:%M")
                    dt = dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            else:
                from dateutil import parser as date_parser
                dt = date_parser.parse(datetime_str)

            event = context.context.event
            user_id = str(event.get_sender_id() or '')
            if not user_id and self.default_user_id:
                user_id = self.default_user_id

            if not user_id:
                return "无法确定用户身份"

            if not self.store:
                return "日程存储服务未初始化"

            item = ScheduleItem(
                type="schedule",
                title=title,
                time=dt.strftime("%Y-%m-%d %H:%M"),
                context=description
            )

            await self.store.add_item(user_id, item)
            return f"已创建日程「{title}」，时间：{dt.strftime('%m-%d %H:%M')} ✅"
            
        except Exception as e:
            logger.error(f"创建日程失败: {e}")
            return f"创建日程失败: {e}"


@dataclass(config=dict(arbitrary_types_allowed=True))
class DeleteScheduleTool(FunctionTool[AstrAgentContext]):
    """删除日程工具"""
    
    name: str = "delete_schedule"
    description: str = "删除日程。用于当用户想要取消或删除一个日程时调用。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "schedule_id": {
                    "type": "string",
                    "description": "日程ID（精确匹配），如 abc123",
                    "nullable": True,
                },
                "title_keyword": {
                    "type": "string",
                    "description": "日程标题关键词（模糊匹配），如「开会」「组会」",
                    "nullable": True,
                },
            },
            "required": [],
        }
    )

    def __init__(self, **data):
        super().__init__(**data)
        self.store = None
        self.default_user_id = None

    def inject_store(self, store, default_user_id):
        self.store = store
        self.default_user_id = default_user_id

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        try:
            schedule_id = (kwargs.get("schedule_id") or "").strip()
            title_keyword = (kwargs.get("title_keyword") or "").strip()

            if not schedule_id and not title_keyword:
                return "请提供日程ID或标题关键词"

            event = context.context.event
            user_id = str(event.get_sender_id() or '')
            if not user_id and self.default_user_id:
                user_id = self.default_user_id

            if not user_id:
                return "无法确定用户身份"

            if not self.store:
                return "日程存储服务未初始化"

            if schedule_id:
                success = await self.store.remove_item(user_id, schedule_id)
                return f"已删除日程 ✅" if success else "未找到指定日程"

            if title_keyword:
                schedules_dict = await self.store.get_schedules(user_id)
                all_items = schedules_dict.get("schedules", []) + schedules_dict.get("habits", [])
                matches = [s for s in all_items if title_keyword in s.title]

                if not matches:
                    return f"没有找到包含「{title_keyword}」的日程"
                elif len(matches) == 1:
                    await self.store.remove_item(user_id, matches[0].id)
                    return f"已删除日程「{matches[0].title}」✅"
                else:
                    lines = ["找到多个匹配日程，请提供更具体的信息："]
                    for s in matches:
                        lines.append(f"  [{s.id}] {s.title} @ {s.time}")
                    return "\n".join(lines)

            return "请提供日程ID或标题关键词"

        except Exception as e:
            logger.error(f"删除日程失败: {e}")
            return f"删除日程失败: {e}"


@dataclass(config=dict(arbitrary_types_allowed=True))
class ListSchedulesTool(FunctionTool[AstrAgentContext]):
    """查看日程列表工具"""
    
    name: str = "list_schedules"
    description: str = "查看日程列表。用于当用户想要查看自己有哪些日程安排时调用。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "days": {
                    "type": "number",
                    "description": "查看最近几天的日程，默认7天",
                    "nullable": True,
                },
            },
            "required": [],
        }
    )

    def __init__(self, **data):
        super().__init__(**data)
        self.store = None
        self.default_user_id = None

    def inject_store(self, store, default_user_id):
        self.store = store
        self.default_user_id = default_user_id

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        try:
            days = kwargs.get("days", 7)
            if isinstance(days, str):
                days = int(days)

            event = context.context.event
            user_id = str(event.get_sender_id() or '')
            if not user_id and self.default_user_id:
                user_id = self.default_user_id

            if not user_id:
                return "无法确定用户身份"

            if not self.store:
                return "日程存储服务未初始化"

            schedules_dict = await self.store.get_schedules(user_id)
            all_items = schedules_dict.get("schedules", []) + schedules_dict.get("habits", [])
            
            now = datetime.now()
            future = now + timedelta(days=days)
            
            user_schedules = []
            for s in all_items:
                if not s.time:
                    continue
                try:
                    dt = datetime.strptime(s.time, "%Y-%m-%d %H:%M")
                    if now <= dt <= future:
                        user_schedules.append((dt, s))
                except Exception:
                    continue
            
            if not user_schedules:
                return f"最近{days}天没有日程安排~"

            user_schedules.sort(key=lambda x: x[0])

            lines = [f"📋 接下来{days}天日程（共{len(user_schedules)}个）：", ""]
            current_date = None
            
            for dt, s in user_schedules:
                date_str = dt.strftime("%m-%d")
                if date_str != current_date:
                    current_date = date_str
                    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][dt.weekday()]
                    lines.append(f"━━━ {date_str} {weekday} ━━━")
                
                lines.append(f"  ⏰ {dt.strftime('%H:%M')} │ {s.title}")
                if s.context:
                    lines.append(f"      📝 {s.context}")

            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"查看日程失败: {e}")
            return f"查看日程失败: {e}"


@dataclass(config=dict(arbitrary_types_allowed=True))
class UpdateScheduleTool(FunctionTool[AstrAgentContext]):
    """修改日程工具"""
    
    name: str = "update_schedule"
    description: str = "修改日程。用于当用户想要修改某个日程的时间、标题或备注时调用。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "schedule_id": {
                    "type": "string",
                    "description": "日程ID（精确匹配）",
                    "nullable": True,
                },
                "title_keyword": {
                    "type": "string",
                    "description": "日程标题关键词（模糊匹配），用于定位日程",
                    "nullable": True,
                },
                "new_title": {
                    "type": "string",
                    "description": "新标题",
                    "nullable": True,
                },
                "new_datetime": {
                    "type": "string",
                    "description": "新时间，格式如「2024-01-15 14:30」「明天9点」",
                    "nullable": True,
                },
                "new_description": {
                    "type": "string",
                    "description": "新备注",
                    "nullable": True,
                },
            },
            "required": [],
        }
    )

    def __init__(self, **data):
        super().__init__(**data)
        self.store = None
        self.default_user_id = None

    def inject_store(self, store, default_user_id):
        self.store = store
        self.default_user_id = default_user_id

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        try:
            schedule_id = (kwargs.get("schedule_id") or "").strip()
            title_keyword = (kwargs.get("title_keyword") or "").strip()
            new_title = (kwargs.get("new_title") or "").strip()
            new_datetime = (kwargs.get("new_datetime") or "").strip()
            new_description = (kwargs.get("new_description") or "").strip()

            if not schedule_id and not title_keyword:
                return "请提供要修改的日程ID或标题关键词"

            if not new_title and not new_datetime and not new_description:
                return "请提供要修改的内容（新标题/新时间/新备注）"

            event = context.context.event
            user_id = str(event.get_sender_id() or '')
            if not user_id and self.default_user_id:
                user_id = self.default_user_id

            if not user_id:
                return "无法确定用户身份"

            if not self.store:
                return "日程存储服务未初始化"

            schedules_dict = await self.store.get_schedules(user_id)
            all_items = schedules_dict.get("schedules", []) + schedules_dict.get("habits", [])
            
            matches = []
            for s in all_items:
                if schedule_id and s.id == schedule_id:
                    matches = [s]
                    break
                elif title_keyword and title_keyword in s.title:
                    matches.append(s)

            if not matches:
                return "没有找到匹配的日程"

            if len(matches) > 1:
                lines = ["找到多个匹配日程，请提供更具体的信息："]
                for s in matches:
                    lines.append(f"  [{s.id}] {s.title} @ {s.time}")
                return "\n".join(lines)

            target = matches[0]
            
            if new_title:
                target.title = new_title
            if new_description:
                target.context = new_description
            if new_datetime:
                dt = date_parser.parse(new_datetime)
                target.time = dt.strftime("%Y-%m-%d %H:%M")

            await self.store.update_item(user_id, target)
            
            changes = []
            if new_title:
                changes.append(f"标题改为「{new_title}」")
            if new_datetime:
                changes.append(f"时间改为{new_datetime}")
            if new_description:
                changes.append("备注已更新")
            
            return f"已修改日程：{', '.join(changes)} ✅"
            
        except Exception as e:
            logger.error(f"修改日程失败: {e}")
            return f"修改日程失败: {e}"


# ============ 工具注册 ============

def register_schedule_tools(plugin_instance) -> None:
    """注册日程管理工具到 AstrBot"""
    # 创建工具实例
    create_tool = CreateScheduleTool()
    delete_tool = DeleteScheduleTool()
    list_tool = ListSchedulesTool()
    update_tool = UpdateScheduleTool()
    
    # 注入依赖
    store = getattr(plugin_instance, 'store', None)
    default_user_id = getattr(plugin_instance, 'default_user_id', None)
    
    create_tool.inject_store(store, default_user_id)
    delete_tool.inject_store(store, default_user_id)
    list_tool.inject_store(store, default_user_id)
    update_tool.inject_store(store, default_user_id)
    
    # 注册到 AstrBot
    plugin_instance.context.add_llm_tools(
        create_tool,
        delete_tool,
        list_tool,
        update_tool,
    )
    
    logger.info("[ScheduleAssistant] 日程管理工具已注册：create_schedule, delete_schedule, list_schedules, update_schedule")
```