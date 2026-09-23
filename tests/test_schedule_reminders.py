"""日程提醒扫描与 LLM 提示词标签测试。

覆盖：提前量窗口（含上边界）、窗口外/已开始不触发、防重标记（含改期后重新提醒）、
habit / 全天 / 停用条目跳过、区间时间标签进入 LLM 提示词。
"""

import asyncio
from datetime import datetime, timedelta

from schedule_assistant.reminders import schedule as schedule_module
from schedule_assistant.reminders.schedule import (
    ScheduleReminder,
    check_and_trigger_schedule_reminder,
)
from schedule_assistant.schedule_store import ScheduleItem, ScheduleStore


class _FakeKVPlugin:
    """提供 get_kv_data / put_kv_data 的内存 KV 假插件"""

    def __init__(self):
        self.data = {}

    async def get_kv_data(self, key, default=None):
        return self.data.get(key, default)

    async def put_kv_data(self, key, value):
        self.data[key] = value


class _FakeReminder:
    """记录 generate_reminder_text 入参的假提醒器"""

    def __init__(self):
        self.calls = []

    async def generate_reminder_text(self, **kwargs):
        self.calls.append(kwargs)
        return f"reminder:{kwargs['item_title']}"


class _CaptureLLM:
    def __init__(self):
        self.prompts = []

    async def generate(self, prompt, umo=None, extra_system=None):
        self.prompts.append(prompt)
        return "好的，马上开始啦~"


def _store() -> ScheduleStore:
    return ScheduleStore(_FakeKVPlugin())


def _at(minutes: int) -> str:
    """now+N 分钟的时间串（截断到分钟，断言窗口留了余量）"""
    return (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")


def _add(store, user_id="u", **kw):
    item = ScheduleItem(
        type=kw.pop("type", "schedule"),
        title=kw.pop("title", "测试日程"),
        time=kw.pop("time", _at(5)),
        **kw,
    )
    asyncio.run(store.add_item(user_id, item))
    return item


def _scan(store, minutes_before=10, reminder=None, user_id="u"):
    return asyncio.run(
        check_and_trigger_schedule_reminder(
            schedule_store=store,
            llm_service=None,
            user_id=user_id,
            minutes_before=minutes_before,
            reminder=reminder or _FakeReminder(),
        )
    )


class TestScanWindow:
    def test_within_window_due_then_dedup(self):
        store = _store()
        item = _add(store, time=_at(5))

        triggered = _scan(store, 10)
        assert len(triggered) == 1
        assert triggered[0]["item_id"] == item.id
        assert triggered[0]["reminder_text"] == "reminder:测试日程"
        assert 3 <= triggered[0]["minutes_until"] <= 5

        # 防重：同一事件第二次扫描不再触发
        assert _scan(store, 10) == []

    def test_last_triggered_persisted(self):
        store = _store()
        _add(store, time=_at(5))
        _scan(store, 10)
        assert asyncio.run(store.list_all_items("u"))[0].last_triggered

    def test_boundary_exact_and_one_second_over(self, monkeypatch):
        """精确边界：剩余 == minutes_before 触发，超出一秒不触发"""
        fixed = datetime(2026, 9, 25, 12, 0, 0)

        class _FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed

        monkeypatch.setattr(schedule_module, "datetime", _FrozenDatetime)

        store_exact = _store()
        _add(store_exact, title="刚好", time="2026-09-25 12:10")
        assert len(_scan(store_exact, 10)) == 1

        store_over = _store()
        _add(store_over, title="差一秒", time="2026-09-25T12:10:01")
        assert _scan(store_over, 10) == []

    def test_outside_window_not_due(self):
        store = _store()
        _add(store, time=_at(30))
        assert _scan(store, 10) == []

    def test_already_started_not_due(self):
        store = _store()
        _add(store, time=_at(-5))
        assert _scan(store, 10) == []

    def test_habit_all_day_disabled_skipped(self):
        store = _store()
        _add(store, type="habit", title="喝水", time=_at(5))
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        _add(store, title="全天事项", time=tomorrow, all_day=True)
        _add(store, title="停用日程", time=_at(6), enabled=False)
        assert _scan(store, 10) == []

    def test_reschedule_triggers_again(self):
        """改期重置防重标记后，新时间重新提醒"""
        store = _store()
        _add(store, time=_at(5))
        assert len(_scan(store, 10)) == 1

        revived = asyncio.run(store.list_all_items("u"))[0]
        revived.last_triggered = None
        revived.time = _at(6)
        asyncio.run(store.update_item("u", revived))

        assert len(_scan(store, 10)) == 1

    def test_end_time_passed_to_reminder(self):
        store = _store()
        item = _add(store, time=_at(10), end_time=_at(70))
        reminder = _FakeReminder()
        _scan(store, 10, reminder)
        assert reminder.calls[0]["item_end_time"] == item.end_time


class TestScheduleReminderPrompt:
    def test_time_label_range(self):
        reminder = ScheduleReminder(None)
        assert (
            reminder._format_time_label("2026-09-10 14:30", "2026-09-10 16:30")
            == "14:30-16:30"
        )
        assert reminder._format_time_label("2026-09-10 14:30") == "14:30"
        assert reminder._format_time_label("bad-format") == "bad-format"

    def test_prompt_contains_range_and_history(self):
        llm = _CaptureLLM()
        reminder = ScheduleReminder(llm, {})

        text = asyncio.run(
            reminder.generate_reminder_text(
                item_title="组会",
                item_time="2026-09-10 14:30",
                item_context="带电脑",
                minutes_ahead=8,
                conv_history="用户: 下午有会",
                item_end_time="2026-09-10 16:30",
            )
        )
        assert text == "好的，马上开始啦~"

        prompt = llm.prompts[0]
        assert "组会" in prompt
        assert "14:30-16:30" in prompt
        assert "带电脑" in prompt
        assert "用户: 下午有会" in prompt

    def test_llm_failure_falls_back(self):
        class _BrokenLLM:
            async def generate(self, prompt, umo=None, extra_system=None):
                raise RuntimeError("boom")

        reminder = ScheduleReminder(_BrokenLLM(), {})
        text = asyncio.run(
            reminder.generate_reminder_text(
                item_title="组会", item_time="2026-09-10 14:30", item_context=""
            )
        )
        assert "组会" in text and "即将开始" in text
