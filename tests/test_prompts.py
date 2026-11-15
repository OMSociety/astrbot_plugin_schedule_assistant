"""推送提示词组装测试。"""

from schedule_assistant import prompts


def test_custom_prompt_takes_over_completely():
    text = prompts.render(
        "bath", {"current_time": "22:00", "default_time": "22:00"}, "自定义模板"
    )
    assert text == "自定义模板"


def test_custom_prompt_renders_placeholders():
    text = prompts.render(
        "water", {"current_time": "10:00"}, "现在 {current_time}，喝水"
    )
    assert text == "现在 10:00，喝水"


def test_bath_default_is_plain_intent():
    text = prompts.render("bath", {"current_time": "22:00", "default_time": "22:00"})
    assert "22:00" in text
    assert "提醒用户去洗澡" in text
    assert "字" not in text


def test_schedule_default_is_plain_intent():
    text = prompts.render(
        "schedule",
        {
            "item_title": "组会",
            "time_label": "09:00",
            "ahead_label": "10 分钟后开始",
            "item_context": "",
        },
    )
    assert "组会" in text
    assert "提醒用户这件事" in text


def test_morning_contains_requirement_and_example():
    text = prompts.render(
        "morning",
        {
            "date": "2026-09-10",
            "weekday": "周四",
            "weather_current": "晴",
            "weather_forecast": "-1~9℃",
            "agenda": "- 09:00 组会",
            "notion_todos": "- 交报告",
        },
    )
    assert "一句问候" in text
    assert "示例（其语气不纳入参考，按你的表达习惯来）" in text
    assert "今天也要加油呀" in text


def test_morning_omits_todo_block_when_notion_is_not_configured():
    text = prompts.render(
        "morning",
        {
            "date": "2026-09-10",
            "weekday": "周四",
            "weather_current": "晴",
            "weather_forecast": "-1~9℃",
            "agenda": "- 09:00 组会",
            "notion_todos": None,
        },
    )
    assert "待办：" not in text
