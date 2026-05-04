from __future__ import annotations

from typing import Any


def get_text_value(config: dict[str, Any], key: str, default: str = "") -> str:
    """读取字符串配置并去除首尾空白。

    设计目的：
    - 统一处理配置项中的 `None`、数字、布尔等非字符串输入。
    - 避免调用方重复写 `str(...).strip()` 的样板代码。
    """
    # 从配置中读取目标键，缺失时使用默认值。
    value = config.get(key, default)

    # 对 None 做特殊处理：保持默认值语义，避免把 None 转成字符串 "None"。
    if value is None:
        return default

    # 统一转字符串并去除首尾空白。
    return str(value).strip()


def get_bool_value(config: dict[str, Any], key: str, default: bool = False) -> bool:
    """读取布尔配置，兼容常见字符串写法。

    支持的“真值”字符串：
    - "1" / "true" / "yes" / "on"（大小写不敏感）
    """
    # 读取原始值。
    value = config.get(key, default)

    # 若本身就是 bool，直接返回。
    if isinstance(value, bool):
        return value

    # 字符串按约定真值集合解析。
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}

    # 其他类型（如 int/float/list）回退到 Python 原生 bool 语义。
    return bool(value)


def parse_list_config(raw_text: str, *, to_lower: bool = False) -> list[str]:
    """解析列表型文本配置（支持逗号/分号/换行分隔）。

    Args:
        raw_text: 原始配置文本。
        to_lower: 是否把结果统一转为小写。
    """
    separators = [",", "，", ";", "；", "\n", "\r", "\t"]
    normalized = raw_text
    for separator in separators:
        normalized = normalized.replace(separator, ",")

    values: list[str] = []
    for part in normalized.split(","):
        value = part.strip()
        if not value:
            continue
        values.append(value.lower() if to_lower else value)

    return values


def get_int_value(
    config: dict[str, Any],
    key: str,
    default: int,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    """读取整数配置，并可选执行上下限裁剪。

    典型用途：
    - 请求超时秒数
    - 最大展示数量
    - 各类阈值参数
    """
    # 先取原始配置值，缺失时使用默认值。
    value = config.get(key, default)

    # 尝试转换为 int，失败则回退默认值。
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default

    # 若配置了最小值，执行下限保护。
    if min_value is not None:
        number = max(min_value, number)

    # 若配置了最大值，执行上限保护。
    if max_value is not None:
        number = min(max_value, number)

    return number


def parse_time_config(
    time_str: str, default_hour: int = 0, default_minute: int = 0
) -> tuple[int, int]:
    """解析HH:MM格式的时间配置。

    Args:
        time_str: 时间字符串，格式为 "HH:MM"
        default_hour: 解析失败时的默认小时
        default_minute: 解析失败时的默认分钟

    Returns:
        (hour, minute) 元组
    """
    if not time_str or not isinstance(time_str, str):
        return default_hour, default_minute

    try:
        # 尝试解析时间
        parts = time_str.strip().split(":")
        if len(parts) != 2:
            return default_hour, default_minute

        hour = int(parts[0])
        minute = int(parts[1])

        # 验证范围
        if not (0 <= hour <= 23) or not (0 <= minute <= 59):
            return default_hour, default_minute

        return hour, minute
    except (ValueError, TypeError):
        return default_hour, default_minute
