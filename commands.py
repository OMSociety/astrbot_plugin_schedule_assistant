"""
日程命令处理模块（已简化）

不再处理具体命令，所有交互通过 LLM 工具完成。
保留此文件是为了与 main.py 的兼容性，但 handle_message 始终返回 False，
让消息继续传递给 LLM 处理。
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
        AiocqhttpMessageEvent,
    )

    from .messaging import MessagingService
    from .schedule_store import ScheduleStore


class CommandHandler:
    """
    日程命令处理器（已禁用）

    所有命令交互通过 LLM 工具完成，本处理器不再拦截消息。
    """

    def __init__(
        self,
        store: "ScheduleStore",
        messaging: "MessagingService",
    ):
        self.store = store
        self.messaging = messaging

    async def handle_message(
        self, event: "AiocqhttpMessageEvent", user_id: str, msg_text: str
    ) -> bool:
        """
        不再处理任何命令，始终返回 False，让消息传递给 LLM 工具。
        """
        # 所有交互通过 LLM 工具完成，不再本地处理
        return False
