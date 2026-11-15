"""调度核心逻辑测试：任务登记、去重、喝水时刻、启动清理。"""

import asyncio
import logging
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from schedule_assistant.schedule_store import ScheduleItem
from schedule_assistant.scheduling import Scheduling
from schedule_assistant.settings import Settings

TZ = ZoneInfo("Asia/Shanghai")
UMO = "qq:FriendMessage:u1"


class FakeCron:
    def __init__(self, jobs=None):
        self.jobs = list(jobs or [])
        self.active = []
        self.basic = []
        self._next = 1

    async def list_jobs(self):
        return list(self.jobs)

    async def add_active_job(self, **kwargs):
        job = SimpleNamespace(
            job_id=f"a{self._next}", name=kwargs["name"], job_type="active_agent"
        )
        self._next += 1
        self.jobs.append(job)
        self.active.append(kwargs)
        return job

    async def add_basic_job(self, **kwargs):
        job = SimpleNamespace(
            job_id=f"b{self._next}", name=kwargs["name"], job_type="basic"
        )
        self._next += 1
        self.jobs.append(job)
        self.basic.append(kwargs)
        return job

    async def delete_job(self, job_id):
        self.jobs = [job for job in self.jobs if job.job_id != job_id]


class FakeStore:
    def __init__(self, items=None):
        self.items = items or {}

    async def list_items(self, umo):
        return list(self.items.get(umo, []))


def _make(items=None, jobs=None, **overrides):
    cron = FakeCron(jobs)
    settings = Settings(timezone=TZ, **overrides)
    plugin = SimpleNamespace(
        context=SimpleNamespace(cron_manager=cron), logger=logging.getLogger("test")
    )
    scheduling = Scheduling(plugin, FakeStore(items), settings, None, None)
    return scheduling, cron


def test_schedule_scan_enqueues_once():
    now = datetime(2026, 9, 10, 9, 0, tzinfo=TZ)
    start = now + timedelta(minutes=12)
    item = ScheduleItem.create(title="组会", time=start.strftime("%Y-%m-%d %H:%M"))
    scheduling, cron = _make(
        items={UMO: [item]},
        target_umos=(UMO,),
        enable_schedule_reminder=True,
        schedule_reminder_minutes=10,
    )

    async def scenario():
        await scheduling._scan_schedules(now)
        assert len(cron.active) == 1
        job = cron.active[0]
        assert "日程提醒" in job["name"]
        assert item.id in job["name"]
        assert job["payload"]["session"] == UMO
        assert "组会" in job["payload"]["note"]
        assert job["persistent"] is False

        await scheduling._scan_schedules(now)
        assert len(cron.active) == 1

    asyncio.run(scenario())


def test_schedule_scan_skips_all_day_and_other_sessions():
    now = datetime(2026, 9, 10, 9, 0, tzinfo=TZ)
    all_day = ScheduleItem.create(title="全天", time="2026-09-10", all_day=True)
    clock = ScheduleItem.create(
        title="组会", time=(now + timedelta(minutes=12)).strftime("%Y-%m-%d %H:%M")
    )
    scheduling, cron = _make(
        items={UMO: [all_day], "qq:GroupMessage:g1": [clock]},
        target_umos=(UMO,),
        enable_schedule_reminder=True,
    )

    async def scenario():
        await scheduling._scan_schedules(now)
        assert cron.active == []

    asyncio.run(scenario())


def test_water_slots():
    now = datetime(2026, 9, 10, 10, 0, tzinfo=TZ)
    slots = Scheduling._water_slots(now, time(9, 30), time(21, 30), 90)
    assert len(slots) == 8
    assert slots[0].strftime("%H:%M") == "11:00"
    assert slots[-1].strftime("%H:%M") == "21:30"


def test_basic_jobs_registered():
    scheduling, cron = _make(target_umos=(UMO,))

    async def scenario():
        await scheduling._register_basic_jobs()
        names = {job["name"] for job in cron.basic}
        assert names == {"日程助手·早安", "日程助手·洗澡", "日程助手·睡觉"}
        assert all(job["persistent"] is False for job in cron.basic)

    asyncio.run(scenario())


def test_start_removes_stale_jobs_and_registers_basic():
    stale = SimpleNamespace(
        job_id="old", name="日程助手·推送·早安·x·1", job_type="active_agent"
    )
    other = SimpleNamespace(job_id="keep", name="用户自己的任务", job_type="basic")
    scheduling, cron = _make(target_umos=(UMO,), jobs=[stale, other])

    async def scenario():
        await scheduling.start()
        await scheduling.stop()
        names = {job.name for job in cron.jobs}
        assert "用户自己的任务" in names
        assert not any(name.startswith("日程助手") for name in names)

    asyncio.run(scenario())


def test_cancel_item_jobs():
    now = datetime(2026, 9, 10, 9, 0, tzinfo=TZ)
    item = ScheduleItem.create(
        title="组会", time=(now + timedelta(minutes=12)).strftime("%Y-%m-%d %H:%M")
    )
    scheduling, cron = _make(
        items={UMO: [item]},
        target_umos=(UMO,),
        enable_schedule_reminder=True,
    )

    async def scenario():
        await scheduling._scan_schedules(now)
        assert len(cron.jobs) == 1
        await scheduling.cancel_item_jobs(UMO, item.id)
        assert cron.jobs == []

    asyncio.run(scenario())


def test_push_enqueued_after_delay():
    scheduling, cron = _make(target_umos=(UMO,))

    async def scenario():
        await scheduling._enqueue_push("洗澡", UMO, "洗澡啦")
        assert len(cron.active) == 1
        job = cron.active[0]
        assert job["run_once"] is True
        assert job["persistent"] is False
        assert job["payload"]["session"] == UMO
        assert job["payload"]["note"] == "洗澡啦"

    asyncio.run(scenario())
