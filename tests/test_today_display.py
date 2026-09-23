"""今日日程展示标签与问候语合并去重测试（早安播报的可信面）。

标签一致性是去重的前提：本地条目与 Apple 直读行必须同格式，
否则同一日程会在播报里出现两行。
"""

import types
from datetime import datetime

from schedule_assistant.main import ScheduleAssistant


class TestScheduleTimeLabel:
    def test_point_range_invalid_and_all_day(self):
        start = datetime(2026, 9, 10, 9, 0)
        assert ScheduleAssistant._schedule_time_label(start, None, False) == "09:00"
        assert (
            ScheduleAssistant._schedule_time_label(start, "2026-09-10T10:00:00", False)
            == "09:00-10:00"
        )
        assert (
            ScheduleAssistant._schedule_time_label(start, "bad-format", False)
            == "09:00"
        )
        assert (
            ScheduleAssistant._schedule_time_label(
                datetime(2026, 9, 10, 0, 0), None, True
            )
            == "全天"
        )


class TestMergeTodayBlocks:
    def _merge(self, local_text, apple_text):
        fake = types.SimpleNamespace()
        fake._extract_block_lines = ScheduleAssistant._extract_block_lines.__get__(fake)
        fake._merge_today_schedule_blocks = (
            ScheduleAssistant._merge_today_schedule_blocks.__get__(fake)
        )
        return fake._merge_today_schedule_blocks(local_text, apple_text)

    def test_identical_lines_deduped(self):
        """本地与 Apple 同格式行只留一行"""
        out = self._merge("⏰ 09:00-10:00 │ 组会", "⏰ 09:00-10:00 │ 组会")
        assert out == "⏰ 09:00-10:00 │ 组会"
        assert out.count("组会") == 1

    def test_different_labels_not_deduped(self):
        """格式不一致时会被视为两条（标签一致性的回归护栏）"""
        out = self._merge("⏰ 09:00 │ 组会", "⏰ 09:00-10:00 │ 组会")
        assert out.count("组会") == 2

    def test_empty_and_failure(self):
        assert self._merge("暂无", "暂无") == "暂无"
        assert self._merge("暂无", "获取失败") == "获取失败"
