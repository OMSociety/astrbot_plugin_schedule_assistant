"""
统一消息发送模块
"""

from typing import Optional
from astrbot.api.star import Context
from astrbot.api.event import MessageEvent

from .constants import LOG_PREFIX


async def send_to_user(context: Context, user_id: str, message: str) -> bool:
    """向指定用户发送私聊消息"""
    try:
        platform_mgr = context.get_platform_manager()
        if not platform_mgr:
            return False

        platforms = platform_mgr.get_platforms()
        if not platforms:
            return False

        # 获取第一个可用的平台（通常是 aiocqhttp/onebot）
        platform = next(iter(platforms.values()), None)
        if not platform:
            return False

        # 获取平台 ID
        platform_id = platform.adapter
        if not platform_id:
            return False

        session = f"{platform_id}:FriendMessage:{user_id}"
        await context.send_message(
            session=session,
            message_chain=[{"type": "plain", "text": message}]
        )
        return True
    except Exception as e:
        from astrbot import logger
        logger.warning(f"{LOG_PREFIX} 发送消息失败 user={user_id}: {e}")
        return False


async def reply_event(event: MessageEvent, message: str) -> bool:
    """回复消息事件"""
    try:
        await event.reply(message)
        return True
    except Exception as e:
        from astrbot import logger
        logger.warning(f"{LOG_PREFIX} 回复消息失败: {e}")
        return False
