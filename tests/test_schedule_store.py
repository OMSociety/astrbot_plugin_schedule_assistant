"""ScheduleStore 测试：Apple 日历同步去重、对话历史截断口径。

plugin 的 KV API 用内存字典假对象替代，不依赖真实框架存储。
"""

import asyncio
from datetime import datetime, timedelta

from schedule_assistant.constants import SCHEDULES_KEY
from schedule_assistant.schedule_store import ScheduleItem, ScheduleStore


class _FakeKVPlugin:
    """提供 get_kv_data / put_kv_data 的内存 KV 假插件"""

    def __init__(self):
        self.data = {}

    async def get_kv_data(self, key, default=None):
        return self.data.get(key, default)

    async def put_kv_data(self, key, value):
        self.data[key] = value


def _store() -> ScheduleStore:
    return ScheduleStore(_FakeKVPlugin())


def _evt(uid, title="事件", start=None, end=None, all_day=False):
    evt = {
        "uid": uid,
        "summary": title,
        "start": start
        or (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if end:
        evt["end"] = end
    if all_day:
        evt["all_day"] = True
    return evt


class TestSyncFromAppleCalendar:
    """Apple 日历同步：重复 UID 去重且不误删、空列表防御、窗口过滤"""

    def test_empty_events_no_deletion(self):
        """空事件列表（可能为同步失败）不触发删除"""
        store = _store()
        item = ScheduleItem(
            type="schedule", title="已有", time="2026-09-10 10:00", apple_uid="u1"
        )
        asyncio.run(store.add_item("u", item))
        stats = asyncio.run(store.sync_from_apple_calendar("u", []))
        assert stats == {"added": 0, "updated": 0, "deleted": 0}
        assert len(asyncio.run(store.list_all_items("u"))) == 1

    def test_duplicate_uid_added_once_and_kept(self):
        """Apple 返回重复 RRULE 实例：同一 UID 只添加一次，且不因重复被误删"""
        store = _store()
        events = [_evt("u1"), _evt("u1")]
        stats = asyncio.run(store.sync_from_apple_calendar("u", events))
        assert stats["added"] == 1
        assert stats["deleted"] == 0
        items = asyncio.run(store.list_all_items("u"))
        assert len(items) == 1
        assert items[0].apple_uid == "u1"

    def test_repeated_sync_idempotent(self):
        """同一批事件同步两次：第二次无新增、无更新、无删除"""
        store = _store()
        events = [_evt("u1"), _evt("u2")]
        asyncio.run(store.sync_from_apple_calendar("u", events))
        stats = asyncio.run(store.sync_from_apple_calendar("u", events))
        assert stats == {"added": 0, "updated": 0, "deleted": 0}
        assert len(asyncio.run(store.list_all_items("u"))) == 2

    def test_changed_event_updated(self):
        store = _store()
        asyncio.run(store.sync_from_apple_calendar("u", [_evt("u1")]))
        stats = asyncio.run(
            store.sync_from_apple_calendar("u", [_evt("u1", title="改名了")])
        )
        assert stats["updated"] == 1
        assert asyncio.run(store.list_all_items("u"))[0].title == "改名了"

    def test_missing_from_apple_deleted(self):
        """本地有 apple_uid 而本次同步没有的事件应删除；无 apple_uid 的不动"""
        store = _store()
        asyncio.run(store.add_item("u", ScheduleItem(title="a", apple_uid="gone")))
        asyncio.run(store.add_item("u", ScheduleItem(title="b")))
        stats = asyncio.run(store.sync_from_apple_calendar("u", [_evt("keep")]))
        assert stats["deleted"] == 1
        titles = {i.title for i in asyncio.run(store.list_all_items("u"))}
        assert titles == {"b", "事件"}

    def test_far_future_event_skipped(self):
        """超过 7 天窗口的远期事件不入库"""
        store = _store()
        far = _evt("u1", start=(datetime.now() + timedelta(days=30)).isoformat())
        stats = asyncio.run(store.sync_from_apple_calendar("u", [far]))
        assert stats["added"] == 0
        assert asyncio.run(store.list_all_items("u")) == []

    def test_stale_event_skipped(self):
        """比 1 天前更早的过期事件不入库"""
        store = _store()
        stale = _evt("u1", start=(datetime.now() - timedelta(days=3)).isoformat())
        stats = asyncio.run(store.sync_from_apple_calendar("u", [stale]))
        assert stats["added"] == 0


class TestSyncEndTimeAndReschedule:
    """区间 / 全天同步与改期防重重置"""

    def test_item_roundtrip_with_end_time(self):
        item = ScheduleItem(
            type="schedule",
            title="组会",
            time="2026-09-10 19:00",
            end_time="2026-09-10 21:00",
        )
        revived = ScheduleItem.from_dict(item.to_dict())
        assert revived == item
        assert revived.end_time == "2026-09-10 21:00"

    def test_end_time_stored(self):
        store = _store()
        start = (datetime.now() + timedelta(days=2)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        end = start + timedelta(hours=1, minutes=30)
        asyncio.run(
            store.sync_from_apple_calendar(
                "u", [_evt("u1", start=start.isoformat(), end=end.isoformat())]
            )
        )
        item = asyncio.run(store.list_all_items("u"))[0]
        assert item.end_time == end.strftime("%Y-%m-%d %H:%M")

    def test_all_day_stored_as_date_only(self):
        """全天事件 time 存 date-only（与全天判定口径对齐）"""
        store = _store()
        day = datetime.now() + timedelta(days=2)
        asyncio.run(
            store.sync_from_apple_calendar(
                "u",
                [
                    _evt(
                        "u1",
                        start=day.strftime("%Y-%m-%dT00:00:00"),
                        end=(day + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00"),
                        all_day=True,
                    )
                ],
            )
        )
        item = asyncio.run(store.list_all_items("u"))[0]
        assert item.all_day is True
        assert item.time == day.strftime("%Y-%m-%d")
        assert item.end_time is None

    def test_reschedule_resets_last_triggered(self):
        store = _store()
        asyncio.run(store.sync_from_apple_calendar("u", [_evt("u1")]))
        item = asyncio.run(store.list_all_items("u"))[0]
        item.last_triggered = datetime.now().isoformat()
        asyncio.run(store.update_item("u", item))

        new_start = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%dT10:00:00")
        stats = asyncio.run(
            store.sync_from_apple_calendar("u", [_evt("u1", start=new_start)])
        )
        assert stats["updated"] == 1
        assert asyncio.run(store.list_all_items("u"))[0].last_triggered is None

    def test_title_change_keeps_last_triggered(self):
        store = _store()
        asyncio.run(store.sync_from_apple_calendar("u", [_evt("u1")]))
        item = asyncio.run(store.list_all_items("u"))[0]
        item.last_triggered = datetime.now().isoformat()
        asyncio.run(store.update_item("u", item))

        stats = asyncio.run(
            store.sync_from_apple_calendar("u", [_evt("u1", title="改名了")])
        )
        assert stats["updated"] == 1
        assert asyncio.run(store.list_all_items("u"))[0].last_triggered is not None

    def test_legacy_item_without_end_time_not_treated_as_reschedule(self):
        """旧数据无 end_time 键时首轮补齐不算改期（避免升级后重复提醒）"""
        store = _store()
        start = (datetime.now() + timedelta(days=2)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        asyncio.run(
            store.add_item(
                "u",
                ScheduleItem(
                    type="schedule",
                    title="事件",
                    time=start.strftime("%Y-%m-%d %H:%M"),
                    apple_uid="u1",
                    last_triggered="2026-09-23T10:00:00",
                ),
            )
        )

        async def strip_end_time():
            data = await store._load_user_data("u")
            for s in data[SCHEDULES_KEY]:
                s.pop("end_time", None)
            await store._save_user_data("u", data)

        asyncio.run(strip_end_time())

        end = start + timedelta(hours=2)
        stats = asyncio.run(
            store.sync_from_apple_calendar(
                "u", [_evt("u1", start=start.isoformat(), end=end.isoformat())]
            )
        )
        assert stats["updated"] == 1
        revived = asyncio.run(store.list_all_items("u"))[0]
        assert revived.end_time == end.strftime("%Y-%m-%d %H:%M")
        assert revived.last_triggered == "2026-09-23T10:00:00"

    def test_unchanged_sync_skips_save(self):
        """无变化的同步不写盘（扫描前每轮都会刷新同步）"""
        store = _store()
        asyncio.run(store.sync_from_apple_calendar("u", [_evt("u1")]))

        saves = []
        orig = store._save_user_data

        async def counting(user_id, data):
            saves.append(user_id)
            return await orig(user_id, data)

        store._save_user_data = counting
        stats = asyncio.run(store.sync_from_apple_calendar("u", [_evt("u1")]))
        assert stats == {"added": 0, "updated": 0, "deleted": 0}
        assert saves == []

    def test_duplicate_uid_out_of_window_not_resurrected(self):
        """窗口外事件（含重复实例）不保留成员资格 → 本地对应条目被删除"""
        store = _store()
        asyncio.run(
            store.add_item(
                "u",
                ScheduleItem(
                    type="schedule",
                    title="旧事件",
                    time="2026-09-10 10:00",
                    apple_uid="u1",
                ),
            )
        )
        far = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
        stats = asyncio.run(
            store.sync_from_apple_calendar(
                "u", [_evt("u1", start=far), _evt("u1", start=far)]
            )
        )
        assert stats["deleted"] == 1
        assert asyncio.run(store.list_all_items("u")) == []


class TestFormatHistoryForPrompt:
    """对话历史格式化：新口径按字符预算截断（1 字符 ≈ 1.5 token 假设下的保守口径）"""

    @staticmethod
    def _msg(role, content, minutes_ago=0):
        ts = datetime.now() - timedelta(minutes=minutes_ago)
        return {"role": role, "content": content, "timestamp": ts.isoformat()}

    def test_empty_history(self):
        store = _store()
        assert store.format_history_for_prompt([]) == "（无近期对话历史）"

    def test_role_labels(self):
        store = _store()
        history = [self._msg("user", "你好"), self._msg("assistant", "早上好呀")]
        out = store.format_history_for_prompt(history)
        assert "用户: 你好" in out
        assert "芙兰: 早上好呀" in out

    def test_newest_last(self):
        """历史按时间正序排（最旧在前、最新在后，贴合对话语感）"""
        store = _store()
        history = [
            self._msg("user", "第一条", minutes_ago=10),
            self._msg("user", "第二条", minutes_ago=1),
        ]
        lines = store.format_history_for_prompt(history).split("\n")
        assert "第一条" in lines[0]
        assert "第二条" in lines[-1]

    def test_budget_trims_oldest(self):
        """超出字符预算时从最旧开始丢弃，保留的都是最近的消息"""
        store = _store()
        history = [
            self._msg("user", "A" * 50, minutes_ago=50),
            self._msg("user", "B" * 50, minutes_ago=40),
            self._msg("user", "C" * 30, minutes_ago=1),
        ]
        max_tokens = 80
        out = store.format_history_for_prompt(history, max_tokens=max_tokens)
        assert "C" in out
        assert "A" not in out
        assert len(out) <= max_tokens

    def test_first_line_over_budget_fallback(self):
        """所有行都放不下时回退到（无近期对话历史）"""
        store = _store()
        history = [self._msg("user", "A" * 200)]
        assert (
            store.format_history_for_prompt(history, max_tokens=10)
            == "（无近期对话历史）"
        )
