"""main.py 日程提醒发送流程测试：防重标记只在发送成功后落盘。

覆盖：发送成功 → last_triggered 写入；发送抛异常 → 不写入（下轮会重试，
提醒不永久丢失）。只构造对象骨架，不启动 AstrBot 运行时。
"""

import asyncio
from datetime import datetime, timedelta

from schedule_assistant.main import ScheduleAssistant
from schedule_assistant.schedule_store import ScheduleItem, ScheduleStore


class _FakeKVPlugin:
    """提供 get_kv_data / put_kv_data 的内存 KV 假插件"""

    def __init__(self):
        self.data = {}

    async def get_kv_data(self, key, default=None):
        return self.data.get(key, default)

    async def put_kv_data(self, key, value):
        self.data[key] = value


class _FakeMessaging:
    """send_to_user 替身：fail="raise" 抛异常，fail="false" 返回 False（真实失败主通道）"""

    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []
        self.attempts = []

    async def send_to_user(self, user_id, text):
        self.attempts.append((user_id, text))
        if self.fail == "raise":
            raise RuntimeError("send boom")
        if self.fail == "false":
            return False
        self.sent.append((user_id, text))
        return True


class _FakeScheduleReminder:
    async def generate_reminder_text(self, **kwargs):
        return f"reminder:{kwargs['item_title']}"


def _plugin(store, messaging):
    """构造 ScheduleAssistant 骨架：绕过 __init__ 只挂扫描所需依赖"""
    plugin = ScheduleAssistant.__new__(ScheduleAssistant)
    plugin.config = {"schedule_reminder_minutes": 10}
    plugin.store = store
    plugin.messaging = messaging
    plugin.llm_service = None
    plugin.schedule_reminder = _FakeScheduleReminder()
    plugin.apple_calendar = None
    plugin._schedule_reminder_last_log_ts = 0.0
    plugin._schedule_reminder_scan_lock = asyncio.Lock()
    plugin._apple_calendar_sync_lock = asyncio.Lock()
    plugin._last_apple_read_issue = None

    async def _noop_ensure_services():
        return None

    async def _targets(include_known_users=False):
        return ["u1"]

    plugin._ensure_services = _noop_ensure_services
    plugin._get_target_user_ids = _targets
    return plugin


def _seed_due(store, user_id="u1"):
    item = ScheduleItem(
        type="schedule",
        title="组会",
        time=(datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M"),
    )
    asyncio.run(store.add_item(user_id, item))
    return item


def _last_triggered(store, user_id="u1"):
    return asyncio.run(store.list_all_items(user_id))[0].last_triggered


def test_successful_send_marks_last_triggered():
    store = ScheduleStore(_FakeKVPlugin())
    _seed_due(store)
    messaging = _FakeMessaging()

    asyncio.run(_plugin(store, messaging)._schedule_reminder_scan())

    assert messaging.sent == [("u1", "reminder:组会")]
    assert _last_triggered(store)

    # 标记落盘后不再重复提醒
    asyncio.run(_plugin(store, messaging)._schedule_reminder_scan())
    assert len(messaging.sent) == 1


def test_failed_send_does_not_mark_last_triggered(caplog):
    """发送抛异常绝不能落防重标记：否则该日程本期乃至永久不再提醒"""
    store = ScheduleStore(_FakeKVPlugin())
    _seed_due(store)

    with caplog.at_level("WARNING"):
        asyncio.run(
            _plugin(store, _FakeMessaging(fail="raise"))._schedule_reminder_scan()
        )

    assert _last_triggered(store) is None
    assert any("日程提醒扫描失败" in r.message for r in caplog.records)

    # 下轮发送正常时仍能提醒（提醒没有丢）
    messaging = _FakeMessaging()
    asyncio.run(_plugin(store, messaging)._schedule_reminder_scan())
    assert messaging.sent == [("u1", "reminder:组会")]
    assert _last_triggered(store)


def test_send_returning_false_does_not_mark_last_triggered(caplog):
    """send_to_user 返回 False 是真实失败主通道（平台不可用/发送被吞），同样不落标记"""
    store = ScheduleStore(_FakeKVPlugin())
    _seed_due(store)
    messaging = _FakeMessaging(fail="false")

    with caplog.at_level("WARNING"):
        asyncio.run(_plugin(store, messaging)._schedule_reminder_scan())

    assert messaging.sent == []  # 未送达
    assert _last_triggered(store) is None
    assert any("提醒未送达" in r.message for r in caplog.records)

    # 下轮仍会尝试发送，并在成功后落标记
    ok = _FakeMessaging()
    asyncio.run(_plugin(store, ok)._schedule_reminder_scan())
    assert ok.sent == [("u1", "reminder:组会")]
    assert _last_triggered(store)


def test_send_returning_none_is_treated_as_delivered(caplog):
    """未声明返回值的自定义 messaging 实现（返回 None）不判为失败，避免反复重发"""
    store = ScheduleStore(_FakeKVPlugin())
    _seed_due(store)

    class _NoneMessaging:
        def __init__(self):
            self.sent = []

        async def send_to_user(self, user_id, text):
            self.sent.append((user_id, text))

    messaging = _NoneMessaging()
    asyncio.run(_plugin(store, messaging)._schedule_reminder_scan())

    assert messaging.sent == [("u1", "reminder:组会")]
    assert _last_triggered(store)


def test_empty_reminder_text_is_not_retried_forever(caplog):
    """文案为空时不发送，但要落防重标记：否则每轮都进 triggered 却永不发，空转"""
    store = ScheduleStore(_FakeKVPlugin())
    _seed_due(store)
    messaging = _FakeMessaging()

    class _EmptyReminder:
        async def generate_reminder_text(self, **kwargs):
            return ""

    plugin = _plugin(store, messaging)
    plugin.schedule_reminder = _EmptyReminder()

    with caplog.at_level("WARNING"):
        asyncio.run(plugin._schedule_reminder_scan())

    assert messaging.attempts == []  # 没有可发内容
    assert _last_triggered(store)  # 但已按"处理过"落标记
    assert any("提醒文案为空" in r.message for r in caplog.records)

    # 第二轮不再触发（防重标记生效，不再空转）
    caplog.clear()
    with caplog.at_level("WARNING"):
        asyncio.run(plugin._schedule_reminder_scan())
    assert [r.message for r in caplog.records if "提醒文案为空" in r.message] == []


def test_two_package_aliases_do_not_share_classes():
    """conftest 的 schedule_assistant 别名与真实包名各自加载一份模块。

    两类之间按 item.id 匹配（ScheduleStore.update_item 只比对 id），
    故插件的包路径与测试的别名路径混用不影响本测试的有效性。
    """
    import astrbot_plugin_schedule_assistant.schedule_store as real_store

    assert real_store.ScheduleItem is not ScheduleItem
    assert real_store.ScheduleStore is not ScheduleStore


class _FakeAppleCalendar:
    """get_all_events 替身：交回 (事件, 问题)"""

    def __init__(self, events, issues):
        self._events = events
        self._issues = issues
        self.calls = 0

    async def get_all_events(self, days=1):
        self.calls += 1
        return list(self._events), list(self._issues)


class _RecordingStore:
    """记录 allow_delete 的同步替身"""

    def __init__(self):
        self.calls = []

    async def sync_from_apple_calendar(self, user_id, apple_events, *, allow_delete):
        self.calls.append(allow_delete)
        return {"added": 0, "updated": 0, "deleted": 0}


def _sync_plugin(apple_calendar):
    store = _RecordingStore()
    plugin = _plugin(store, _FakeMessaging())
    plugin.apple_calendar = apple_calendar
    return plugin, store


def test_clean_read_allows_deletion():
    """读取完整时照旧允许删除，同步行为不变"""
    plugin, store = _sync_plugin(_FakeAppleCalendar([{"uid": "u1"}], []))

    asyncio.run(plugin._apple_calendar_sync())

    assert store.calls == [True]
    assert plugin._last_apple_read_issue is None


def test_incomplete_read_forbids_deletion_and_warns_once(caplog):
    """读取不完整：不允许删除，且同一原因只提示一次（30 分钟一轮不至于刷屏）"""
    issues = ["日程: 抓取日历事件失败（status=403）"]
    plugin, store = _sync_plugin(_FakeAppleCalendar([{"uid": "u1"}], issues))

    with caplog.at_level("WARNING", logger="astrbot"):
        asyncio.run(plugin._apple_calendar_sync())

    assert store.calls == [False]
    assert plugin._last_apple_read_issue == issues[0]
    warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "读取不完整" in warnings[0] and "403" in warnings[0]

    # 第二轮的同一原因不再重复 WARNING，但依然不允许删除
    caplog.clear()
    with caplog.at_level("WARNING", logger="astrbot"):
        asyncio.run(plugin._apple_calendar_sync())

    assert store.calls == [False, False]
    assert [r for r in caplog.records if r.levelname == "WARNING"] == []


def test_clean_read_after_incomplete_round_resets_state():
    """恢复正常后要复位，否则下次真删除时会被旧原因挡住"""
    plugin, store = _sync_plugin(_FakeAppleCalendar([{"uid": "u1"}], ["CalDAV 未连接"]))
    asyncio.run(plugin._apple_calendar_sync())
    assert plugin._last_apple_read_issue == "CalDAV 未连接"

    plugin.apple_calendar = _FakeAppleCalendar([{"uid": "u1"}], [])
    asyncio.run(plugin._apple_calendar_sync())

    assert store.calls == [False, True]
    assert plugin._last_apple_read_issue is None


def test_triggered_dict_shape():
    """triggered 条目结构（main.py 发送依赖这些键）"""
    from schedule_assistant.reminders.schedule import (
        check_and_trigger_schedule_reminder,
    )

    store = ScheduleStore(_FakeKVPlugin())
    item = _seed_due(store)
    triggered = asyncio.run(
        check_and_trigger_schedule_reminder(
            schedule_store=store,
            llm_service=None,
            user_id="u1",
            minutes_before=10,
            reminder=_FakeScheduleReminder(),
        )
    )
    assert [t["item_id"] for t in triggered] == [item.id]
    assert triggered[0]["user_id"] == "u1"
    assert triggered[0]["title"] == "组会"
    assert triggered[0]["reminder_text"] == "reminder:组会"
    assert triggered[0]["type"] == "schedule"
