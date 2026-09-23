"""time_parser 时间解析与显示标签测试（点 / 区间 / 全天）"""

from datetime import datetime, timedelta

from schedule_assistant.schedule_store import ScheduleItem
from schedule_assistant.time_parser import (
    format_item_when,
    format_when_label,
    is_all_day_event,
    parse_item_time,
    parse_clock,
    parse_schedule_time,
)


class TestParseClock:
    def test_hour_only(self):
        assert parse_clock("9点") == (9, 0)

    def test_half_hour(self):
        assert parse_clock("3点半") == (3, 30)

    def test_colon(self):
        assert parse_clock("14:30") == (14, 30)

    def test_pm(self):
        assert parse_clock("下午3点") == (15, 0)

    def test_pm_with_minutes(self):
        assert parse_clock("晚上8点30") == (20, 30)

    def test_am_12_is_midnight(self):
        assert parse_clock("上午12点") == (0, 0)

    def test_invalid(self):
        assert parse_clock("25点") is None
        assert parse_clock("abc") is None
        assert parse_clock("") is None


class TestParseScheduleTime:
    def test_point_iso(self):
        start, end, all_day = parse_schedule_time("2026-09-10 14:30")
        assert start == datetime(2026, 9, 10, 14, 30)
        assert end is None
        assert all_day is False

    def test_point_relative(self):
        start, end, all_day = parse_schedule_time("明天9点")
        assert start is not None
        assert start.date() == (datetime.now() + timedelta(days=1)).date()
        assert (start.hour, start.minute) == (9, 0)
        assert end is None
        assert all_day is False

    def test_range_clock_end(self):
        start, end, all_day = parse_schedule_time("明天9点到11点")
        assert start is not None and end is not None
        assert (start.hour, start.minute) == (9, 0)
        assert (end.hour, end.minute) == (11, 0)
        assert end.date() == start.date()
        assert all_day is False

    def test_range_cross_midnight(self):
        start, end, all_day = parse_schedule_time("23点到1点")
        assert start is not None and end is not None
        assert end - start == timedelta(hours=2)
        assert all_day is False

    def test_range_hyphen(self):
        start, end, all_day = parse_schedule_time("2026-09-10 09:00-11:00")
        assert start == datetime(2026, 9, 10, 9, 0)
        assert end == datetime(2026, 9, 10, 11, 0)
        assert all_day is False

    def test_range_tilde(self):
        start, end, all_day = parse_schedule_time("09:00~11:00")
        assert start is not None and end is not None
        assert end - start == timedelta(hours=2)

    def test_equal_end_not_cross_day(self):
        """「9点到9点」等值区间不跨天（等值交给调用方报错）"""
        start, end, all_day = parse_schedule_time("2026-09-10 9点到9点")
        assert end == start
        assert all_day is False

    def test_all_day_bare_date(self):
        start, end, all_day = parse_schedule_time("明天")
        assert start is not None
        assert start.date() == (datetime.now() + timedelta(days=1)).date()
        assert (start.hour, start.minute) == (0, 0)
        assert end is None
        assert all_day is True

    def test_all_day_keyword(self):
        start, end, all_day = parse_schedule_time("明天全天")
        assert all_day is True
        assert end is None
        assert start is not None

    def test_date_only_range_is_all_day(self):
        """两端纯日期的区间（「明天到后天」）按全天处理，多日取开始日"""
        start, end, all_day = parse_schedule_time("2026-09-10到2026-09-12")
        assert start == datetime(2026, 9, 10, 0, 0)
        assert end is None
        assert all_day is True

    def test_all_day_flag_wins_over_range(self):
        """「全天」关键词优先于区间时刻（「…9点到11点全天」按全天处理）"""
        start, end, all_day = parse_schedule_time("2026-09-10 9点到11点全天")
        assert start == datetime(2026, 9, 10, 0, 0)
        assert end is None
        assert all_day is True

    def test_invalid(self):
        assert parse_schedule_time("随便说说") == (None, None, False)
        assert parse_schedule_time("") == (None, None, False)


class TestParseItemTime:
    def test_iso_with_z(self):
        dt = parse_item_time("2026-09-10T14:30:00Z")
        assert dt is not None
        assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 9, 10, 14, 30)

    def test_plain_and_date_only_and_clock_only(self):
        assert parse_item_time("2026-09-10 14:30") == datetime(2026, 9, 10, 14, 30)
        assert parse_item_time("2026-09-10") == datetime(2026, 9, 10, 0, 0)
        assert parse_item_time("14:30") == datetime(1900, 1, 1, 14, 30)

    def test_invalid(self):
        assert parse_item_time("随便说说") is None
        assert parse_item_time("") is None


class TestAllDayDetection:
    def test_flag(self):
        assert is_all_day_event(ScheduleItem(time="2026-09-10 00:00", all_day=True))

    def test_date_only(self):
        assert is_all_day_event(ScheduleItem(time="2026-09-10"))

    def test_timed(self):
        assert not is_all_day_event(ScheduleItem(time="2026-09-10 09:00"))


class TestLabels:
    def test_when_label(self):
        start = datetime(2026, 9, 10, 15, 0)
        assert format_when_label(start, None, False) == "09-10 15:00"
        assert (
            format_when_label(start, datetime(2026, 9, 10, 16, 30), False)
            == "09-10 15:00-16:30"
        )
        assert (
            format_when_label(start, datetime(2026, 9, 11, 1, 0), False)
            == "09-10 15:00→09-11 01:00"
        )
        assert format_when_label(start, None, True) == "09-10 全天"

    def test_item_when(self):
        assert format_item_when(ScheduleItem(time="2026-09-10", all_day=True)) == (
            "📅 全天"
        )
        assert format_item_when(ScheduleItem(time="2026-09-10 10:00")) == "⏰ 10:00"
        assert (
            format_item_when(
                ScheduleItem(time="2026-09-10 10:00", end_time="2026-09-10 11:30")
            )
            == "⏰ 10:00-11:30"
        )

    def test_item_when_with_date(self):
        """多匹配提示需要日期：同名日程靠日期区分"""
        item = ScheduleItem(time="2026-09-10 10:00", end_time="2026-09-10 11:30")
        assert format_item_when(item, with_date=True) == "⏰ 09-10 10:00-11:30"
        assert (
            format_item_when(
                ScheduleItem(time="2026-09-10", all_day=True), with_date=True
            )
            == "📅 09-10 全天"
        )
