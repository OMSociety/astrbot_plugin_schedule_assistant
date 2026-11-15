"""Apple 日历同步。"""

from __future__ import annotations

import logging
from datetime import datetime

from .settings import Settings

logger = logging.getLogger("astrbot")


class CalendarSync:
    def __init__(self, apple, store, settings: Settings):
        self.apple = apple
        self.store = store
        self.settings = settings
        self._issue_reported = False

    async def run(self, targets: tuple[str, ...]) -> dict[str, int] | None:
        if self.apple is None or not targets:
            return None
        try:
            events, issues = await self.apple.get_all_events(days=7)
        except Exception as exc:
            logger.warning(f"Apple 日历读取失败: {exc}")
            return None

        if issues:
            if not self._issue_reported:
                logger.warning(
                    "Apple 日历本轮读取不完整，只做新增与更新，不删除本地日程: %s",
                    "；".join(issues),
                )
                self._issue_reported = True
        else:
            self._issue_reported = False

        if not events:
            return None

        now = datetime.now(self.settings.timezone)
        total = {"added": 0, "updated": 0, "deleted": 0}
        for umo in targets:
            try:
                stats = await self.store.sync_from_apple_calendar(
                    umo, events, allow_delete=not issues, now=now
                )
            except Exception as exc:
                logger.warning(f"Apple 日历同步失败 umo={umo}: {exc}")
                continue
            for key in total:
                total[key] += stats[key]
        return total
