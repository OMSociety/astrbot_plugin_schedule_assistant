"""
统一消息发送模块

封装平台无关的消息发送和事件回复逻辑。
支持多平台候选、会话记忆、优雅降级。
"""
from typing import Optional, List
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
        """解析用户平台绑定配置"""
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
        """获取当前已注册的所有平台ID"""
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

    def _build_platform_candidates(self, user_id: str, preferred_platform: Optional[str] = None) -> List[str]:
        """
        构建平台候选列表（按优先级排序）

        优先级：指定平台 > 最近成功平台 > 用户绑定 > 全局平台 > 可用平台
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

    def remember_user_platform(self, user_id: str, platform_id: str):
        """记录用户上次接收成功的平台"""
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

    async def reply_event(self, event, message: str) -> bool:
        """
        回复消息事件

        Args:
            event: 消息事件对象
            message: 要回复的消息文本

        Returns:
            bool: 是否回复成功
        """
        try:
            await event.reply(message)
            return True
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} 回复消息失败: {e}")
            return False
