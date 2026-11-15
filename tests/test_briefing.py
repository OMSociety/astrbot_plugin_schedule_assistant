"""早安播报数据组装测试。"""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from schedule_assistant.briefing import MorningBriefing
from schedule_assistant.schedule_store import ScheduleItem
from schedule_assistant.settings import Settings

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 10, 9, 0, tzinfo=TZ)


class FakeStore:
    def __init__(self, items):
        self.items = items

    async def list_items(self, umo):
        return list(self.items)


class FakeWeather:
    async def fetch(self):
        return "晴", "-1~9℃"


class FakeNotion:
    def __init__(self, tasks):
        self.tasks = tasks

    async def get_pending_transactions(self):
        return self.tasks


class FakeApple:
    def __init__(self, events):
        self.events = events

    async def get_all_events(self, days=1):
        return self.events, []


def test_build_merges_local_apple_and_notion():
    store = FakeStore([ScheduleItem(title="组会", time="2026-09-10", all_day=True)])
    apple = FakeApple(
        [{"uid": "a1", "summary": "读书会", "start": "2026-09-10", "all_day": True}]
    )
    notion = FakeNotion([{"title": "交报告", "ddl": "2026-09-10", "db_name": "事务"}])
    briefing = MorningBriefing(
        store, FakeWeather(), notion, apple, Settings(timezone=TZ)
    )

    text = asyncio.run(briefing.build("qq:FriendMessage:u1", now=NOW))

    assert "组会" in text
    assert "读书会" in text
    assert "交报告" in text
    assert "晴" in text
    assert "-1~9℃" in text


def test_build_without_optional_services():
    store = FakeStore([ScheduleItem(title="组会", time="2026-09-10 09:30")])
    briefing = MorningBriefing(store, None, None, None, Settings(timezone=TZ))

    text = asyncio.run(briefing.build("qq:FriendMessage:u1", now=NOW))

    assert "暂无" in text
    assert "天气：暂无" in text


def test_notion_failure_is_reported():
    store = FakeStore([])
    briefing = MorningBriefing(
        store, None, FakeNotion(None), None, Settings(timezone=TZ)
    )

    text = asyncio.run(briefing.build("qq:FriendMessage:u1", now=NOW))

    assert "获取失败" in text


def test_build_skips_all_day_items_not_today():
    store = FakeStore([ScheduleItem(title="明天的事", time="2026-09-11", all_day=True)])
    briefing = MorningBriefing(store, None, None, None, Settings(timezone=TZ))

    text = asyncio.run(briefing.build("qq:FriendMessage:u1", now=NOW))

    assert "明天的事" not in text


def test_apple_event_in_other_offset_shown_in_local_time():
    apple = FakeApple(
        [{"uid": "a1", "summary": "跨时区", "start": "2026-09-10T01:00:00+00:00"}]
    )
    briefing = MorningBriefing(FakeStore([]), None, None, apple, Settings(timezone=TZ))

    text = asyncio.run(briefing.build("qq:FriendMessage:u1", now=NOW))

    assert "09:00" in text
    assert "跨时区" in text
