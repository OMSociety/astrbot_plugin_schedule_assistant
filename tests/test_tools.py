"""LLM 日程工具测试。"""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from schedule_assistant.schedule_store import ScheduleItem
from schedule_assistant.settings import Settings
from schedule_assistant.tools.schedule_tools import (
    CreateScheduleTool,
    DeleteScheduleTool,
    ListSchedulesTool,
    UpdateScheduleTool,
)

TZ = ZoneInfo("Asia/Shanghai")
UMO = "qq:FriendMessage:10001"


class FakeStore:
    def __init__(self):
        self.items = {}

    async def list_items(self, umo):
        return list(self.items.get(umo, []))

    async def add_item(self, umo, item):
        self.items.setdefault(umo, []).append(item)
        return item

    async def update_item(self, umo, item):
        return item

    async def remove_item(self, umo, item_id):
        self.items[umo] = [i for i in self.items.get(umo, []) if i.id != item_id]


class FakeScheduling:
    def __init__(self):
        self.cancelled = []

    async def cancel_item_jobs(self, umo, item_id):
        self.cancelled.append((umo, item_id))


def _context(umo=UMO):
    event = SimpleNamespace(unified_msg_origin=umo)
    return SimpleNamespace(context=SimpleNamespace(event=event))


def _plugin(store):
    plugin = SimpleNamespace(
        apple=None, scheduling=FakeScheduling(), settings=Settings(timezone=TZ)
    )
    return plugin, store


def _tomorrow_at(hour):
    return (datetime.now(TZ) + timedelta(days=1)).strftime(f"%Y-%m-%d {hour:02d}:00")


def test_create_list_update_delete():
    store = FakeStore()
    plugin, _ = _plugin(store)
    context = _context()

    create = CreateScheduleTool()
    create.inject(store, UMO, plugin)
    result = asyncio.run(
        create.call(
            context, title="组会", datetime_str=_tomorrow_at(9), description="带材料"
        )
    )
    assert "已创建日程「组会」" in result
    assert len(store.items[UMO]) == 1
    item_id = store.items[UMO][0].id

    listing = ListSchedulesTool()
    listing.inject(store, UMO, plugin)
    result = asyncio.run(listing.call(context, days=7))
    assert "组会" in result
    assert "带材料" in result

    update = UpdateScheduleTool()
    update.inject(store, UMO, plugin)
    result = asyncio.run(
        update.call(
            context,
            schedule_id=item_id,
            new_title="组会（改）",
            new_datetime=_tomorrow_at(10),
        )
    )
    assert "已修改日程" in result
    assert store.items[UMO][0].title == "组会（改）"
    assert plugin.scheduling.cancelled

    delete = DeleteScheduleTool()
    delete.inject(store, UMO, plugin)
    result = asyncio.run(delete.call(context, title_keyword="组会（改）"))
    assert "已删除日程" in result
    assert store.items[UMO] == []


def test_tool_uses_session_umo_not_sender_id():
    store = FakeStore()
    plugin, _ = _plugin(store)
    context = _context()

    create = CreateScheduleTool()
    create.inject(store, "qq:FriendMessage:other", plugin)
    asyncio.run(create.call(context, title="群日程", datetime_str=_tomorrow_at(9)))

    assert "群日程" in [item.title for item in store.items[UMO]]
    assert "qq:FriendMessage:other" not in store.items


def test_delete_multiple_matches_returns_candidates():
    store = FakeStore()
    plugin, _ = _plugin(store)
    context = _context()
    store.items[UMO] = [
        ScheduleItem(title="组会一", time=_tomorrow_at(9)),
        ScheduleItem(title="组会二", time=_tomorrow_at(10)),
    ]

    delete = DeleteScheduleTool()
    delete.inject(store, UMO, plugin)
    result = asyncio.run(delete.call(context, title_keyword="组会"))

    assert "找到多个匹配日程" in result
    assert "组会一" in result
    assert "组会二" in result


def test_create_rejects_unparsable_time():
    store = FakeStore()
    plugin, _ = _plugin(store)

    create = CreateScheduleTool()
    create.inject(store, UMO, plugin)
    result = asyncio.run(
        create.call(_context(), title="组会", datetime_str="某个不确定的时候")
    )

    assert "时间格式无法解析" in result


def test_list_reports_empty():
    store = FakeStore()
    plugin, _ = _plugin(store)

    listing = ListSchedulesTool()
    listing.inject(store, UMO, plugin)
    result = asyncio.run(listing.call(_context(), days=3))

    assert "最近3天没有日程安排" in result
