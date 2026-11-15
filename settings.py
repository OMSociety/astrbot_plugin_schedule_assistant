"""插件配置解析：把嵌套的配置项收敛成一个只读的 Settings。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

JOB_PREFIX = "日程助手"
DEFAULT_TIMEZONE = "Asia/Shanghai"


def as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return default
    return bool(value)


def as_int(value: object, default: int, minimum: int = 0) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(minimum, number)


def as_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = value.replace(",", "\n").replace("，", "\n").splitlines()
    elif isinstance(value, (list, tuple)):
        parts = [str(part) for part in value]
    else:
        parts = [str(value)]
    return tuple(part.strip() for part in parts if part and part.strip())


def resolve_timezone(*configs: dict | None) -> tzinfo:
    for config in configs:
        name = str((config or {}).get("timezone") or "").strip()
        if not name:
            continue
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return datetime.now().astimezone().tzinfo or dt_timezone.utc


MESSAGE_TYPES = frozenset({"FriendMessage", "GroupMessage"})


def parse_target(value: str) -> str | None:
    """校验配置项是否为可投递的 UMO（私聊或群聊）。

    UMO 形如 ``platform:message_type:session_id``；同一条 UMO 同时是配置项、
    存储键与投递会话标识。
    """
    text = (value or "").strip()
    parts = text.split(":", 2)
    if len(parts) != 3 or not all(parts):
        return None
    if parts[1] not in MESSAGE_TYPES:
        return None
    return text


def _default_timezone() -> tzinfo:
    try:
        return ZoneInfo(DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.now().astimezone().tzinfo or dt_timezone.utc


@dataclass(frozen=True)
class Settings:
    target_umos: tuple[str, ...] = ()
    invalid_targets: tuple[str, ...] = ()

    enable_schedule_reminder: bool = False
    schedule_reminder_minutes: int = 10

    enable_morning_report: bool = True
    morning_report_time: str = "09:00"
    enable_bath_reminder: bool = True
    bath_time: str = "22:00"
    enable_sleep_reminder: bool = True
    sleep_time: str = "23:00"
    enable_water_reminder: bool = True
    water_start_time: str = "09:30"
    water_end_time: str = "21:30"
    water_interval: int = 90

    enable_apple_calendar_sync: bool = False
    apple_sync_interval: int = 30
    apple_username: str = ""
    apple_app_password: str = ""
    apple_caldav_host: str = ""
    apple_calendar_id: str = ""
    webcal_urls: tuple[str, ...] = ()

    maton_api_key: str = ""
    notion_db_ids: tuple[str, ...] = ()
    weather_api_key: str = ""
    weather_city: str = "北京"

    prompt_morning: str = ""
    prompt_bath: str = ""
    prompt_sleep: str = ""
    prompt_water: str = ""
    prompt_schedule: str = ""

    timezone: tzinfo = field(default_factory=_default_timezone)


def load_settings(config: dict, global_config: dict | None = None) -> Settings:
    basic = config.get("basic_settings") or {}
    schedule = config.get("schedule_reminder_settings") or {}
    habit = config.get("habit_reminder_settings") or {}
    calendar = config.get("calendar_sync_settings") or {}
    apple = calendar.get("apple_calendar") or {}
    external = config.get("external_services_settings") or {}
    prompts = config.get("prompt_settings") or {}

    target_umos: list[str] = []
    invalid_targets: list[str] = []
    for raw in as_list(basic.get("user_umos")):
        umo = parse_target(raw)
        if umo is None:
            invalid_targets.append(raw)
        elif umo not in target_umos:
            target_umos.append(umo)

    return Settings(
        target_umos=tuple(target_umos),
        invalid_targets=tuple(invalid_targets),
        enable_schedule_reminder=as_bool(schedule.get("enable_schedule_reminder")),
        schedule_reminder_minutes=as_int(
            schedule.get("schedule_reminder_minutes"), 10, 1
        ),
        enable_morning_report=as_bool(habit.get("enable_morning_report"), True),
        morning_report_time=str(habit.get("morning_report_time") or "09:00").strip(),
        enable_bath_reminder=as_bool(habit.get("enable_bath_reminder"), True),
        bath_time=str(habit.get("bath_time") or "22:00").strip(),
        enable_sleep_reminder=as_bool(habit.get("enable_sleep_reminder"), True),
        sleep_time=str(habit.get("sleep_time") or "23:00").strip(),
        enable_water_reminder=as_bool(habit.get("enable_water_reminder"), True),
        water_start_time=str(habit.get("water_start_time") or "09:30").strip(),
        water_end_time=str(habit.get("water_end_time") or "21:30").strip(),
        water_interval=as_int(habit.get("water_interval"), 90, 1),
        enable_apple_calendar_sync=as_bool(calendar.get("enable_apple_calendar_sync")),
        apple_sync_interval=as_int(calendar.get("apple_calendar_sync_interval"), 30, 1),
        apple_username=str(apple.get("username") or "").strip(),
        apple_app_password=str(apple.get("app_password") or "").strip(),
        apple_caldav_host=str(apple.get("caldav_host") or "").strip(),
        apple_calendar_id=str(apple.get("calendar_id") or "").strip(),
        webcal_urls=as_list(calendar.get("webcal_urls")),
        maton_api_key=str(external.get("maton_api_key") or "").strip(),
        notion_db_ids=as_list(external.get("notion_db_ids")),
        weather_api_key=str(external.get("weather_api_key") or "").strip(),
        weather_city=str(external.get("weather_city") or "北京").strip(),
        prompt_morning=str(prompts.get("prompt_morning") or ""),
        prompt_bath=str(prompts.get("prompt_bath") or ""),
        prompt_sleep=str(prompts.get("prompt_sleep") or ""),
        prompt_water=str(prompts.get("prompt_water") or ""),
        prompt_schedule=str(prompts.get("prompt_schedule") or ""),
        timezone=resolve_timezone(global_config, config),
    )
