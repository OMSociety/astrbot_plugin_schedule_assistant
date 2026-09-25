"""日程工具测试：创建 / 修改 / 查看的时间形态、错误分支与 Apple 写入参数。"""

import asyncio
import types
from datetime import datetime, timedelta

from schedule_assistant.schedule_store import ScheduleItem, ScheduleStore
from schedule_assistant.tools.schedule_tools import (
    CreateScheduleTool,
    DeleteScheduleTool,
    ListSchedulesTool,
    UpdateScheduleTool,
)


class _FakeKVPlugin:
    """提供 get_kv_data / put_kv_data 的内存 KV 假插件"""

    def __init__(self):
        self.data = {}

    async def get_kv_data(self, key, default=None):
        return self.data.get(key, default)

    async def put_kv_data(self, key, value):
        self.data[key] = value


class _FakeApple:
    """记录 create_event 调用参数的 Apple 日历替身（返回可配置的 uid）"""

    def __init__(self, uid="uid-1"):
        self.calls = []
        self.uid = uid

    async def create_event(
        self,
        summary,
        start,
        end=None,
        calendar_id=None,
        description="",
        all_day=False,
        uid=None,
    ):
        self.calls.append(
            {
                "summary": summary,
                "start": start,
                "end": end,
                "all_day": all_day,
                "uid": uid,
            }
        )
        return self.uid


class _FakeDeleteApple:
    """记录 delete_event 调用参数、返回可配置结果的 Apple 日历替身"""

    def __init__(self, events=None, delete_ok=True):
        self.events = events if events is not None else []
        self.delete_ok = delete_ok
        self.deleted = []

    async def find_events_by_summary(self, summary):
        return self.events

    async def delete_event(self, uid, calendar_id=None):
        self.deleted.append((uid, calendar_id))
        return self.delete_ok


def _store() -> ScheduleStore:
    return ScheduleStore(_FakeKVPlugin())


def _ctx(user_id="u1"):
    event = types.SimpleNamespace(get_sender_id=lambda: user_id)
    return types.SimpleNamespace(context=types.SimpleNamespace(event=event))


def _plugin(apple=None):
    return types.SimpleNamespace(
        config={"enable_apple_calendar_sync": apple is not None},
        apple_calendar=apple,
    )


def _create_tool(store, apple=None):
    tool = CreateScheduleTool()
    tool.inject_store(store, None)
    tool.inject_plugin(_plugin(apple))
    return tool


def _update_tool(store, apple=None):
    tool = UpdateScheduleTool()
    tool.inject_store(store, None)
    if apple is not None:
        tool.inject_plugin(_plugin(apple))
    return tool


def _list_tool(store):
    tool = ListSchedulesTool()
    tool.inject_store(store, None)
    return tool


def _delete_tool(store, apple=None):
    tool = DeleteScheduleTool()
    tool.inject_store(store, None)
    tool.inject_plugin(_plugin(apple))
    return tool


def _items(store, user_id="u1"):
    return asyncio.run(store.list_all_items(user_id))


class TestCreateScheduleTool:
    def test_point_mode(self):
        store = _store()
        res = asyncio.run(
            _create_tool(store).call(
                _ctx(),
                title="开会",
                datetime_str="2026-09-10 14:30",
                description="讨论",
            )
        )
        assert "✅" in res
        assert "09-10 14:30" in res

        item = _items(store)[0]
        assert item.time == "2026-09-10 14:30"
        assert item.end_time is None
        assert item.all_day is False
        assert item.context == "讨论"

    def test_range_via_end_param(self):
        store = _store()
        res = asyncio.run(
            _create_tool(store).call(
                _ctx(),
                title="组会",
                datetime_str="2026-09-10 09:00",
                end_datetime_str="11:00",
            )
        )
        assert "09:00-11:00" in res

        item = _items(store)[0]
        assert item.end_time == "2026-09-10 11:00"
        assert item.all_day is False

    def test_range_inline(self):
        store = _store()
        asyncio.run(
            _create_tool(store).call(
                _ctx(), title="组会", datetime_str="2026-09-10 09:00到11:00"
            )
        )
        item = _items(store)[0]
        assert item.time == "2026-09-10 09:00"
        assert item.end_time == "2026-09-10 11:00"

    def test_all_day_bare_date(self):
        store = _store()
        res = asyncio.run(
            _create_tool(store).call(
                _ctx(), title="全天事项", datetime_str="2026-09-10"
            )
        )
        assert "全天" in res

        item = _items(store)[0]
        assert item.time == "2026-09-10"
        assert item.all_day is True
        assert item.end_time is None

    def test_date_only_range_is_all_day(self):
        store = _store()
        res = asyncio.run(
            _create_tool(store).call(
                _ctx(), title="团建", datetime_str="2026-09-10到2026-09-12"
            )
        )
        assert "全天" in res

        item = _items(store)[0]
        assert item.time == "2026-09-10"
        assert item.all_day is True
        assert item.end_time is None

    def test_equal_end_rejected(self):
        store = _store()
        res = asyncio.run(
            _create_tool(store).call(
                _ctx(), title="X", datetime_str="2026-09-10 9点到9点"
            )
        )
        assert res == "结束时间需要晚于开始时间"
        assert _items(store) == []

    def test_end_before_start_rejected(self):
        store = _store()
        res = asyncio.run(
            _create_tool(store).call(
                _ctx(),
                title="X",
                datetime_str="2026-09-10 11:00",
                end_datetime_str="2026-09-10 09:00",
            )
        )
        assert res == "结束时间需要晚于开始时间"
        assert _items(store) == []

    def test_missing_title_or_time(self):
        store = _store()
        tool = _create_tool(store)
        assert asyncio.run(tool.call(_ctx(), title="", datetime_str="明天9点")) == (
            "请提供日程标题和时间"
        )
        assert asyncio.run(tool.call(_ctx(), title="开会", datetime_str="")) == (
            "请提供日程标题和时间"
        )

    def test_explicit_null_params_return_friendly_hint(self):
        """LLM 显式传 null（schema 标了 nullable）时给友好提示，不抛 AttributeError"""
        store = _store()
        tool = _create_tool(store)
        assert asyncio.run(tool.call(_ctx(), title=None, datetime_str="明天9点")) == (
            "请提供日程标题和时间"
        )
        assert asyncio.run(tool.call(_ctx(), title="开会", datetime_str=None)) == (
            "请提供日程标题和时间"
        )
        assert asyncio.run(
            tool.call(
                _ctx(), title="开会", datetime_str="2026-09-10 09:00", description=None
            )
        ).endswith("✅")
        assert _items(store)[0].context == ""

    def test_unparsable_time(self):
        store = _store()
        res = asyncio.run(
            _create_tool(store).call(_ctx(), title="开会", datetime_str="随便说说")
        )
        assert res.startswith("时间格式无法解析")

    def test_apple_write_params(self):
        apple = _FakeApple()
        store = _store()
        res = asyncio.run(
            _create_tool(store, apple=apple).call(
                _ctx(), title="组会", datetime_str="2026-09-10 09:00到11:00"
            )
        )
        # 整句精确断言：Apple 写入成功分支的文案口径固定
        assert (
            res == "已创建日程「组会」，时间：09-10 09:00-11:00 ✅，已同步到 Apple 日历"
        )
        assert apple.calls == [
            {
                "summary": "组会",
                "start": datetime(2026, 9, 10, 9, 0),
                "end": datetime(2026, 9, 10, 11, 0),
                "all_day": False,
                "uid": None,
            }
        ]
        # 回写 UID：否则下一轮同步会把它当新事件再入库一份（播报出现两行）
        assert _items(store)[0].apple_uid == "uid-1"

    def test_apple_write_failure_has_no_sync_claim(self):
        """create_event 返回 None（如 401/403）时不得回"已同步"文案

        失败文案与成功文案必须互斥：否则用户看到"已同步"，本地却带着假 UID
        被下轮同步静默删除。
        """
        apple = _FakeApple(uid=None)
        store = _store()
        res = asyncio.run(
            _create_tool(store, apple=apple).call(
                _ctx(), title="组会", datetime_str="2026-09-10 09:00到11:00"
            )
        )
        assert res == "已创建日程「组会」，时间：09-10 09:00-11:00 ✅"
        assert "已同步到 Apple 日历" not in res
        # 本地日程照常入库，但不带假 UID（否则下轮同步按 UID 差集删除它）
        assert _items(store)[0].apple_uid is None

    def test_apple_all_day_param(self):
        apple = _FakeApple()
        store = _store()
        asyncio.run(
            _create_tool(store, apple=apple).call(
                _ctx(), title="全天", datetime_str="2026-09-10"
            )
        )
        assert apple.calls[0]["all_day"] is True
        assert apple.calls[0]["end"] is None

    def test_all_day_ignores_end_param(self):
        store = _store()
        asyncio.run(
            _create_tool(store).call(
                _ctx(),
                title="全天事项",
                datetime_str="2026-09-10 全天",
                end_datetime_str="11点",
            )
        )
        item = _items(store)[0]
        assert item.all_day is True
        assert item.time == "2026-09-10"
        assert item.end_time is None

    def test_apple_sync_does_not_duplicate_tool_created_item(self):
        """回写 UID 后，下一轮 Apple 同步更新原条目而非再入库一份（播报不再两行）"""
        apple = _FakeApple()
        store = _store()
        day = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        asyncio.run(
            _create_tool(store, apple=apple).call(
                _ctx(), title="组会", datetime_str=f"{day} 09:00"
            )
        )
        assert len(_items(store)) == 1

        start = apple.calls[0]["start"]
        end = start + timedelta(hours=1)
        stats = asyncio.run(
            store.sync_from_apple_calendar(
                "u1",
                [
                    {
                        "uid": "uid-1",
                        "summary": "组会",
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                    }
                ],
            )
        )

        items = _items(store)
        assert len(items) == 1
        assert stats["added"] == 0
        assert stats["updated"] == 1
        assert items[0].end_time == end.strftime("%Y-%m-%d %H:%M")


class TestUpdateScheduleTool:
    def _seed(self, store, **kw):
        item = ScheduleItem(
            type="schedule",
            title=kw.pop("title", "组会"),
            time=kw.pop("time", "2026-09-10 14:30"),
            **kw,
        )
        asyncio.run(store.add_item("u1", item))
        return item

    def test_end_only_requires_start(self):
        store = _store()
        item = self._seed(store)
        res = asyncio.run(
            _update_tool(store).call(
                _ctx(), schedule_id=item.id, new_end_datetime="11点"
            )
        )
        assert res == "请一并提供开始时间，或直接用「9点到11点」的区间写法"

    def test_range_update_resets_dedup(self):
        store = _store()
        item = self._seed(store, last_triggered=datetime.now().isoformat())

        res = asyncio.run(
            _update_tool(store).call(
                _ctx(), schedule_id=item.id, new_datetime="2026-09-11 09:00到11:00"
            )
        )
        assert "✅" in res

        revived = _items(store)[0]
        assert revived.time == "2026-09-11 09:00"
        assert revived.end_time == "2026-09-11 11:00"
        assert revived.last_triggered is None

    def test_title_only_keeps_dedup(self):
        store = _store()
        item = self._seed(store, last_triggered="2026-09-23T10:00:00")

        asyncio.run(
            _update_tool(store).call(_ctx(), schedule_id=item.id, new_title="新标题")
        )
        revived = _items(store)[0]
        assert revived.title == "新标题"
        assert revived.last_triggered == "2026-09-23T10:00:00"

    def test_update_to_all_day(self):
        store = _store()
        item = self._seed(store)

        asyncio.run(
            _update_tool(store).call(
                _ctx(), schedule_id=item.id, new_datetime="2026-09-13"
            )
        )
        revived = _items(store)[0]
        assert revived.time == "2026-09-13"
        assert revived.all_day is True
        assert revived.end_time is None

    def test_end_before_start_rejected(self):
        store = _store()
        item = self._seed(store)

        res = asyncio.run(
            _update_tool(store).call(
                _ctx(),
                schedule_id=item.id,
                new_datetime="2026-09-10 11:00",
                new_end_datetime="2026-09-10 09:00",
            )
        )
        assert res == "结束时间需要晚于开始时间"

    def test_no_matches(self):
        store = _store()
        res = asyncio.run(
            _update_tool(store).call(_ctx(), schedule_id="nope", new_title="x")
        )
        assert res == "没有找到匹配的日程"

    def test_multi_match_display(self):
        store = _store()
        self._seed(store, title="组会", time="2026-09-10 14:30")
        self._seed(store, title="周会", time="2026-09-11", all_day=True)

        res = asyncio.run(
            _update_tool(store).call(_ctx(), title_keyword="会", new_title="新标题")
        )
        assert "找到多个匹配日程" in res
        assert "⏰ 09-10 14:30" in res  # 带日期：同名不同日期的日程可区分
        assert "📅 09-11 全天" in res


class TestUpdateScheduleAppleWriteBack:
    """改期要写回 Apple：否则下轮同步用 Apple 旧值反写，用户的修改被静默还原"""

    def _seed(self, store, **kw):
        item = ScheduleItem(
            type="schedule",
            title=kw.pop("title", "组会"),
            time=kw.pop("time", "2026-09-10 14:30"),
            **kw,
        )
        asyncio.run(store.add_item("u1", item))
        return item

    def test_update_writes_back_with_same_uid(self):
        store = _store()
        apple = _FakeApple(uid="uid-existing")
        item = self._seed(store, apple_uid="uid-existing")

        res = asyncio.run(
            _update_tool(store, apple=apple).call(
                _ctx(), schedule_id=item.id, new_datetime="2026-09-11 09:00"
            )
        )
        assert "✅" in res
        assert len(apple.calls) == 1
        # 同一 UID 的 PUT = CalDAV 更新，不生成新 UID
        assert apple.calls[0]["uid"] == "uid-existing"
        assert apple.calls[0]["summary"] == "组会"
        assert apple.calls[0]["start"] == datetime(2026, 9, 11, 9, 0)
        assert _items(store)[0].apple_uid == "uid-existing"

    def test_update_without_apple_uid_skips_write_back(self):
        store = _store()
        apple = _FakeApple()
        item = self._seed(store)

        asyncio.run(
            _update_tool(store, apple=apple).call(
                _ctx(), schedule_id=item.id, new_datetime="2026-09-11 09:00"
            )
        )
        assert apple.calls == []

    def test_write_back_failure_unlinks_apple_uid(self):
        """写回失败时清空 apple_uid：否则下轮同步会把本地改动覆盖回旧值"""
        store = _store()
        apple = _FakeApple(uid=None)
        # 用相对日期：同步只处理未来 7 天内的 Apple 事件
        old_dt = datetime.now() + timedelta(days=2)
        new_dt = old_dt + timedelta(hours=3)
        item = self._seed(
            store,
            time=old_dt.strftime("%Y-%m-%d %H:%M"),
            apple_uid="uid-existing",
        )

        res = asyncio.run(
            _update_tool(store, apple=apple).call(
                _ctx(),
                schedule_id=item.id,
                new_datetime=new_dt.strftime("%Y-%m-%d %H:%M"),
            )
        )
        assert "✅" in res  # 本地改动已生效，不因此谎报失败

        revived = _items(store)[0]
        assert revived.apple_uid is None
        assert revived.time == new_dt.strftime("%Y-%m-%d %H:%M")

        # 脱离 Apple 关联后，同步不会再用 Apple 旧值反写本地
        stats = asyncio.run(
            store.sync_from_apple_calendar(
                "u1",
                [
                    {
                        "uid": "uid-existing",
                        "summary": "组会",
                        "start": old_dt.isoformat(),
                    }
                ],
            )
        )
        assert stats["added"] == 1
        unlinked = next(s for s in _items(store) if s.id == item.id)
        assert unlinked.time == new_dt.strftime("%Y-%m-%d %H:%M")


class TestListSchedulesTool:
    def test_all_day_range_point_shown(self):
        store = _store()
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        asyncio.run(
            store.add_item(
                "u1",
                ScheduleItem(
                    type="schedule", title="全天事项", time=tomorrow, all_day=True
                ),
            )
        )
        asyncio.run(
            store.add_item(
                "u1",
                ScheduleItem(
                    type="schedule",
                    title="组会",
                    time=f"{tomorrow} 10:00",
                    end_time=f"{tomorrow} 11:30",
                ),
            )
        )
        asyncio.run(
            store.add_item(
                "u1",
                ScheduleItem(type="schedule", title="开会", time=f"{tomorrow} 09:00"),
            )
        )

        res = asyncio.run(_list_tool(store).call(_ctx(), days=7))
        assert "📅 全天 │ 全天事项" in res  # 全天（date-only）不再被静默跳过
        assert "⏰ 10:00-11:30 │ 组会" in res
        assert "⏰ 09:00 │ 开会" in res

    def test_empty(self):
        store = _store()
        assert "没有日程安排" in asyncio.run(_list_tool(store).call(_ctx(), days=7))

    def test_explicit_null_days_falls_back_to_default(self):
        """days=null（schema 标了 nullable）走默认 7 天，不是 timedelta(None) 崩溃"""
        store = _store()
        assert asyncio.run(_list_tool(store).call(_ctx(), days=None)) == (
            "最近7天没有日程安排~"
        )

    def test_days_as_numeric_string(self):
        store = _store()
        assert asyncio.run(_list_tool(store).call(_ctx(), days="3")) == (
            "最近3天没有日程安排~"
        )

    def test_days_unparsable_falls_back_to_default(self):
        store = _store()
        assert asyncio.run(_list_tool(store).call(_ctx(), days="三天")) == (
            "最近7天没有日程安排~"
        )


class TestDeleteScheduleTool:
    def test_multi_match_display(self):
        store = _store()
        asyncio.run(
            store.add_item(
                "u1",
                ScheduleItem(type="schedule", title="组会", time="2026-09-10 14:30"),
            )
        )
        asyncio.run(
            store.add_item(
                "u1",
                ScheduleItem(
                    type="schedule", title="周会", time="2026-09-11", all_day=True
                ),
            )
        )

        res = asyncio.run(_delete_tool(store).call(_ctx(), title_keyword="会"))
        assert "找到多个匹配日程" in res
        assert "⏰ 09-10 14:30" in res  # 带日期：同名不同日期的日程可区分
        assert "📅 09-11 全天" in res

    def test_explicit_null_params_return_friendly_hint(self):
        store = _store()
        tool = _delete_tool(store)
        assert asyncio.run(tool.call(_ctx(), schedule_id=None, title_keyword=None)) == (
            "请提供日程ID或标题关键词"
        )

    def test_apple_delete_failure_does_not_claim_success(self, caplog):
        """Apple 侧删失败要留下告警：下轮同步会把该日程按 UID 拉回本地"""
        store = _store()
        asyncio.run(
            store.add_item(
                "u1",
                ScheduleItem(type="schedule", title="组会", time="2026-09-10 14:30"),
            )
        )
        apple = _FakeDeleteApple(
            events=[({"uid": "uid-1", "summary": "组会"}, "cal-1")], delete_ok=False
        )

        with caplog.at_level("WARNING"):
            res = asyncio.run(
                _delete_tool(store, apple=apple).call(_ctx(), title_keyword="组会")
            )

        assert apple.deleted == [("uid-1", "cal-1")]
        # 本地删除已完成，用户侧文案不变；但必须留下可排查告警
        assert "已删除日程" in res
        assert any("删除未成功" in r.message for r in caplog.records)
