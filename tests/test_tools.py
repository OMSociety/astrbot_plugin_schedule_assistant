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


class FakeApple:
    def __init__(self, uid="apple-uid", delete_ok=True):
        self.uid = uid
        self.delete_ok = delete_ok
        self.calls = []

    async def create_event(self, **kwargs):
        self.calls.append(("create", kwargs))
        return self.uid

    async def delete_event(self, uid):
        self.calls.append(("delete", uid))
        return self.delete_ok


def _context(umo=UMO):
    event = SimpleNamespace(unified_msg_origin=umo)
    return SimpleNamespace(context=SimpleNamespace(event=event))


def _plugin(store, apple=None, targets=(UMO,)):
    plugin = SimpleNamespace(
        apple=apple,
        scheduling=FakeScheduling(),
        settings=Settings(target_umos=targets, timezone=TZ),
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
        create.call(context, title="组会", start=_tomorrow_at(9), description="带材料")
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
            new_start=_tomorrow_at(10),
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


def test_create_with_end_and_all_day():
    store = FakeStore()
    plugin, _ = _plugin(store)
    context = _context()
    create = CreateScheduleTool()
    create.inject(store, UMO, plugin)

    asyncio.run(
        create.call(
            context,
            title="区间",
            start=_tomorrow_at(9),
            end=_tomorrow_at(11),
        )
    )
    assert store.items[UMO][0].end_time is not None

    asyncio.run(
        create.call(context, title="全天", start=_tomorrow_at(9)[:10], all_day=True)
    )
    assert store.items[UMO][1].all_day is True
    assert len(store.items[UMO][1].time) == 10


def test_create_rejects_past_time():
    store = FakeStore()
    plugin, _ = _plugin(store)
    create = CreateScheduleTool()
    create.inject(store, UMO, plugin)

    past = (datetime.now(TZ) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    result = asyncio.run(create.call(_context(), title="旧事", start=past))

    assert "不能早于当前时间" in result
    assert store.items == {}


def test_create_rejects_invalid_iso():
    store = FakeStore()
    plugin, _ = _plugin(store)
    create = CreateScheduleTool()
    create.inject(store, UMO, plugin)

    result = asyncio.run(create.call(_context(), title="组会", start="明天9点"))

    assert "格式无法解析" in result


def test_tool_uses_session_umo_not_sender_id():
    store = FakeStore()
    plugin, _ = _plugin(store)
    context = _context()

    create = CreateScheduleTool()
    create.inject(store, "qq:FriendMessage:other", plugin)
    asyncio.run(create.call(context, title="群日程", start=_tomorrow_at(9)))

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


def test_list_reports_empty():
    store = FakeStore()
    plugin, _ = _plugin(store)

    listing = ListSchedulesTool()
    listing.inject(store, UMO, plugin)
    result = asyncio.run(listing.call(_context(), days=3))

    assert "最近3天没有日程安排" in result


def test_tools_reject_umo_not_in_user_umos():
    store = FakeStore()
    apple = FakeApple()
    plugin, _ = _plugin(store, apple=apple)
    context = _context("qq:FriendMessage:99999")
    calls = [
        (CreateScheduleTool(), {"title": "越权", "start": _tomorrow_at(9)}),
        (DeleteScheduleTool(), {"title_keyword": "越权"}),
        (ListSchedulesTool(), {"days": 3}),
        (UpdateScheduleTool(), {"title_keyword": "越权", "new_title": "改"}),
    ]

    for tool, kwargs in calls:
        tool.inject(store, UMO, plugin)
        result = asyncio.run(tool.call(context, **kwargs))
        assert "未启用" in result

    assert store.items == {}
    assert apple.calls == []


def test_tools_reject_when_user_umos_empty():
    store = FakeStore()
    plugin, _ = _plugin(store, targets=())
    listing = ListSchedulesTool()
    listing.inject(store, UMO, plugin)

    result = asyncio.run(listing.call(_context(), days=3))

    assert "未启用" in result
    assert store.items == {}


def test_create_syncs_apple_event():
    store = FakeStore()
    apple = FakeApple()
    plugin, _ = _plugin(store, apple=apple)
    create = CreateScheduleTool()
    create.inject(store, UMO, plugin)

    result = asyncio.run(
        create.call(
            _context(), title="组会", start=_tomorrow_at(9), description="带材料"
        )
    )

    assert "已同步到 Apple 日历" in result
    item = store.items[UMO][0]
    assert item.apple_uid == "apple-uid"
    kind, payload = apple.calls[0]
    assert kind == "create"
    assert payload["summary"] == "组会"
    assert payload["all_day"] is False


def test_create_keeps_local_when_apple_write_fails():
    store = FakeStore()
    apple = FakeApple(uid=None)
    plugin, _ = _plugin(store, apple=apple)
    create = CreateScheduleTool()
    create.inject(store, UMO, plugin)

    result = asyncio.run(create.call(_context(), title="组会", start=_tomorrow_at(9)))

    assert "已创建日程「组会」" in result
    assert "已同步到 Apple 日历" not in result
    item = store.items[UMO][0]
    assert item.apple_uid is None
    assert apple.calls


def test_update_pushes_apple_uid():
    store = FakeStore()
    apple = FakeApple(uid="uid-1")
    plugin, _ = _plugin(store, apple=apple)
    item = ScheduleItem(title="组会", time=_tomorrow_at(9), apple_uid="uid-1")
    store.items[UMO] = [item]
    update = UpdateScheduleTool()
    update.inject(store, UMO, plugin)

    result = asyncio.run(
        update.call(_context(), schedule_id=item.id, new_title="组会（改）")
    )

    assert "已修改日程" in result
    kind, payload = apple.calls[0]
    assert kind == "create"
    assert payload["uid"] == "uid-1"


def test_update_clears_apple_uid_when_push_fails():
    store = FakeStore()
    apple = FakeApple(uid=None)
    plugin, _ = _plugin(store, apple=apple)
    item = ScheduleItem(title="组会", time=_tomorrow_at(9), apple_uid="uid-1")
    store.items[UMO] = [item]
    update = UpdateScheduleTool()
    update.inject(store, UMO, plugin)

    asyncio.run(update.call(_context(), schedule_id=item.id, new_title="组会（改）"))

    assert item.apple_uid is None


def test_delete_removes_apple_event():
    store = FakeStore()
    apple = FakeApple()
    plugin, _ = _plugin(store, apple=apple)
    item = ScheduleItem(title="组会", time=_tomorrow_at(9), apple_uid="uid-1")
    store.items[UMO] = [item]
    delete = DeleteScheduleTool()
    delete.inject(store, UMO, plugin)

    result = asyncio.run(delete.call(_context(), schedule_id=item.id))

    assert "已删除日程" in result
    assert store.items[UMO] == []
    assert apple.calls == [("delete", "uid-1")]


def test_delete_keeps_local_when_apple_delete_fails():
    store = FakeStore()
    apple = FakeApple(delete_ok=False)
    plugin, _ = _plugin(store, apple=apple)
    item = ScheduleItem(title="组会", time=_tomorrow_at(9), apple_uid="uid-1")
    store.items[UMO] = [item]
    delete = DeleteScheduleTool()
    delete.inject(store, UMO, plugin)

    result = asyncio.run(delete.call(_context(), schedule_id=item.id))

    assert "删除 Apple 日历事件失败" in result
    assert store.items[UMO] == [item]
