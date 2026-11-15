"""把数据组装成一次推送的文本。"""

from __future__ import annotations

from datetime import date, datetime

from .prompts import render
from .schedule_store import ScheduleItem

_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def weekday_label(day: date) -> str:
    return _WEEKDAYS[day.weekday()]


def parse_item_time(value: str) -> datetime:
    return datetime.fromisoformat((value or "").strip().replace(" ", "T"))


def format_ddl(ddl: str, tz=None) -> str:
    if not ddl:
        return ""
    try:
        due = datetime.fromisoformat(ddl.replace("Z", "+00:00"))
        if due.tzinfo is None:
            if tz is not None:
                due = due.replace(tzinfo=tz)
        else:
            due = due.astimezone(tz) if tz is not None else due.astimezone()
        now = datetime.now(tz) if tz is not None else datetime.now()
        diff = (due.date() - now.date()).days
    except (TypeError, ValueError):
        return ""
    if diff < 0:
        return f"已逾期{-diff}天"
    if diff == 0:
        return "今天截止"
    if diff == 1:
        return "还剩1天"
    return f"还剩{diff}天"


def time_label(item: ScheduleItem) -> str:
    if item.all_day:
        return "全天"
    try:
        start = parse_item_time(item.time)
    except ValueError:
        return item.time
    if item.end_time:
        try:
            end = parse_item_time(item.end_time)
        except ValueError:
            return f"{start:%H:%M}"
        return f"{start:%H:%M}-{end:%H:%M}"
    return f"{start:%H:%M}"


def ahead_label(minutes: int) -> str:
    if minutes <= 0:
        return "即将开始"
    if minutes < 60:
        return f"{minutes} 分钟后开始"
    hours, rest = divmod(minutes, 60)
    if rest:
        return f"{hours} 小时 {rest} 分钟后开始"
    return f"{hours} 小时后开始"


def format_agenda(entries: list[tuple[str, str]]) -> str:
    if not entries:
        return "暂无"
    return "\n".join(f"- {label} {title}" for label, title in entries)


def morning(
    *,
    date_label: str,
    weekday: str,
    weather_current: str,
    weather_forecast: str,
    agenda: str,
    notion_todos: str | None,
    custom: str = "",
) -> str:
    if notion_todos is None:
        notion_block = ""
    elif notion_todos == "获取失败":
        notion_block = "待办：获取失败\n"
    else:
        notion_block = f"待办：{notion_todos}\n"
    return render(
        "morning",
        {
            "date": date_label,
            "weekday": weekday,
            "weather_current": weather_current or "暂无",
            "weather_forecast": weather_forecast,
            "agenda": agenda,
            "notion_todos": "" if notion_todos is None else notion_todos,
            "notion_block": notion_block,
        },
        custom,
    )


def bath(*, current_time: str, default_time: str, custom: str = "") -> str:
    return render(
        "bath",
        {"current_time": current_time, "default_time": default_time},
        custom,
    )


def sleep(*, current_time: str, default_time: str, custom: str = "") -> str:
    return render(
        "sleep",
        {"current_time": current_time, "default_time": default_time},
        custom,
    )


def water(*, current_time: str, custom: str = "") -> str:
    return render("water", {"current_time": current_time}, custom)


def schedule(
    *,
    item_title: str,
    time_label_text: str,
    ahead_label_text: str,
    item_context: str,
    custom: str = "",
) -> str:
    return render(
        "schedule",
        {
            "item_title": item_title,
            "time_label": time_label_text,
            "ahead_label": ahead_label_text,
            "item_context": item_context or "无",
        },
        custom,
    )
