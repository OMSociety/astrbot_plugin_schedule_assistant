"""内置提醒提示词模板与渲染。"""

from __future__ import annotations

MORNING = """现在是 {date} {weekday}。
天气：{weather_current}；{weather_forecast}
今日日程：
{agenda}
{notion_block}
请写一段早安播报：一句问候，一句天气与体感，按时间顺序说今日日程和待办，最后一句收尾。

示例（其语气不纳入参考，按你的表达习惯来）：
早上好！今天晴，零下 1 度到 9 度，早晚偏冷，穿厚点。九点有组会，下午两点前记得交读书报告。别忘了买牛奶、回邮件。今天也要加油呀"""

BATH = """现在是 {current_time}。
提醒用户去洗澡。"""

SLEEP = """现在是 {current_time}。
提醒用户该睡觉了。"""

WATER = """现在是 {current_time}。
提醒用户喝杯水。"""

SCHEDULE = """日程「{item_title}」{ahead_label}（{time_label}）。
备注：{item_context}

提醒用户这件事。"""

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
