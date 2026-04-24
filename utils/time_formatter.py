from __future__ import annotations

from datetime import datetime


def format_time_text(raw_text: str) -> str:
    """将 ISO 时间字符串格式化为本地可读文本。

    输入示例：
    - "2026-03-24T12:00:05.000Z"
    - "2026-03-24T12:00:05+00:00"

    输出格式：
    - "03-24 20:00:05"（按当前系统本地时区显示）
    """
    try:
        # 兼容常见 Zulu 时间写法：把尾部 "Z" 转为 "+00:00"。
        dt = datetime.fromisoformat(raw_text.replace("Z", "+00:00"))

        # 转换到本地时区并格式化为“月-日 时:分:秒”。
        return dt.astimezone().strftime("%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        # 解析失败时回退原文，避免因为时间格式异常导致整条消息渲染失败。
        return raw_text
