"""ScheduleStore 测试：增删改查与 Apple 同步。"""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from schedule_assistant.schedule_store import ScheduleItem, ScheduleStore

TZ = ZoneInfo("Asia/Shanghai")


class FakeKV:
    def __init__(self):
        self.data = {}

    async def get_kv_data(self, key, default=None):
        return self.data.get(key, default)

    async def put_kv_data(self, key, value):
        self.data[key] = value


def _store() -> ScheduleStore:
    return ScheduleStore(FakeKV())


def _event(uid, title="事件", days=2, all_day=False, offset=None):
    start = (datetime.now(TZ) + timedelta(days=days)).replace(microsecond=0)
    if offset is not None:
        start = start.astimezone(ZoneInfo(offset))
    event = {"uid": uid, "summary": title, "start": start.isoformat()}
    if all_day:
        event["all_day"] = True
    else:
        event["end"] = (start + timedelta(hours=1)).isoformat()
    return event


def test_add_list_get_update_remove():
    store = _store()

    async def scenario():
        item = ScheduleItem.create(title="组会", time="2026-09-10 09:00")
        await store.add_item("qq:FriendMessage:u", item)
        assert [i.title for i in await store.list_items("qq:FriendMessage:u")] == [
            "组会"
        ]
        assert (await store.get_item("qq:FriendMessage:u", item.id)).title == "组会"

        item.title = "读书会"
        assert await store.update_item("qq:FriendMessage:u", item) is True
        assert (await store.list_items("qq:FriendMessage:u"))[0].title == "读书会"

        assert await store.remove_item("qq:FriendMessage:u", item.id) is True
        assert await store.list_items("qq:FriendMessage:u") == []

    asyncio.run(scenario())


def test_sessions_are_isolated():
    store = _store()

    async def scenario():
        await store.add_item("qq:FriendMessage:a", ScheduleItem(title="a"))
        await store.add_item("qq:GroupMessage:g", ScheduleItem(title="g"))
        assert [i.title for i in await store.list_items("qq:FriendMessage:a")] == ["a"]
        assert [i.title for i in await store.list_items("qq:GroupMessage:g")] == ["g"]

    asyncio.run(scenario())


def test_empty_events_no_deletion():
    store = _store()

    async def scenario():
        await store.add_item("u", ScheduleItem(title="已有", apple_uid="u1"))
        stats = await store.sync_from_apple_calendar(
            "u", [], allow_delete=True, now=datetime.now(TZ)
        )
        assert stats == {"added": 0, "updated": 0, "deleted": 0}
        assert len(await store.list_items("u")) == 1

    asyncio.run(scenario())


def test_duplicate_uid_added_once_and_kept():
    store = _store()

    async def scenario():
        events = [_event("u1"), _event("u1")]
        stats = await store.sync_from_apple_calendar(
            "u", events, allow_delete=True, now=datetime.now(TZ)
        )
        assert stats["added"] == 1
        assert stats["deleted"] == 0
        items = await store.list_items("u")
        assert len(items) == 1
        assert items[0].apple_uid == "u1"

    asyncio.run(scenario())


def test_repeated_sync_idempotent():
    store = _store()

    async def scenario():
        events = [_event("u1"), _event("u2")]
        now = datetime.now(TZ)
        await store.sync_from_apple_calendar("u", events, allow_delete=True, now=now)
        stats = await store.sync_from_apple_calendar(
            "u", events, allow_delete=True, now=now
        )
        assert stats == {"added": 0, "updated": 0, "deleted": 0}
        assert len(await store.list_items("u")) == 2

    asyncio.run(scenario())


def test_changed_event_updated():
    store = _store()

    async def scenario():
        now = datetime.now(TZ)
        await store.sync_from_apple_calendar(
            "u", [_event("u1")], allow_delete=True, now=now
        )
        stats = await store.sync_from_apple_calendar(
            "u", [_event("u1", title="改名了")], allow_delete=True, now=now
        )
        assert stats["updated"] == 1
        assert (await store.list_items("u"))[0].title == "改名了"

    asyncio.run(scenario())


def test_missing_from_apple_deleted_only_when_allowed():
    store = _store()

    async def scenario():
        now = datetime.now(TZ)
        await store.add_item("u", ScheduleItem(title="a", apple_uid="gone"))
        await store.add_item("u", ScheduleItem(title="b"))
        stats = await store.sync_from_apple_calendar(
            "u", [_event("keep")], allow_delete=False, now=now
        )
        assert stats["deleted"] == 0
        assert {i.title for i in await store.list_items("u")} == {"a", "b", "事件"}

        stats = await store.sync_from_apple_calendar(
            "u", [_event("keep")], allow_delete=True, now=now
        )
        assert stats["deleted"] == 1
        assert {i.title for i in await store.list_items("u")} == {"b", "事件"}

    asyncio.run(scenario())


def test_events_outside_window_ignored():
    store = _store()

    async def scenario():
        stats = await store.sync_from_apple_calendar(
            "u",
            [_event("old", days=-3), _event("far", days=10)],
            allow_delete=True,
            now=datetime.now(TZ),
        )
        assert stats["added"] == 0
        assert await store.list_items("u") == []

    asyncio.run(scenario())


def test_all_day_and_end_time_format():
    store = _store()

    async def scenario():
        await store.sync_from_apple_calendar(
            "u",
            [_event("day", all_day=True), _event("clock")],
            allow_delete=True,
            now=datetime.now(TZ),
        )
        by_uid = {i.apple_uid: i for i in await store.list_items("u")}
        assert len(by_uid["day"].time) == 10
        assert by_uid["day"].end_time is None
        assert by_uid["clock"].end_time is not None

    asyncio.run(scenario())


def test_event_in_other_offset_converted_to_local_wall_time():
    store = _store()

    async def scenario():
        event = _event("u1", offset="UTC")
        await store.sync_from_apple_calendar(
            "u", [event], allow_delete=True, now=datetime.now(TZ)
        )
        item = (await store.list_items("u"))[0]
        expected = datetime.fromisoformat(event["start"]).astimezone(TZ)
        assert item.time == expected.strftime("%Y-%m-%d %H:%M")

    asyncio.run(scenario())
