"""时间标签与文本拼装测试。"""

from datetime import date, datetime, timedelta

from schedule_assistant import notices
from schedule_assistant.schedule_store import ScheduleItem


def test_weekday_label():
    assert notices.weekday_label(date(2026, 9, 10)) == "周四"


def test_parse_item_time():
    assert notices.parse_item_time("2026-09-10 09:30") == datetime(2026, 9, 10, 9, 30)
    assert notices.parse_item_time("2026-09-10T09:30") == datetime(2026, 9, 10, 9, 30)


def test_time_label():
    assert (
        notices.time_label(ScheduleItem(title="a", time="2026-09-10", all_day=True))
        == "全天"
    )
    with_end = ScheduleItem(
        title="a", time="2026-09-10 09:00", end_time="2026-09-10 11:00"
    )
    assert notices.time_label(with_end) == "09:00-11:00"
    single = ScheduleItem(title="a", time="2026-09-10 09:00")
    assert notices.time_label(single) == "09:00"


def test_ahead_label():
    assert notices.ahead_label(0) == "即将开始"
    assert notices.ahead_label(5) == "5 分钟后开始"
    assert notices.ahead_label(60) == "1 小时后开始"
    assert notices.ahead_label(95) == "1 小时 35 分钟后开始"


def test_format_agenda():
    assert notices.format_agenda([]) == "暂无"
    assert notices.format_agenda([("09:00", "组会"), ("15:00", "读书会")]) == (
        "- 09:00 组会\n- 15:00 读书会"
    )


def test_format_ddl():
    assert notices.format_ddl("") == ""
    today = date.today()
    assert notices.format_ddl(today.isoformat()) == "今天截止"
    assert notices.format_ddl((today + timedelta(days=3)).isoformat()) == "还剩3天"
    assert notices.format_ddl((today - timedelta(days=1)).isoformat()) == "已逾期1天"
