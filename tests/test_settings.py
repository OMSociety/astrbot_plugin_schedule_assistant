"""配置解析测试。"""

from datetime import datetime
from zoneinfo import ZoneInfo

from schedule_assistant.settings import load_settings, parse_target


def test_load_nested_config():
    config = {
        "basic_settings": {
            "user_umos": [
                "qq:FriendMessage:20002",
                "qq:GroupMessage:g1",
                "bad",
                "qq:FriendMessage:20002",
            ]
        },
        "schedule_reminder_settings": {
            "enable_schedule_reminder": True,
            "schedule_reminder_minutes": 15,
        },
        "habit_reminder_settings": {
            "morning_report_time": "08:30",
            "water_interval": 60,
        },
        "external_services_settings": {
            "weather_city": "杭州",
            "notion_db_ids": ["事务:aaa"],
        },
        "prompt_settings": {"prompt_water": "喝水 {current_time}"},
    }
    settings = load_settings(config)
    assert settings.target_umos == ("qq:FriendMessage:20002", "qq:GroupMessage:g1")
    assert settings.invalid_targets == ("bad",)
    assert settings.enable_schedule_reminder is True
    assert settings.schedule_reminder_minutes == 15
    assert settings.morning_report_time == "08:30"
    assert settings.water_interval == 60
    assert settings.weather_city == "杭州"
    assert settings.notion_db_ids == ("事务:aaa",)
    assert settings.prompt_water == "喝水 {current_time}"


def test_defaults():
    settings = load_settings({})
    assert settings.schedule_reminder_minutes == 10
    assert settings.enable_morning_report is True
    assert settings.bath_time == "22:00"
    assert settings.sleep_time == "23:00"
    assert settings.water_start_time == "09:30"
    assert settings.water_end_time == "21:30"
    assert settings.enable_schedule_reminder is False


def test_timezone_from_global_config():
    settings = load_settings({}, {"timezone": "UTC"})
    assert settings.timezone == ZoneInfo("UTC")

    settings = load_settings({}, {"timezone": "Not/AZone"})
    assert isinstance(settings.timezone, type(datetime.now().astimezone().tzinfo))


def test_parse_target():
    assert parse_target("qq:FriendMessage:20002") == "qq:FriendMessage:20002"
    assert parse_target("qq:GroupMessage:g1") == "qq:GroupMessage:g1"
    assert parse_target("20002") is None
    assert parse_target("qq:FriendMessage:") is None
    assert parse_target("qq:StrangerMessage:1") is None
    assert parse_target("  ") is None
