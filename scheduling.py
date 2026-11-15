"""定时推送与日程扫描。

插件只负责把“要说什么”写成一条提醒消息，并登记一个一次性的框架任务；
真正的回复由宿主主 Agent 生成并经 ``send_message_to_user`` 发出。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dt_time, timedelta

from . import notices
from .settings import JOB_PREFIX, Settings

logger = logging.getLogger("astrbot")

_DEFAULT_MORNING = "09:00"
_DEFAULT_BATH = "22:00"
_DEFAULT_SLEEP = "23:00"
_DEFAULT_WATER_START = "09:30"
_DEFAULT_WATER_END = "21:30"


def _parse_clock(value: str, fallback: str) -> dt_time:
    for candidate in (value, fallback):
        text = str(candidate or "").strip()
        try:
            hour, minute = text.split(":", 1)
            return dt_time(int(hour), int(minute))
        except (ValueError, TypeError):
            continue
    return dt_time(0, 0)


class Scheduling:
    TICK_SECONDS = 60
    DELIVERY_DELAY_SECONDS = 2
    SCHEDULE_WINDOW_SECONDS = 180
    KNOWN_JOB_TTL = timedelta(days=2)

    def __init__(self, plugin, store, settings: Settings, briefing, calendar_sync):
        self.plugin = plugin
        self.log = getattr(plugin, "logger", logger)
        self.context = plugin.context
        self.store = store
        self.settings = settings
        self.briefing = briefing
        self.calendar_sync = calendar_sync
        self._task: asyncio.Task | None = None
        self._known_jobs: dict[str, datetime] = {}
        self._last_sync: datetime | None = None
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- 生命周期

    async def start(self) -> None:
        if self.settings.invalid_targets:
            self.log.warning(
                "以下 user_umos 不是有效的 UMO，已忽略：%s",
                "、".join(self.settings.invalid_targets),
            )
        if not self.settings.target_umos:
            self.log.warning(
                "user_umos 中没有有效的 UMO，定时推送不会发送；请用 /sid 获取会话 UMO 后填入配置"
            )
        await self._delete_all_jobs()
        await self._register_basic_jobs()
        self._task = asyncio.create_task(self._tick_loop(), name="schedule_assistant")
        self.log.info("日程提醒调度已启动")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._delete_all_jobs()

    # ------------------------------------------------------------------ 主循环

    async def _tick_loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.log.exception("定时任务执行失败")
            await asyncio.sleep(self.TICK_SECONDS)

    async def _tick(self) -> None:
        now = datetime.now(self.settings.timezone)
        self._prune_known(now)
        async with self._lock:
            await self._sync_calendar(now)
            await self._scan_schedules(now)
            await self._ensure_water_jobs(now)

    def _timezone_key(self) -> str | None:
        tz = self.settings.timezone
        return getattr(tz, "key", None) or str(tz) or None

    # -------------------------------------------------------------- Apple 同步

    async def _sync_calendar(self, now: datetime) -> None:
        if self.calendar_sync is None or not self.settings.enable_apple_calendar_sync:
            return
        interval = timedelta(minutes=self.settings.apple_sync_interval)
        if self._last_sync is not None and now - self._last_sync < interval:
            return
        self._last_sync = now
        stats = await self.calendar_sync.run(self.settings.target_umos)
        if stats and any(stats.values()):
            self.log.info(
                "Apple 日历同步：新增 %d，更新 %d，删除 %d",
                stats["added"],
                stats["updated"],
                stats["deleted"],
            )

    # ------------------------------------------------------------------ 日程

    def _item_start(self, value: str) -> datetime | None:
        try:
            parsed = notices.parse_item_time(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=self.settings.timezone)
        return parsed.astimezone(self.settings.timezone)

    async def _scan_schedules(self, now: datetime) -> None:
        if not self.settings.enable_schedule_reminder:
            return
        minutes_before = self.settings.schedule_reminder_minutes
        for umo in self.settings.target_umos:
            items = await self.store.list_items(umo)
            for item in items:
                if item.all_day:
                    continue
                start = self._item_start(item.time)
                if start is None:
                    continue
                due = start - timedelta(minutes=minutes_before)
                seconds = (due - now).total_seconds()
                if not 0 < seconds <= self.SCHEDULE_WINDOW_SECONDS:
                    continue
                name = f"{JOB_PREFIX}·日程提醒·{umo}·{item.id}·{start:%Y%m%d%H%M}"
                if name in self._known_jobs:
                    continue
                ahead = int(round((start - now).total_seconds() / 60))
                note = notices.schedule(
                    item_title=item.title,
                    time_label_text=notices.time_label(item),
                    ahead_label_text=notices.ahead_label(ahead),
                    item_context=item.context,
                    custom=self.settings.prompt_schedule,
                )
                await self._enqueue(name, umo, note, due, now)

    # ------------------------------------------------------------------ 喝水

    async def _ensure_water_jobs(self, now: datetime) -> None:
        if not self.settings.enable_water_reminder:
            return
        slots = self._water_slots(
            now,
            _parse_clock(self.settings.water_start_time, _DEFAULT_WATER_START),
            _parse_clock(self.settings.water_end_time, _DEFAULT_WATER_END),
            self.settings.water_interval,
        )
        if not slots:
            return
        for umo in self.settings.target_umos:
            for slot in slots:
                name = f"{JOB_PREFIX}·喝水·{umo}·{slot:%Y%m%d%H%M}"
                if name in self._known_jobs:
                    continue
                note = notices.water(
                    current_time=f"{slot:%H:%M}", custom=self.settings.prompt_water
                )
                await self._enqueue(name, umo, note, slot, now)

    @staticmethod
    def _water_slots(
        now: datetime, start: dt_time, end: dt_time, interval: int
    ) -> list[datetime]:
        cursor = datetime.combine(now.date(), start, tzinfo=now.tzinfo)
        last = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
        step = timedelta(minutes=max(1, interval))
        slots: list[datetime] = []
        while cursor <= last:
            if cursor >= now:
                slots.append(cursor)
            cursor += step
        return slots

    # ------------------------------------------------------------------ 固定推送

    async def _on_morning(self) -> None:
        await self._broadcast(
            "早安",
            lambda umo: self.briefing.build(umo),
            fallback_factory=self._morning_fallback,
        )

    async def _on_bath(self) -> None:
        now = datetime.now(self.settings.timezone)
        note = notices.bath(
            current_time=f"{now:%H:%M}",
            default_time=self.settings.bath_time,
            custom=self.settings.prompt_bath,
        )
        await self._push_all("洗澡", note)

    async def _on_sleep(self) -> None:
        now = datetime.now(self.settings.timezone)
        note = notices.sleep(
            current_time=f"{now:%H:%M}",
            default_time=self.settings.sleep_time,
            custom=self.settings.prompt_sleep,
        )
        await self._push_all("睡觉", note)

    async def _broadcast(self, kind: str, builder, fallback_factory=None) -> None:
        for umo in self.settings.target_umos:
            try:
                note = await builder(umo)
            except Exception as exc:
                self.log.warning(f"{kind}播报生成失败 umo={umo}: {exc}")
                if fallback_factory is None:
                    continue
                note = fallback_factory()
            await self._enqueue_push(kind, umo, note)

    def _morning_fallback(self) -> str:
        now = datetime.now(self.settings.timezone)
        return f"早安，今天是 {now:%Y-%m-%d}。天气与日程暂时读取失败，稍后我再看一眼。"

    async def _push_all(self, kind: str, note: str) -> None:
        for umo in self.settings.target_umos:
            await self._enqueue_push(kind, umo, note)

    async def _enqueue_push(self, kind: str, umo: str, note: str) -> None:
        now = datetime.now(self.settings.timezone)
        stamp = now.strftime("%Y%m%d%H%M%S")
        name = f"{JOB_PREFIX}·推送·{kind}·{umo}·{stamp}"
        run_at = now + timedelta(seconds=self.DELIVERY_DELAY_SECONDS)
        await self._enqueue(name, umo, note, run_at, now)

    # -------------------------------------------------------------- 任务登记

    async def _enqueue(
        self,
        name: str,
        umo: str,
        note: str,
        run_at: datetime,
        now: datetime | None = None,
    ) -> None:
        if name in self._known_jobs:
            return
        now = now or datetime.now(self.settings.timezone)
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=self.settings.timezone)
        if run_at <= now:
            run_at = now + timedelta(seconds=self.DELIVERY_DELAY_SECONDS)
        try:
            await self.context.cron_manager.add_active_job(
                name=name,
                cron_expression=None,
                payload={"session": umo, "note": note},
                timezone=self._timezone_key(),
                persistent=False,
                run_once=True,
                run_at=run_at,
            )
        except Exception as exc:
            self.log.warning(f"登记推送任务失败 name={name}: {exc}")
            return
        self._known_jobs[name] = now

    def _prune_known(self, now: datetime) -> None:
        stale = [
            name
            for name, created in self._known_jobs.items()
            if now - created > self.KNOWN_JOB_TTL
        ]
        for name in stale:
            del self._known_jobs[name]

    async def _register_basic_jobs(self) -> None:
        entries = (
            (
                self.settings.enable_morning_report,
                self.settings.morning_report_time,
                _DEFAULT_MORNING,
                "早安",
                self._on_morning,
            ),
            (
                self.settings.enable_bath_reminder,
                self.settings.bath_time,
                _DEFAULT_BATH,
                "洗澡",
                self._on_bath,
            ),
            (
                self.settings.enable_sleep_reminder,
                self.settings.sleep_time,
                _DEFAULT_SLEEP,
                "睡觉",
                self._on_sleep,
            ),
        )
        for enabled, value, fallback, label, handler in entries:
            if not enabled:
                continue
            clock = _parse_clock(value, fallback)
            try:
                await self.context.cron_manager.add_basic_job(
                    name=f"{JOB_PREFIX}·{label}",
                    cron_expression=f"{clock.minute} {clock.hour} * * *",
                    handler=handler,
                    timezone=self._timezone_key(),
                    persistent=False,
                )
            except Exception as exc:
                self.log.warning(f"登记{label}任务失败: {exc}")

    async def _delete_all_jobs(self) -> None:
        for job in await self.context.cron_manager.list_jobs():
            if job.name.startswith(JOB_PREFIX):
                await self.context.cron_manager.delete_job(job.job_id)
        self._known_jobs.clear()

    async def cancel_item_jobs(self, umo: str, item_id: str) -> None:
        prefix = f"{JOB_PREFIX}·日程提醒·{umo}·{item_id}·"
        for job in await self.context.cron_manager.list_jobs():
            if job.name.startswith(prefix):
                await self.context.cron_manager.delete_job(job.job_id)
                self._known_jobs.pop(job.name, None)
