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


def test_bath_default_contains_length_requirement():
    text = prompts.render("bath", {"current_time": "22:00", "default_time": "22:00"})
    assert "40 字" in text


def test_schedule_default_contains_length_requirement():
    text = prompts.render(
        "schedule",
        {
            "item_title": "组会",
            "time_label_text": "09:00",
            "ahead_label_text": "10 分钟后开始",
            "item_context": "",
        },
    )
    assert "组会" in text
    assert "30 字" in text


def test_morning_contains_writing_requirement_and_example():
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
    assert "不要编造" in text
    assert "示例（不参考其语气）" in text
    assert "120 字" in text


def test_no_prompt_keeps_only_data_and_output_rules():
    text = prompts.render("bath", {"current_time": "22:00", "default_time": "22:00"})
    assert "写作要求" not in text
    assert "22:00" in text
