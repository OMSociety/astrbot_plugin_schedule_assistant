"""
统一消息发送模块

封装平台无关的消息发送和事件回复逻辑。
支持多平台候选、会话记忆、优雅降级。
由 main.py 的内联发送逻辑迁移而来，整合了最健壮的回复兜底机制。
"""
from typing import Optional, List
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.message.components import Plain
from astrbot import logger
from .constants import LOG_PREFIX


class MessagingService:
    """
    消息发送服务

    封装消息发送逻辑，支持：
    - 多平台候选和自动回退
    - 发送历史记忆（记住用户上次成功接收的平台）
    - 全局平台兜底
    - 事件回复（兼容无 reply 方法的事件对象）
    """

    def __init__(self, context, config: dict):
        """
        初始化消息服务

        Args:
            context: AstrBot 上下文
            config: 插件配置，包含以下键：
                - send_platform_id: 全局发送平台ID
                - default_session_type: 默认会话类型，默认 FriendMessage
                - user_platform_bindings: 用户平台绑定映射
        """
        self.context = context
        self.config = config
        self._session_type = str(config.get("default_session_type", "FriendMessage") or "FriendMessage")
        self._global_platform_id = str(config.get("send_platform_id", "") or "").strip()
        self._user_platform_bindings = self._parse_user_platform_bindings()
        self._recent_user_platforms: dict = {}

    def _parse_user_platform_bindings(self) -> dict:
        """
        解析用户平台绑定配置

        Returns:
            dict: {user_id: platform_id} 映射
        """
        bindings: dict = {}
        raw_bindings = self.config.get("user_platform_bindings", []) or []
        for item in raw_bindings:
            user_id = ""
            platform_id = ""
            if isinstance(item, dict):
                user_id = str(item.get("user_id", "")).strip()
                platform_id = str(item.get("platform_id", "")).strip()
            elif isinstance(item, str) and ":" in item:
                user_id, platform_id = item.split(":", 1)
                user_id = user_id.strip()
                platform_id = platform_id.strip()
            if user_id and platform_id:
                bindings[user_id] = platform_id
        return bindings

    def _get_available_platform_ids(self) -> List[str]:
        """
        获取当前已注册的所有平台ID

        Returns:
            List[str]: 可用平台ID列表
        """
        ids: List[str] = []
        try:
            for platform in self.context.platform_manager.platform_insts:
                pid = platform.meta().id
                if pid:
                    ids.append(str(pid))
        except Exception:
            pass
        if not ids:
            fallback = self._global_platform_id or "aiocqhttp"
            logger.warning(f"{LOG_PREFIX} 未发现已注册平台，使用回退: {fallback}")
            ids = [fallback]
        return ids

    def _extract_platform_id_from_event(self, event: AiocqhttpMessageEvent) -> Optional[str]:
        """
        从事件对象中提取平台ID

        Args:
            event: 消息事件对象

        Returns:
            Optional[str]: 平台ID，未知则返回 None
        """
        for attr in ("platform_id", "platform", "platform_name"):
            value = getattr(event, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for attr in ("session_id", "session", "unified_msg_origin"):
            value = getattr(event, attr, None)
            if isinstance(value, str) and ":" in value:
                return value.split(":", 1)[0].strip()
        if isinstance(event, AiocqhttpMessageEvent):
            return "aiocqhttp"
        return None

    def _build_platform_candidates(self, user_id: str, preferred_platform: Optional[str] = None) -> List[str]:
        """
        构建平台候选列表（按优先级排序）

        优先级：指定平台 > 最近成功平台 > 用户绑定 > 全局平台 > 可用平台

        Args:
            user_id: 目标用户ID
            preferred_platform: 优先使用的平台ID

        Returns:
            List[str]: 排序后的平台ID列表
        """
        candidates: List[str] = []
        if preferred_platform:
            candidates.append(str(preferred_platform).strip())
        recent = self._recent_user_platforms.get(str(user_id))
        if recent:
            candidates.append(recent)
        bound = self._user_platform_bindings.get(str(user_id))
        if bound:
            candidates.append(bound)
        if self._global_platform_id:
            candidates.append(self._global_platform_id)
        candidates.extend(self._get_available_platform_ids())
        # 去重，保持顺序
        seen = set()
        ordered = []
        for pid in candidates:
            if pid and pid not in seen:
                ordered.append(pid)
                seen.add(pid)
        return ordered

    def remember_user_platform(self, user_id: str, platform_id: str) -> None:
        """
        记录用户上次接收成功的平台

        Args:
            user_id: 用户ID
            platform_id: 平台ID
        """
        self._recent_user_platforms[str(user_id)] = platform_id

    async def send_to_user(self, user_id: str, message: str, platform_id: Optional[str] = None) -> bool:
        """
        向指定用户发送私聊消息

        Args:
            user_id: 目标用户ID
            message: 要发送的消息文本
            platform_id: 优先使用的平台ID（可选）

        Returns:
            bool: 是否发送成功
        """
        try:
            chain = MessageChain([Plain(message)])
            available = set(self._get_available_platform_ids())
            sessions_tried = []

            for platform in self._build_platform_candidates(user_id, platform_id):
                if platform not in available:
                    logger.warning(
                        f"{LOG_PREFIX} 发送目标平台不可用: platform={platform} "
                        f"user={user_id} available={sorted(available)}"
                    )
                    continue

                session = f"{platform}:{self._session_type}:{user_id}"
                sessions_tried.append(session)

                try:
                    await self.context.send_message(session, chain)
                    self.remember_user_platform(user_id, platform)
                    logger.info(f"{LOG_PREFIX} 发送成功 user={user_id} platform={platform}")
                    return True
                except Exception as send_err:
                    logger.warning(
                        f"{LOG_PREFIX} 发送失败 user={user_id} platform={platform} err={send_err}"
                    )

            logger.error(
                f"{LOG_PREFIX} 发送消息失败，已尝试所有可用平台: "
                f"user={user_id} sessions={sessions_tried}"
            )
            return False
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 发送消息异常: user={user_id} err={e}")
            return False

    async def reply_to_event(self, event: AiocqhttpMessageEvent, message: str) -> None:
        """
        回复消息事件，兼容不同版本的事件对象

        采用三层兜底策略：
        1. 优先通过 session_id 直接回复（最可靠）
        2. 次选通过 user_id + 平台提取发送
        3. 兜底记录日志（避免崩溃）

        Args:
            event: 消息事件对象
            message: 要回复的消息文本
        """
        # 第一层：优先尝试 session_id 直接回复
        try:
            session_id = getattr(event, "session_id", "")
            if isinstance(session_id, str) and session_id.strip():
                await self.context.send_message(session_id, MessageChain([Plain(message)]))
                return
        except Exception:
            pass

        # 第二层：按 user_id + 平台组合发送
        try:
            user_id = str(event.get_sender_id())
            if user_id:
                platform_id = self._extract_platform_id_from_event(event)
                if platform_id:
                    await self.send_to_user(user_id, message, platform_id)
                else:
                    await self.send_to_user(user_id, message)
                return
        except Exception:
            pass

        # 第三层：兜底告警，不抛异常
        logger.warning(f"{LOG_PREFIX} 回复失败，且无可用回退通道: message={message[:40]}")