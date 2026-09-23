"""日程时间解析与显示标签（单时间点 / 区间 / 全天）

三形态统一入口 `parse_schedule_time`：
- 单时间点：「2024-01-15 14:30」「明天9点」「今天晚上8点」（先前模式，保留）
- 时间区间：「明天9点到11点」「2026-09-10 09:00~11:00」，结束只给时刻时继承开始日期，
  早于开始视为次日；两端纯日期的区间（「明天到后天」）按全天处理，多日取开始日
- 全天日程：「明天全天」「整天」「2026-09-10」这类纯日期输入

另提供 `parse_item_time`（读存储里的时间串）与 `format_when_label` / `format_item_when`
（工具回执与列表显示）。工具、提醒、播报三处共用同一套口径，避免各自解析漂移。
"""

import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

# 中文星期 → weekday()（周一=0）
_WEEKDAY_MAP = {
    "周一": 0,
    "周二": 1,
    "周三": 2,
    "周四": 3,
    "周五": 4,
    "周六": 5,
    "周日": 6,
    "周天": 6,
    "星期一": 0,
    "星期二": 1,
    "星期三": 2,
    "星期四": 3,
    "星期五": 4,
    "星期六": 5,
    "星期日": 6,
    "星期天": 6,
}

# 时刻表达式：「9点」「3点半」「14:30」「下午3点」「晚上8点30」（可带秒）
_CLOCK_TOKEN = (
    r"(?:凌晨|上午|早上|早晨|中午|下午|傍晚|晚上|晚间)?\s*"
    r"\d{1,2}\s*(?::\d{1,2}(?::\d{2})?|：\d{1,2}|点半|点\s*\d{0,2})\s*分?"
)
_CLOCK_SPLIT_RE = re.compile(rf"^(.*?)\s*({_CLOCK_TOKEN})\s*$")
_CLOCK_RE = re.compile(r"^(\d{1,2})(?::(\d{1,2}))?(?::\d{2})?$")
# 「09:00-11:00」中缀连字符 → 「到」（日期里的连字符不受影响）
_HYPHEN_RANGE_RE = re.compile(r"(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})")
_RANGE_SEPS = ("到", "至", "~", " - ")


def parse_item_time(time_str: str) -> datetime | None:
    """解析存储里的时间串：ISO（含时区）、「%Y-%m-%d %H:%M」、date-only、「%H:%M」"""
    if not time_str:
        return None
    s = time_str.strip()
    # 优先 fromisoformat（原生支持 ISO 8601，含时区）
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except (ValueError, TypeError):
        pass
    # 再尝试普通格式（显式列 date-only，不依赖 fromisoformat 的版本差异）
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def is_all_day_event(item) -> bool:
    """判断是否为全天事件（优先 all_day 标记，其次 date-only 时间串）"""
    if getattr(item, "all_day", False):
        return True
    t = (getattr(item, "time", "") or "").strip()
    if len(t) == 10 and t.count("-") == 2:
        try:
            datetime.strptime(t, "%Y-%m-%d")
            return True
        except ValueError:
            pass
    return False


def parse_clock(text: str) -> tuple[int, int] | None:
    """解析时刻：「9点」「3点半」「14:30」「下午3点」「晚上8点30」→ (时, 分)"""
    s = (text or "").strip()
    if not s:
        return None
    period = None
    for kw, p in (
        ("凌晨", "am"),
        ("上午", "am"),
        ("早上", "am"),
        ("早晨", "am"),
        ("中午", "noon"),
        ("下午", "pm"),
        ("傍晚", "pm"),
        ("晚上", "pm"),
        ("晚间", "pm"),
    ):
        if kw in s:
            period = p
            s = s.replace(kw, "")
            break
    s = (
        s.replace("：", ":")
        .replace("点半", ":30")
        .replace("点", ":")
        .replace("分", "")
        .strip()
    )
    if s.endswith(":"):
        s += "00"
    m = _CLOCK_RE.match(s)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if minute > 59:
        return None
    if period in ("pm", "noon") and hour < 12:
        hour += 12
    elif period == "am" and hour == 12:
        hour = 0
    if hour > 23:
        return None
    return hour, minute


def split_date_clock(text: str) -> tuple[str, str]:
    """拆分「日期部分」与「时刻部分」，返回 (date_part, clock_part)（可能为空串）"""
    m = _CLOCK_SPLIT_RE.match((text or "").strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return (text or "").strip(), ""


def parse_date_part(text: str) -> datetime | None:
    """解析日期部分为当天 0 点：今天/明天/后天/周X/X月X日/YYYY-MM-DD 等"""
    s = (text or "").strip()
    today0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if not s:
        return today0
    rel_days = {"今天": 0, "明天": 1, "后天": 2}
    if s in rel_days:
        return today0 + relativedelta(days=rel_days[s])
    week = s.lstrip("下个本这")
    if week in _WEEKDAY_MAP:
        delta = (_WEEKDAY_MAP[week] - today0.weekday()) % 7
        return today0 + relativedelta(days=delta)
    norm = (
        s.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("T", "")
        .replace("t", "")
        .strip()
    )
    for fmt in ("%Y-%m-%d", "%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            # %m-%d 补上当年年份再解析（strptime 无年份的 %m-%d 在新 Python 有歧义告警）
            dt = (
                datetime.strptime(f"{today0.year}-{norm}", "%Y-%m-%d")
                if fmt == "%m-%d"
                else datetime.strptime(norm, fmt)
            )
        except ValueError:
            continue
        if fmt == "%m-%d" and dt < today0:
            try:
                dt = dt.replace(year=today0.year + 1)
            except ValueError:  # 次年无此日（如 2-29 落非闰年）
                return None
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return None


def parse_when(text: str) -> tuple[datetime | None, bool]:
    """解析单个时间表达式，返回 (datetime, 是否带时刻)。

    纯日期（「明天」「2026-09-10」）返回当天 0 点且 has_time=False；
    「明天9点」「14:30」返回具体时刻且 has_time=True。
    """
    s = (text or "").strip()
    if not s:
        return None, False
    date_part, clock_part = split_date_clock(s)
    date0 = parse_date_part(date_part)
    if date0 is None:
        return None, False
    if not clock_part:
        return date0, False
    clock = parse_clock(clock_part)
    if clock is None:
        return None, False
    return date0.replace(hour=clock[0], minute=clock[1]), True


def is_clock_only(text: str) -> bool:
    """是否是「只给时刻、没给日期」的表达（如「11点」）"""
    return not split_date_clock(text or "")[0]


def parse_range_end(text: str, start: datetime) -> datetime | None:
    """解析区间结束时间：只给时刻时继承开始日期，早于开始视为次日（「23点到1点」）"""
    end, _has_time = parse_when(text)
    if end is None:
        return None
    if is_clock_only(text):
        end = end.replace(year=start.year, month=start.month, day=start.day)
        if end < start:
            end += timedelta(days=1)
    return end


def parse_schedule_time(
    datetime_str: str,
) -> tuple[datetime | None, datetime | None, bool]:
    """解析日程时间，返回 (开始, 结束, 是否全天)。

    - 区间：「明天9点到11点」「2026-09-10 09:00~11:00」→ (开始, 结束, False)
    - 全天：「明天」「明天全天」「2026-09-10」→ (当天 0 点, None, True)；
      两端纯日期的区间（「明天到后天」）同为全天，多日取开始日
    - 单点：「明天9点」→ (开始, None, False)
    """
    s = (datetime_str or "").strip().replace("整天", "全天")
    if not s:
        return None, None, False
    all_day_flag = "全天" in s
    s = s.replace("全天", " ").strip()
    s = _HYPHEN_RANGE_RE.sub(r"\1到\2", s)

    for sep in _RANGE_SEPS:
        if sep in s:
            left, right = s.split(sep, 1)
            left = left.strip().removeprefix("从")
            right = right.strip()
            start, start_has_time = parse_when(left)
            if start is None:
                return None, None, False
            end, end_has_time = parse_when(right)
            if end is None:
                return None, None, False
            if all_day_flag or (not start_has_time and not end_has_time):
                # 「全天」或两端纯日期（「明天到后天」）→ 全天；
                # 多日事件简化为开始日全天
                return (
                    start.replace(hour=0, minute=0, second=0, microsecond=0),
                    None,
                    True,
                )
            if is_clock_only(right):
                end = end.replace(year=start.year, month=start.month, day=start.day)
                if end < start:
                    end += timedelta(days=1)
            # 结束不晚于开始由调用方报「结束时间需要晚于开始时间」
            return start, end, False

    when, has_time = parse_when(s)
    if when is None:
        return None, None, False
    if all_day_flag or not has_time:
        return (
            when.replace(hour=0, minute=0, second=0, microsecond=0),
            None,
            True,
        )
    return when, None, False


def format_when_label(start: datetime, end: datetime | None, all_day: bool) -> str:
    """回执时间标签：09-02 全天 / 09-02 15:00-16:30 / 09-02 15:00"""
    if all_day:
        return f"{start.strftime('%m-%d')} 全天"
    if end:
        if end.date() == start.date():
            return f"{start.strftime('%m-%d %H:%M')}-{end.strftime('%H:%M')}"
        return f"{start.strftime('%m-%d %H:%M')}→{end.strftime('%m-%d %H:%M')}"
    return f"{start.strftime('%m-%d %H:%M')}"


def format_item_when(item, with_date: bool = False) -> str:
    """日程条目的显示标签：📅 全天 / ⏰ 15:00-16:30 / ⏰ 15:00。

    with_date=True 时前缀日期（多匹配提示用：同名日程靠日期区分）。
    """
    time_str = (getattr(item, "time", "") or "").strip()
    start_dt = parse_item_time(time_str)
    date_prefix = start_dt.strftime("%m-%d ") if (with_date and start_dt) else ""
    if is_all_day_event(item):
        return f"📅 {date_prefix}全天"
    end_dt = parse_item_time(item.end_time) if getattr(item, "end_time", None) else None
    if not start_dt:
        return f"⏰ {time_str}"
    if end_dt:
        if end_dt.date() == start_dt.date():
            return f"⏰ {date_prefix}{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"
        return f"⏰ {start_dt.strftime('%m-%d %H:%M')}→{end_dt.strftime('%m-%d %H:%M')}"
    return f"⏰ {date_prefix}{start_dt.strftime('%H:%M')}"
