"""日程管理 LLM 工具

提供自然语言操作日程的能力：
- 创建日程
- 删除日程
- 查看日程列表
- 修改日程时间/标题
"""

from datetime import datetime, timedelta

from astrbot.api import logger
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.astr_agent_context import AstrAgentContext
from pydantic import Field
from pydantic.dataclasses import dataclass

from ..schedule_store import ScheduleItem
from ..time_parser import (
    format_item_when,
    format_when_label,
    is_all_day_event,
    parse_item_time,
    parse_range_end,
    parse_schedule_time,
)

# ============ Tool 定义 ============


@dataclass(config=dict(arbitrary_types_allowed=True))  # noqa: C408
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
                    "description": (
                        "日期时间，格式如「2024-01-15 14:30」"
                        "「明天9点」「后天下午3点」「今天晚上8点」；"
                        "也支持区间「明天9点到11点」与全天「明天全天」"
                        "（纯日期如「明天」即全天）"
                    ),
                },
                "end_datetime_str": {
                    "type": "string",
                    "description": (
                        "区间日程的结束时间，如「11点」「2024-01-15 16:30」；"
                        "不填则为单时间点（Apple 日历按开始后 1 小时）"
                    ),
                    "nullable": True,
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
        self._plugin = None

    def inject_store(self, store, default_user_id):
        """注入 store 和 default_user_id"""
        self.store = store
        self.default_user_id = default_user_id

    def inject_plugin(self, plugin_instance):
        """注入插件实例（用于 Apple 日历写入）"""
        self._plugin = plugin_instance

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        try:
            # LLM 可能显式传 null：kwargs.get(key, "") 的默认值只在键缺失时生效，
            # 故统一用 `or ""` 兜底（schema 已标 nullable）
            title = (kwargs.get("title") or "").strip()
            datetime_str = (kwargs.get("datetime_str") or "").strip()
            end_datetime_str = (kwargs.get("end_datetime_str") or "").strip()
            description = (kwargs.get("description") or "").strip()

            if not title or not datetime_str:
                return "请提供日程标题和时间"

            start, end, all_day = parse_schedule_time(datetime_str)
            if start is None:
                return (
                    "时间格式无法解析，请使用如「2024-01-15 14:30」「明天9点」"
                    "「明天9点到11点」（区间）「明天全天」（全天）"
                )
            if end_datetime_str and not all_day:
                end = parse_range_end(end_datetime_str, start)
                if end is None:
                    return "结束时间格式无法解析，请使用如「11点」「2024-01-15 16:30」"
            if end is not None and end <= start:
                return "结束时间需要晚于开始时间"

            event = context.context.event
            user_id = str(event.get_sender_id() or "")
            if not user_id and self.default_user_id:
                user_id = self.default_user_id

            if not user_id:
                return "无法确定用户身份"

            if not self.store:
                return "日程存储服务未初始化"

            item = ScheduleItem(
                type="schedule",
                title=title,
                time=(
                    start.strftime("%Y-%m-%d")
                    if all_day
                    else start.strftime("%Y-%m-%d %H:%M")
                ),
                end_time=(
                    None if all_day or end is None else end.strftime("%Y-%m-%d %H:%M")
                ),
                context=description,
                all_day=all_day,
            )

            await self.store.add_item(user_id, item)

            # Apple 日历写入（需 enable_apple_calendar_sync 开启且已配置 Apple Calendar）
            apple_msg = ""
            if self._plugin is not None:
                try:
                    if (
                        self._plugin.config.get("enable_apple_calendar_sync")
                        and self._plugin.apple_calendar
                    ):
                        created_uid = await self._plugin.apple_calendar.create_event(
                            summary=title,
                            start=start,
                            end=end,
                            description=description,
                            all_day=all_day,
                        )
                        if created_uid:
                            # 记录 UID：否则下次同步会把它当成新事件再入库一份
                            item.apple_uid = created_uid
                            await self.store.update_item(user_id, item)
                            apple_msg = "，已同步到 Apple 日历"
                        else:
                            # 没拿到 UID 说明 Apple 侧没写成（如 401/403）：
                            # 不能回成功文案，否则本地条目会带着假 UID 被下轮同步删除
                            logger.warning(
                                f"Apple 日历写入未成功，本地日程不同步 user={user_id} "
                                f"title={title}"
                            )
                except Exception as e:
                    logger.warning(f"Apple 日历写入失败: {e}")

            return (
                f"已创建日程「{title}」，"
                f"时间：{format_when_label(start, end, all_day)} ✅{apple_msg}"
            )

        except Exception as e:
            logger.error(f"创建日程失败: {e}")
            return f"创建日程失败: {e}"


@dataclass(config=dict(arbitrary_types_allowed=True))  # noqa: C408
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
        self._plugin = None

    def inject_store(self, store, default_user_id):
        self.store = store
        self.default_user_id = default_user_id

    def inject_plugin(self, plugin_instance):
        """注入插件实例（用于 Apple 日历删除）"""
        self._plugin = plugin_instance

    async def _sync_delete_to_apple(self, title: str):
        """尝试从 Apple 日历中删除对应事件（失败只告警，不向用户谎报成功）"""
        if self._plugin is None:
            return
        try:
            if (
                not self._plugin.config.get("enable_apple_calendar_sync")
                or not self._plugin.apple_calendar
            ):
                return
            for evt, cal_id in await self._plugin.apple_calendar.find_events_by_summary(
                title
            ):
                deleted = await self._plugin.apple_calendar.delete_event(
                    evt["uid"], cal_id
                )
                if not deleted:
                    # Apple 侧没删掉：下轮同步会按 UID 把这条日程拉回本地，
                    # 必须留下可排查的告警（本地删除已完成，不阻塞用户操作）
                    logger.warning(
                        f"Apple 日历同步删除未成功，下轮同步可能恢复该日程: "
                        f"title={title} uid={evt.get('uid')} calendar={cal_id}"
                    )
        except Exception as e:
            logger.warning(f"Apple 日历同步删除失败: {e}")

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        try:
            schedule_id = (kwargs.get("schedule_id") or "").strip()
            title_keyword = (kwargs.get("title_keyword") or "").strip()

            if not schedule_id and not title_keyword:
                return "请提供日程ID或标题关键词"

            event = context.context.event
            user_id = str(event.get_sender_id() or "")
            if not user_id and self.default_user_id:
                user_id = self.default_user_id

            if not user_id:
                return "无法确定用户身份"

            if not self.store:
                return "日程存储服务未初始化"

            if schedule_id:
                schedules_dict = await self.store.get_schedules(user_id)
                all_items = schedules_dict.get("schedules", []) + schedules_dict.get(
                    "habits", []
                )
                target = next((s for s in all_items if s.id == schedule_id), None)
                success = await self.store.remove_item(user_id, schedule_id)
                # 与关键词删除路径保持一致：本地删除后同步删除 Apple 日历同名事件，
                # 否则下次同步会把日程拉回来
                if success and target:
                    await self._sync_delete_to_apple(target.title)
                return "已删除日程 ✅" if success else "未找到指定日程"

            if title_keyword:
                schedules_dict = await self.store.get_schedules(user_id)
                all_items = schedules_dict.get("schedules", []) + schedules_dict.get(
                    "habits", []
                )
                matches = [s for s in all_items if title_keyword in s.title]

                if not matches:
                    return f"没有找到包含「{title_keyword}」的日程"
                elif len(matches) == 1:
                    await self.store.remove_item(user_id, matches[0].id)
                    await self._sync_delete_to_apple(matches[0].title)
                    return f"已删除日程「{matches[0].title}」✅"
                else:
                    lines = ["找到多个匹配日程，请提供更具体的信息："]
                    for s in matches:
                        lines.append(
                            f"  [{s.id}] {s.title} · "
                            f"{format_item_when(s, with_date=True)}"
                        )
                    return "\n".join(lines)

            return "请提供日程ID或标题关键词"

        except Exception as e:
            logger.error(f"删除日程失败: {e}")
            return f"删除日程失败: {e}"


@dataclass(config=dict(arbitrary_types_allowed=True))  # noqa: C408
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
            # LLM 可能显式传 null（schema 标了 nullable）或数字字符串：
            # timedelta(days=None) 抛 TypeError、timedelta(days="7") 同样不接受
            days = kwargs.get("days") or 7
            try:
                days = int(str(days).strip() or 7)
            except ValueError:
                days = 7

            event = context.context.event
            user_id = str(event.get_sender_id() or "")
            if not user_id and self.default_user_id:
                user_id = self.default_user_id

            if not user_id:
                return "无法确定用户身份"

            if not self.store:
                return "日程存储服务未初始化"

            schedules_dict = await self.store.get_schedules(user_id)
            all_items = schedules_dict.get("schedules", []) + schedules_dict.get(
                "habits", []
            )

            now = datetime.now()
            future = now + timedelta(days=days)

            user_schedules = []
            for s in all_items:
                if not s.time:
                    continue
                dt = parse_item_time(s.time)
                if not dt:
                    logger.debug(f"日程时间解析失败，跳过: {s.time!r}")
                    continue
                is_all_day = is_all_day_event(s)
                if (now <= dt <= future) or (
                    is_all_day and now.date() <= dt.date() <= future.date()
                ):
                    user_schedules.append((dt, s))

            if not user_schedules:
                return f"最近{days}天没有日程安排~"

            user_schedules.sort(key=lambda x: x[0])

            lines = [f"📋 接下来{days}天日程（共{len(user_schedules)}个）：", ""]
            current_date = None

            for dt, s in user_schedules:
                date_str = dt.strftime("%m-%d")
                if date_str != current_date:
                    current_date = date_str
                    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
                        dt.weekday()
                    ]
                    lines.append(f"━━━ {date_str} {weekday} ━━━")

                lines.append(f"  {format_item_when(s)} │ {s.title}")
                if s.context:
                    lines.append(f"      📝 {s.context}")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"查看日程失败: {e}")
            return f"查看日程失败: {e}"


@dataclass(config=dict(arbitrary_types_allowed=True))  # noqa: C408
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
                    "description": (
                        "新时间，格式如「2024-01-15 14:30」「明天9点」；"
                        "也支持区间「明天9点到11点」与全天「明天全天」"
                    ),
                    "nullable": True,
                },
                "new_end_datetime": {
                    "type": "string",
                    "description": "区间日程的新结束时间，如「11点」，需与 new_datetime 一起给",
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
        self._plugin = None

    def inject_store(self, store, default_user_id):
        self.store = store
        self.default_user_id = default_user_id

    def inject_plugin(self, plugin_instance):
        """注入插件实例（用于 Apple 日历写回）"""
        self._plugin = plugin_instance

    async def _sync_update_to_apple(self, user_id: str, item: ScheduleItem) -> None:
        """把改期/改标题写回 Apple 日历（同一 UID 的 CalDAV PUT 即更新）。

        不写回的话，下轮 Apple→本地同步会按 apple_uid 用 Apple 旧值反写本地
        （schedule_store.sync_from_apple_calendar）：用户的修改被静默还原，
        且改期分支会重置 last_triggered 让旧时间再提醒一次。

        写回失败时清空 apple_uid 让该条脱离 Apple 同步：本地已按用户意图改好，
        保留 apple_uid 只会被 Apple 旧值覆盖回去；宁可该条不再与 Apple 同步
        （代价：Apple 侧留一份旧事件，后续同步可能多入库一条本地日程），
        也不能让用户的修改静默丢失。
        """
        if not item.apple_uid or self._plugin is None:
            return
        try:
            if (
                not self._plugin.config.get("enable_apple_calendar_sync")
                or not self._plugin.apple_calendar
            ):
                return
            start, end, all_day = parse_schedule_time(item.time)
            if start is None:
                return
            if end is None and item.end_time:
                end = parse_range_end(item.end_time, start)
            new_uid = await self._plugin.apple_calendar.create_event(
                summary=item.title,
                start=start,
                end=end,
                description=item.context,
                all_day=all_day,
                uid=item.apple_uid,
            )
            if new_uid:
                logger.debug(
                    f"Apple 日历已更新: title={item.title} uid={new_uid} "
                    f"time={item.time}"
                )
                return
            logger.warning(
                f"Apple 日历更新未成功，解除该条目的 Apple 同步关联: "
                f"title={item.title} uid={item.apple_uid}"
            )
        except Exception as e:
            logger.warning(f"Apple 日历更新失败: {e}")
        # 写回失败：清空 UID 并落盘，避免下轮同步用 Apple 旧值覆盖本地修改
        item.apple_uid = None
        await self.store.update_item(user_id, item)

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        try:
            schedule_id = (kwargs.get("schedule_id") or "").strip()
            title_keyword = (kwargs.get("title_keyword") or "").strip()
            new_title = (kwargs.get("new_title") or "").strip()
            new_datetime = (kwargs.get("new_datetime") or "").strip()
            new_end_datetime = (kwargs.get("new_end_datetime") or "").strip()
            new_description = (kwargs.get("new_description") or "").strip()

            if not schedule_id and not title_keyword:
                return "请提供要修改的日程ID或标题关键词"

            if (
                not new_title
                and not new_datetime
                and not new_end_datetime
                and not new_description
            ):
                return "请提供要修改的内容（新标题/新时间/新备注）"

            event = context.context.event
            user_id = str(event.get_sender_id() or "")
            if not user_id and self.default_user_id:
                user_id = self.default_user_id

            if not user_id:
                return "无法确定用户身份"

            if not self.store:
                return "日程存储服务未初始化"

            schedules_dict = await self.store.get_schedules(user_id)
            all_items = schedules_dict.get("schedules", []) + schedules_dict.get(
                "habits", []
            )

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
                    lines.append(
                        f"  [{s.id}] {s.title} · {format_item_when(s, with_date=True)}"
                    )
                return "\n".join(lines)

            target = matches[0]

            # 时间解析先行（出错时不落任何改动）
            parsed = None
            if new_end_datetime and not new_datetime:
                return "请一并提供开始时间，或直接用「9点到11点」的区间写法"
            if new_datetime:
                start, end, all_day = parse_schedule_time(new_datetime)
                if start is None:
                    return (
                        "时间格式无法解析，请使用如「明天9点」"
                        "「明天9点到11点」（区间）「明天全天」（全天）"
                    )
                if new_end_datetime and not all_day:
                    end = parse_range_end(new_end_datetime, start)
                    if end is None:
                        return (
                            "结束时间格式无法解析，请使用如「11点」「2024-01-15 16:30」"
                        )
                if end is not None and end <= start:
                    return "结束时间需要晚于开始时间"
                parsed = (start, end, all_day)

            if new_title:
                target.title = new_title
            if new_description:
                target.context = new_description

            time_label = None
            if parsed is not None:
                start, end, all_day = parsed
                new_time = (
                    start.strftime("%Y-%m-%d")
                    if all_day
                    else start.strftime("%Y-%m-%d %H:%M")
                )
                new_end = (
                    None if all_day or end is None else end.strftime("%Y-%m-%d %H:%M")
                )
                if (target.time, target.end_time, target.all_day) != (
                    new_time,
                    new_end,
                    all_day,
                ):
                    target.time = new_time
                    target.end_time = new_end
                    target.all_day = all_day
                    # 改期重新提醒（与 Apple 同步改期同口径）
                    target.last_triggered = None
                time_label = format_when_label(start, end, all_day)

            await self.store.update_item(user_id, target)

            # 带 apple_uid 的条目要把改动写回 Apple：否则下轮同步用 Apple 旧值反写本地
            await self._sync_update_to_apple(user_id, target)

            changes = []
            if new_title:
                changes.append(f"标题改为「{new_title}」")
            if time_label:
                changes.append(f"时间改为{time_label}")
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
    store = getattr(plugin_instance, "store", None)
    default_user_id = getattr(plugin_instance, "default_user_id", None)

    create_tool.inject_store(store, default_user_id)
    delete_tool.inject_store(store, default_user_id)
    list_tool.inject_store(store, default_user_id)
    update_tool.inject_store(store, default_user_id)

    # 注入插件实例（用于 Apple 日历双向同步）
    create_tool.inject_plugin(plugin_instance)
    delete_tool.inject_plugin(plugin_instance)
    update_tool.inject_plugin(plugin_instance)

    # 注册到 AstrBot
    plugin_instance.context.add_llm_tools(
        create_tool,
        delete_tool,
        list_tool,
        update_tool,
    )

    logger.info(
        "[ScheduleAssistant] 日程管理工具已注册："
        "create_schedule, delete_schedule, list_schedules, update_schedule"
    )
