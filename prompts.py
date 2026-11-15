"""内置提醒提示词模板与渲染。"""

from __future__ import annotations

MORNING = """定时推送｜早安播报

日期：{date} {weekday}
天气：{weather_current} {weather_forecast}
今日日程：
{agenda}
{notion_block}
写作要求：
一句早安语，一句天气与体感，陈述今日所有日程和待办；一句收尾。缺哪项就跳过，不要编造。

示例（不参考其语气）：
早上好！今天晴，零下 1 度到 9 度，早晚偏冷，穿厚点。九点有组会，下午两点前记得交读书报告。别忘了买牛奶、回邮件

输出要求：
只输出播报正文，纯文本，不要提及定时任务、系统或 AI。全文不超过 120 字。"""

BATH = """定时推送｜洗澡提醒

当前时间：{current_time}
默认洗澡时间：{default_time}

输出要求：
只输出提醒正文，纯文本，不要提及定时任务、系统或 AI。全文不超过 40 字。"""

SLEEP = """定时推送｜睡觉提醒

当前时间：{current_time}
默认睡觉时间：{default_time}

输出要求：
只输出提醒正文，纯文本，不要提及定时任务、系统或 AI。全文不超过 40 字。"""

WATER = """定时推送｜喝水提醒

当前时间：{current_time}

输出要求：
只输出提醒正文，纯文本，不要提及定时任务、系统或 AI。全文不超过 30 字。"""

SCHEDULE = """定时推送｜日程提醒

日程：{item_title}
时间：{time_label}（{ahead_label}）
备注：{item_context}

输出要求：
只输出提醒正文，纯文本，不要提及定时任务、系统或 AI。全文不超过 30 字。"""

TEMPLATES = {
    "morning": MORNING,
    "bath": BATH,
    "sleep": SLEEP,
    "water": WATER,
    "schedule": SCHEDULE,
}


def render(kind: str, data: dict[str, object], custom: str = "") -> str:
    """渲染指定类型的提示词；自定义模板非空时整段接管。"""
    template = custom.strip() or TEMPLATES[kind]
    for key, value in data.items():
        template = template.replace("{" + key + "}", str(value))
    return template.strip()
