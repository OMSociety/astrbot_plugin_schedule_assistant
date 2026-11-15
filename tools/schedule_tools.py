"""日程管理 LLM 工具。"""

from __future__ import annotations

from datetime import datetime, timedelta

from astrbot.api import logger
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.astr_agent_context import AstrAgentContext
from pydantic import Field
from pydantic.dataclasses import dataclass

from ..schedule_store import ScheduleItem

FALLBACK_ERROR = "操作失败，请稍后重试"
MAX_YEAR = 2100


def _now(plugin) -> datetime:
    settings = getattr(plugin, "settings", None)
    timezone = getattr(settings, "timezone", None)
    if timezone is None:
        return datetime.now()
    return datetime.now(timezone).replace(tzinfo=None)


def _resolve_umo(context: ContextWrapper[AstrAgentContext], default_umo: str | None):
    event = getattr(context.context, "event", None)
    umo = str(getattr(event, "unified_msg_origin", "") or "") if event else ""
    return umo or (default_umo or "")


def _format_time(value: datetime, all_day: bool) -> str:
    return value.strftime("%Y-%m-%d") if all_day else value.strftime("%Y-%m-%d %H:%M")


def _time_label(start: datetime, end: datetime | None, all_day: bool) -> str:
    if all_day:
        return f"{start:%m-%d} 全天"
    if end is not None:
        if end.date() == start.date():
            return f"{start:%m-%d %H:%M}-{end:%H:%M}"
        return f"{start:%m-%d %H:%M}-{end:%m-%d %H:%M}"
    return f"{start:%m-%d %H:%M}"


def _format_item_when(item: ScheduleItem) -> str:
    try:
        start = datetime.fromisoformat(item.time.replace(" ", "T"))
    except (TypeError, ValueError):
        return item.time or ""
    if item.all_day:
        return f"全天 {start:%m-%d}"
    if item.end_time:
        try:
            end = datetime.fromisoformat(item.end_time.replace(" ", "T"))
        except (TypeError, ValueError):
            end = None
        if end is not None:
            if end.date() == start.date():
                return f"⏰ {start:%H:%M}-{end:%H:%M}"
            return f"⏰ {start:%m-%d %H:%M}-{end:%m-%d %H:%M}"
    return f"⏰ {start:%H:%M}"


def _parse_local(value: str, all_day: bool, timezone) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    if all_day:
        text = text[:10]
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        if timezone is not None:
            parsed = parsed.astimezone(timezone)
        parsed = parsed.replace(tzinfo=None)
    return parsed


def _parse_start(value: str, all_day: bool, timezone) -> datetime | None:
    return _parse_local(value, all_day, timezone)


def _parse_end(value: str, all_day: bool, timezone) -> datetime | None:
    return _parse_local(value, all_day, timezone)


def _validate_start(start: datetime, now: datetime) -> str | None:
    if start < now - timedelta(minutes=1):
        return "开始时间不能早于当前时间"
    if start.year > MAX_YEAR:
        return f"开始时间不能晚于 {MAX_YEAR} 年"
    return None


def _match_items(items, schedule_id: str, title_keyword: str):
    if schedule_id:
        return [item for item in items if item.id == schedule_id]
    if title_keyword:
        return [item for item in items if title_keyword in item.title]
    return []


def _multiple_matches(matches) -> str:
    lines = ["找到多个匹配日程，请提供更具体的信息："]
    for item in matches:
        lines.append(f"  [{item.id}] {item.title} · {_format_item_when(item)}")
    return "\n".join(lines)


async def _cancel_pending(plugin, umo: str, item_id: str) -> None:
    scheduling = getattr(plugin, "scheduling", None) if plugin is not None else None
    if scheduling is not None:
        await scheduling.cancel_item_jobs(umo, item_id)


def _timezone(plugin):
    settings = getattr(plugin, "settings", None)
    return getattr(settings, "timezone", None) if settings else None


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
                "start": {
                    "type": "string",
                    "description": (
                        "开始时间，ISO 8601 格式，如「2026-09-10 14:30」；"
                        "全天日程可直接给日期「2026-09-10」"
                    ),
                },
                "end": {
                    "type": "string",
                    "description": (
                        "结束时间，ISO 8601 格式，如「2026-09-10 16:00」；"
                        "不填则为单时间点"
                    ),
                    "nullable": True,
                },
                "all_day": {
                    "type": "boolean",
                    "description": "是否全天日程",
                    "nullable": True,
                },
                "description": {
                    "type": "string",
                    "description": "可选的备注描述",
                },
            },
            "required": ["title", "start"],
        }
    )

    def __init__(self, **data):
        super().__init__(**data)
        self.store = None
        self.default_umo = None
        self._plugin = None

    def inject(self, store, default_umo, plugin_instance):
        self.store = store
        self.default_umo = default_umo
        self._plugin = plugin_instance

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        try:
            title = (kwargs.get("title") or "").strip()
            all_day = bool(kwargs.get("all_day"))
            timezone = _timezone(self._plugin)
            now = _now(self._plugin)

            if not title:
                return "请提供日程标题"

            start = _parse_start(kwargs.get("start") or "", all_day, timezone)
            if start is None:
                return "开始时间格式无法解析，请使用 ISO 8601，如「2026-09-10 14:30」"
            invalid = _validate_start(start, now)
            if invalid:
                return invalid

            end = None
            raw_end = (kwargs.get("end") or "").strip()
            if raw_end and not all_day:
                end = _parse_end(raw_end, False, timezone)
                if end is None:
                    return (
                        "结束时间格式无法解析，请使用 ISO 8601，如「2026-09-10 16:00」"
                    )
                if end <= start:
                    return "结束时间需要晚于开始时间"

            umo = _resolve_umo(context, self.default_umo)
            if not umo:
                return "无法确定会话身份"
            if self.store is None:
                return "日程存储服务未初始化"

            item = ScheduleItem.create(
                title=title,
                time=_format_time(start, all_day),
                end_time=None if all_day or end is None else _format_time(end, False),
                context=(kwargs.get("description") or "").strip(),
                all_day=all_day,
            )
            await self.store.add_item(umo, item)

            apple_msg = ""
            apple = getattr(self._plugin, "apple", None) if self._plugin else None
            if apple is not None:
                try:
                    created_uid = await apple.create_event(
                        summary=title,
                        start=start,
                        end=end,
                        description=item.context,
                        all_day=all_day,
                    )
                    if created_uid:
                        item.apple_uid = created_uid
                        await self.store.update_item(umo, item)
                        apple_msg = "，已同步到 Apple 日历"
                    else:
                        logger.warning(
                            f"Apple 日历写入未成功，本地日程不同步 umo={umo} title={title}"
                        )
                except Exception:
                    logger.exception("Apple 日历写入失败")

            return (
                f"已创建日程「{title}」，"
                f"时间：{_time_label(start, end, all_day)} ✅{apple_msg}"
            )
        except Exception:
            logger.exception("创建日程失败")
            return f"创建日程失败，{FALLBACK_ERROR}"


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
                    "description": "日程 ID（精确匹配）",
                    "nullable": True,
                },
                "title_keyword": {
                    "type": "string",
                    "description": "日程标题关键词（模糊匹配）",
                    "nullable": True,
                },
            },
            "required": [],
        }
    )

    def __init__(self, **data):
        super().__init__(**data)
        self.store = None
        self.default_umo = None
        self._plugin = None

    def inject(self, store, default_umo, plugin_instance):
        self.store = store
        self.default_umo = default_umo
        self._plugin = plugin_instance

    async def _delete_from_apple(self, item: ScheduleItem) -> bool:
        if not item.apple_uid:
            return True
        apple = getattr(self._plugin, "apple", None) if self._plugin else None
        if apple is None:
            return True
        try:
            if await apple.delete_event(item.apple_uid):
                return True
            logger.warning(
                "Apple 日历删除未成功，本地日程保持不动: "
                f"title={item.title} uid={item.apple_uid}"
            )
            return False
        except Exception:
            logger.exception("Apple 日历删除失败")
            return False

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        try:
            schedule_id = (kwargs.get("schedule_id") or "").strip()
            title_keyword = (kwargs.get("title_keyword") or "").strip()
            if not schedule_id and not title_keyword:
                return "请提供日程 ID 或标题关键词"

            umo = _resolve_umo(context, self.default_umo)
            if not umo:
                return "无法确定会话身份"
            if self.store is None:
                return "日程存储服务未初始化"

            matches = _match_items(
                await self.store.list_items(umo), schedule_id, title_keyword
            )
            if not matches:
                return (
                    "未找到指定日程"
                    if schedule_id
                    else f"没有找到包含「{title_keyword}」的日程"
                )
            if len(matches) > 1:
                return _multiple_matches(matches)

            target = matches[0]
            if not await self._delete_from_apple(target):
                return "删除 Apple 日历事件失败，日程未删除"

            await self.store.remove_item(umo, target.id)
            await _cancel_pending(self._plugin, umo, target.id)
            return f"已删除日程「{target.title}」✅"
        except Exception:
            logger.exception("删除日程失败")
            return f"删除日程失败，{FALLBACK_ERROR}"


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
                    "description": "查看最近几天的日程，默认 7 天",
                    "nullable": True,
                },
            },
            "required": [],
        }
    )

    def __init__(self, **data):
        super().__init__(**data)
        self.store = None
        self.default_umo = None
        self._plugin = None

    def inject(self, store, default_umo, plugin_instance=None):
        self.store = store
        self.default_umo = default_umo
        self._plugin = plugin_instance

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        try:
            days = kwargs.get("days") or 7
            try:
                days = int(str(days).strip() or 7)
            except ValueError:
                days = 7
            if days <= 0:
                days = 7

            umo = _resolve_umo(context, self.default_umo)
            if not umo:
                return "无法确定会话身份"
            if self.store is None:
                return "日程存储服务未初始化"

            now = _now(self._plugin)
            future = now + timedelta(days=days)
            entries = []
            for item in await self.store.list_items(umo):
                if not item.time:
                    continue
                try:
                    start = datetime.fromisoformat(item.time.replace(" ", "T"))
                except ValueError:
                    logger.debug(f"日程时间解析失败，跳过: {item.time!r}")
                    continue
                if item.all_day:
                    if now.date() <= start.date() <= future.date():
                        entries.append((start, item))
                elif now - timedelta(minutes=1) <= start <= future:
                    entries.append((start, item))

            if not entries:
                return f"最近{days}天没有日程安排~"

            entries.sort(key=lambda pair: pair[0])
            lines = [f"📋 接下来{days}天日程（共{len(entries)}个）：", ""]
            current_date = None
            for start, item in entries:
                date_str = start.strftime("%m-%d")
                if date_str != current_date:
                    current_date = date_str
                    lines.append(f"━━━ {date_str} {format_weekday(start)} ━━━")
                lines.append(f"  {_format_item_when(item)} │ {item.title}")
                if item.context:
                    lines.append(f"      📝 {item.context}")
            return "\n".join(lines)
        except Exception:
            logger.exception("查看日程失败")
            return f"查看日程失败，{FALLBACK_ERROR}"


def format_weekday(value: datetime) -> str:
    return ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][value.weekday()]


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
                    "description": "日程 ID（精确匹配）",
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
                "new_start": {
                    "type": "string",
                    "description": "新开始时间，ISO 8601，如「2026-09-10 14:30」",
                    "nullable": True,
                },
                "new_end": {
                    "type": "string",
                    "description": "新结束时间，ISO 8601，需与 new_start 一起给",
                    "nullable": True,
                },
                "new_all_day": {
                    "type": "boolean",
                    "description": "是否改为全天日程",
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
        self.default_umo = None
        self._plugin = None

    def inject(self, store, default_umo, plugin_instance):
        self.store = store
        self.default_umo = default_umo
        self._plugin = plugin_instance

    async def _sync_to_apple(self, umo: str, item: ScheduleItem) -> None:
        if not item.apple_uid:
            return
        apple = getattr(self._plugin, "apple", None) if self._plugin else None
        if apple is None:
            return
        timezone = _timezone(self._plugin)
        try:
            start = _parse_start(item.time, item.all_day, timezone)
            if start is None:
                return
            end = None
            if item.end_time and not item.all_day:
                end = _parse_end(item.end_time, False, timezone)
            new_uid = await apple.create_event(
                summary=item.title,
                start=start,
                end=end,
                description=item.context,
                all_day=item.all_day,
                uid=item.apple_uid,
            )
            if new_uid:
                return
            logger.warning(
                "Apple 日历更新未成功，解除该条目的 Apple 同步关联: "
                f"title={item.title} uid={item.apple_uid}"
            )
        except Exception:
            logger.exception("Apple 日历更新失败")
        item.apple_uid = None
        await self.store.update_item(umo, item)

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        try:
            schedule_id = (kwargs.get("schedule_id") or "").strip()
            title_keyword = (kwargs.get("title_keyword") or "").strip()
            new_title = (kwargs.get("new_title") or "").strip()
            new_start_raw = (kwargs.get("new_start") or "").strip()
            new_end_raw = (kwargs.get("new_end") or "").strip()
            new_description = (kwargs.get("new_description") or "").strip()

            if not schedule_id and not title_keyword:
                return "请提供要修改的日程 ID 或标题关键词"
            if not (new_title or new_start_raw or new_end_raw or new_description):
                return "请提供要修改的内容（新标题/新时间/新备注）"
            if new_end_raw and not new_start_raw:
                return "请一并提供新的开始时间"

            umo = _resolve_umo(context, self.default_umo)
            if not umo:
                return "无法确定会话身份"
            if self.store is None:
                return "日程存储服务未初始化"

            matches = _match_items(
                await self.store.list_items(umo), schedule_id, title_keyword
            )
            if not matches:
                return "没有找到匹配的日程"
            if len(matches) > 1:
                return _multiple_matches(matches)

            target = matches[0]
            timezone = _timezone(self._plugin)
            now = _now(self._plugin)
            parsed = None
            if new_start_raw:
                all_day = (
                    bool(kwargs.get("new_all_day"))
                    if kwargs.get("new_all_day") is not None
                    else target.all_day
                )
                start = _parse_start(new_start_raw, all_day, timezone)
                if start is None:
                    return (
                        "开始时间格式无法解析，请使用 ISO 8601，如「2026-09-10 14:30」"
                    )
                invalid = _validate_start(start, now)
                if invalid:
                    return invalid
                end = None
                if new_end_raw and not all_day:
                    end = _parse_end(new_end_raw, False, timezone)
                    if end is None:
                        return "结束时间格式无法解析，请使用 ISO 8601，如「2026-09-10 16:00」"
                    if end <= start:
                        return "结束时间需要晚于开始时间"
                parsed = (start, end, all_day)

            if new_title:
                target.title = new_title
            if new_description:
                target.context = new_description

            time_label = None
            if parsed is not None:
                start, end, all_day = parsed
                target.time = _format_time(start, all_day)
                target.end_time = (
                    None if all_day or end is None else _format_time(end, False)
                )
                target.all_day = all_day
                target.last_triggered = None
                time_label = _time_label(start, end, all_day)

            await self.store.update_item(umo, target)
            await _cancel_pending(self._plugin, umo, target.id)
            await self._sync_to_apple(umo, target)

            changes = []
            if new_title:
                changes.append(f"标题改为「{new_title}」")
            if time_label:
                changes.append(f"时间改为{time_label}")
            if new_description:
                changes.append("备注已更新")
            return f"已修改日程：{', '.join(changes)} ✅"
        except Exception:
            logger.exception("修改日程失败")
            return f"修改日程失败，{FALLBACK_ERROR}"


def register_schedule_tools(plugin_instance) -> None:
    store = getattr(plugin_instance, "store", None)
    targets = getattr(getattr(plugin_instance, "settings", None), "target_umos", ())
    default_umo = targets[0] if targets else None

    tools = [
        CreateScheduleTool(),
        DeleteScheduleTool(),
        ListSchedulesTool(),
        UpdateScheduleTool(),
    ]
    for tool in tools:
        tool.inject(store, default_umo, plugin_instance)

    plugin_instance.context.add_llm_tools(*tools)
    logger.info(
        "日程管理工具已注册：create_schedule/delete_schedule/list_schedules/update_schedule"
    )
