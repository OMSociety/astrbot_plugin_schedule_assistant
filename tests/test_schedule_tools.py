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
    """记录 create_event 调用参数的 Apple 日历替身"""

    def __init__(self):
        self.calls = []

    async def create_event(
        self, summary, start, end=None, calendar_id=None, description="", all_day=False
    ):
        self.calls.append(
            {"summary": summary, "start": start, "end": end, "all_day": all_day}
        )
        return "uid-1"


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


def _update_tool(store):
    tool = UpdateScheduleTool()
    tool.inject_store(store, None)
    return tool


def _list_tool(store):
    tool = ListSchedulesTool()
    tool.inject_store(store, None)
    return tool


def _delete_tool(store):
    tool = DeleteScheduleTool()
    tool.inject_store(store, None)
    tool.inject_plugin(_plugin(None))
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
        assert "已同步到 Apple 日历" in res
        assert apple.calls == [
            {
                "summary": "组会",
                "start": datetime(2026, 9, 10, 9, 0),
                "end": datetime(2026, 9, 10, 11, 0),
                "all_day": False,
            }
        ]
        # 回写 UID：否则下一轮同步会把它当新事件再入库一份（播报出现两行）
        assert _items(store)[0].apple_uid == "uid-1"

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
