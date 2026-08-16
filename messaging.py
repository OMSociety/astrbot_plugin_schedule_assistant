"""
统一消息发送模块

封装平台无关的消息发送和事件回复逻辑。
支持多平台候选、会话记忆、优雅降级、MessageTarget 统一路由。
由 main.py 的内联发送逻辑迁移而来，整合了最健壮的回复兜底机制。
"""

from dataclasses import dataclass
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import MessageChain

from .constants import LOG_PREFIX
from .markdown import MarkdownRenderer

# 常见会话类型，用于识别 UMO 格式（platform:session_type:session_id）
COMMON_SESSION_TYPES = (
    "FriendMessage",
    "GroupMessage",
    "TempMessage",
    "ChannelMessage",
)


@dataclass
class MessageTarget:
    """
    平台无关的消息目标

    统一承载 platform_id / session_type / session_id 三元组，
    所有发送路由（send_to_user / reply_to_event / UMO 解析）统一走它。
    """

    platform_id: str
    session_type: str = "FriendMessage"
    session_id: str = ""

    @classmethod
    def from_umo(
        cls, umo: str, session_types: set[str] | None = None
    ) -> "MessageTarget | None":
        """从 UMO 字符串（platform:session_type:session_id）解析目标

        Args:
            umo: 统一消息来源字符串
            session_types: 可选，校验第二段是否为已知会话类型；None 表示不校验

        Returns:
            Optional[MessageTarget]：解析成功返回目标，失败返回 None
        """
        if not umo or not isinstance(umo, str):
            return None
        parts = umo.strip().split(":")
        if len(parts) < 3:
            return None
        if session_types and parts[1] not in session_types:
            return None
        return cls(
            platform_id=parts[0].strip(),
            session_type=parts[1].strip(),
            session_id=":".join(parts[2:]).strip(),
        )

    def to_session(self) -> str:
        """转为 AstrBot 会话字符串（platform:session_type:session_id）"""
        return f"{self.platform_id}:{self.session_type}:{self.session_id}"

    def __str__(self) -> str:
        return self.to_session()


class MessagingService:
    """
    消息发送服务

    封装消息发送逻辑，支持：
    - 多平台候选和自动回退
    - 发送历史记忆（记住用户上次成功接收的平台）
    - 用户平台绑定（支持 UMO 格式路由，不硬编码平台）
    - 持久化平台恢复（进程重启后仍能精确推送）
    - 事件回复（兼容无 reply 方法的事件对象）
    """

    def __init__(
        self,
        context,
        config: dict,
        platform_lookup=None,
        users_lookup=None,
        default_user_id: str | None = None,
    ):
        """
        初始化消息服务

        Args:
            context: AstrBot 上下文
            config: 插件配置
            platform_lookup: 可选异步回调 user_id -> platform_id，用于从持久化存储恢复平台
            users_lookup: 可选异步回调 () -> list[str]，返回所有已知用户ID（用于目标用户解析）
            default_user_id: 可选默认目标用户ID（用户名单首个用户）

        平台路由说明：user_ids 中的 UMO 条目（platform:session_type:session_id）
        会在名单解析时自动注册平台绑定（register_umo_binding），无需单独配置；
        纯 ID 用户按私聊（FriendMessage）+ 可用平台自动路由。
        """
        self.context = context
        self.config = config
        self._platform_lookup = platform_lookup
        self._users_lookup = users_lookup
        self._default_user_id = str(default_user_id) if default_user_id else None
        # 会话类型固定私聊：UMO 条目可自带 session_type，纯 ID 用户按 FriendMessage 发送
        self._session_type = "FriendMessage"
        self._session_types = set(COMMON_SESSION_TYPES)
        self._session_types.add(self._session_type)
        # 平台绑定由 user_ids 中的 UMO 条目在名单解析时自动注册（register_umo_binding）
        self._user_platform_bindings: dict = {}
        self._recent_user_platforms: dict = {}
        self._md_renderer: MarkdownRenderer | None = None

    def _get_platform_type_map(self) -> dict[str, str]:
        """构建 实例ID → 平台类型名 映射（meta().name）

        从 platform_manager 动态读取，避免在配置或代码里硬编码平台实例ID。
        """
        mapping: dict[str, str] = {}
        try:
            for platform in self.context.platform_manager.platform_insts:
                try:
                    meta = platform.meta()
                    if meta and meta.id and meta.name:
                        mapping[str(meta.id)] = str(meta.name)
                except Exception as e:
                    logger.debug(f"{LOG_PREFIX} 读取平台 meta 失败: {e}")
                    continue
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} 构建平台类型映射失败: {e}")
        return mapping

    def _get_md_renderer(self) -> MarkdownRenderer:
        """惰性获取 markdown 渲染器"""
        if self._md_renderer is None:
            self._md_renderer = MarkdownRenderer(
                self.config, platform_types=self._get_platform_type_map()
            )
        return self._md_renderer

    def _build_markdown_chain(self, message: str, platform_id: str) -> MessageChain:
        """按平台渲染 markdown，返回消息链

        两级策略：原生平台直发 md 原文，其余 strip 后纯文本直发。
        """
        renderer = self._get_md_renderer()
        content, kind = renderer.render(message, platform_id)
        if kind == "native":
            return MessageChain([Comp.Plain(content)], use_markdown_=True)
        return MessageChain([Comp.Plain(content)])

    def _split_umo(self, umo: str):
        """
        尝试解析 UMO 字符串（platform:session_type:session_id）

        Args:
            umo: 统一消息来源字符串

        Returns:
            Optional[tuple]: (platform_id, session_type, session_id)，无法解析返回 None
        """
        target = MessageTarget.from_umo(umo, session_types=self._session_types)
        if target is None:
            return None
        return target.platform_id, target.session_type, target.session_id

    def register_umo_binding(self, umo: str, platform_id: str = "") -> str | None:
        """
        注册一条 UMO 平台绑定（user_ids 中的 UMO 条目在名单解析时自动调用）

        Args:
            umo: UMO 字符串，如 "Flandre:FriendMessage:xxx"
            platform_id: 可选发送平台，为空时取 UMO 第一段

        Returns:
            Optional[str]: 绑定的用户ID（session_id），失败返回 None
        """
        parsed = self._split_umo(umo)
        if not parsed:
            return None
        platform, session_type, session_id = parsed
        self._user_platform_bindings[session_id] = {
            "platform": (platform_id or platform).strip(),
            "session_type": session_type,
        }
        return session_id

    def _get_available_platform_ids(self) -> list[str]:
        """
        获取当前已注册的所有平台ID

        Returns:
            List[str]: 可用平台ID列表
        """
        ids: list[str] = []
        try:
            for platform in self.context.platform_manager.platform_insts:
                pid = platform.meta().id
                if pid:
                    ids.append(str(pid))
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} 获取平台列表失败: {e}")
        if not ids:
            logger.warning(f"{LOG_PREFIX} 未发现已注册平台，发送将不可用")
        return ids

    def _extract_platform_id_from_event(self, event: Any) -> str | None:
        """
        从事件对象中提取平台ID（duck typing，平台无关）

        通过通用属性探测，不依赖任何具体平台事件类：
        1. 优先读 platform_id / platform / platform_name 属性
        2. 次选从 session_id / session / unified_msg_origin（UMO 格式）取首段

        Args:
            event: 任意平台的消息事件对象

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
        return None

    def _build_platform_candidates(
        self, user_id: str, preferred_platform: str | None = None
    ) -> list[str]:
        """
        构建平台候选列表（按优先级排序）

        优先级：指定平台 > 最近成功平台 > 用户绑定（UMO 条目） > 可用平台

        Args:
            user_id: 目标用户ID
            preferred_platform: 优先使用的平台ID

        Returns:
            List[str]: 排序后的平台ID列表
        """
        candidates: list[str] = []
        if preferred_platform:
            candidates.append(str(preferred_platform).strip())
        recent = self._recent_user_platforms.get(str(user_id))
        if recent:
            candidates.append(recent)
        binding = self._user_platform_bindings.get(str(user_id))
        if binding and binding.get("platform"):
            candidates.append(binding["platform"])
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

    async def send_to_user(
        self,
        user_id: str,
        message: str,
        platform_id: str | None = None,
        markdown: bool | None = None,
    ) -> bool:
        """
        向指定用户发送私聊消息

        Args:
            user_id: 目标用户ID
            message: 要发送的消息文本
            platform_id: 优先使用的平台ID（可选，不写死，按配置/记忆/绑定路由）
            markdown: 是否启用 markdown 渲染，None 时跟随配置 markdown_enabled

        Returns:
            bool: 是否发送成功
        """
        md_enabled = (
            markdown
            if markdown is not None
            else bool(self.config.get("markdown_enabled", False))
        )
        try:
            available = set(self._get_available_platform_ids())
            sessions_tried = []

            binding = self._user_platform_bindings.get(str(user_id))
            session_type = (
                binding["session_type"]
                if binding and binding.get("session_type")
                else self._session_type
            )
            # 持久化平台恢复：进程重启后内存记忆丢失，从存储补回
            if not platform_id and binding and binding.get("platform"):
                platform_id = binding["platform"]
            if not platform_id and self._platform_lookup:
                try:
                    persisted = await self._platform_lookup(str(user_id))
                    if persisted:
                        platform_id = str(persisted).strip()
                except Exception as lookup_err:
                    logger.warning(
                        f"{LOG_PREFIX} 读取持久化平台失败 user={user_id} err={lookup_err}"
                    )

            for platform in self._build_platform_candidates(user_id, platform_id):
                if platform not in available:
                    logger.warning(
                        f"{LOG_PREFIX} 发送目标平台不可用: platform={platform} "
                        f"user={user_id} available={sorted(available)}"
                    )
                    continue

                target = MessageTarget(
                    platform_id=platform,
                    session_type=session_type,
                    session_id=str(user_id),
                )
                session = target.to_session()
                sessions_tried.append(session)

                try:
                    if md_enabled:
                        chain = self._build_markdown_chain(message, platform)
                    else:
                        chain = MessageChain([Comp.Plain(message)])
                    await self.context.send_message(session, chain)
                    self.remember_user_platform(user_id, platform)
                    logger.info(
                        f"{LOG_PREFIX} 发送成功 user={user_id} platform={platform}"
                    )
                    return True
                except Exception as send_err:
                    logger.warning(
                        f"{LOG_PREFIX} 发送失败"
                        f" user={user_id} platform={platform}"
                        f" err={send_err}"
                    )

            logger.error(
                f"{LOG_PREFIX} 发送消息失败，已尝试所有可用平台: "
                f"user={user_id} sessions={sessions_tried}"
            )
            return False
        except Exception as e:
            logger.error(f"{LOG_PREFIX} 发送消息异常: user={user_id} err={e}")
            return False

    @staticmethod
    def _collect_config_target_ids(config: dict) -> list[str]:
        """读取目标用户名单配置（user_ids 列表）"""
        raw = config.get("user_ids", []) or []
        return [str(uid) for uid in raw if uid]

    async def resolve_target_users(
        self, include_known_users: bool = False
    ) -> list[str]:
        """解析目标用户ID列表（支持 UID 或 UMO 格式，UMO 自动注册路由绑定）

        目标用户解析统一收敛到消息服务路由：
        用户名单（UMO 自动注册绑定） > 默认用户 > 全部已知用户（可选）

        所有来源统一做 UMO 归一化，避免同一用户同时以「纯 ID」和
        「完整 UMO」两种形式出现在结果中导致重复发送。

        Args:
            include_known_users: 是否包含存储中的全部已知用户
                （定时任务如日程扫描/Apple 同步固定传 True）

        Returns:
            List[str]: 去重排序后的目标用户ID列表
        """
        user_ids: set[str] = set()

        def _normalize(uid: str) -> str:
            """UMO 字符串归一化为 session_id，非 UMO 原样返回"""
            registered = self.register_umo_binding(uid)
            return registered or uid

        for uid in self._collect_config_target_ids(self.config):
            user_ids.add(_normalize(str(uid)))
        if self._default_user_id:
            # 默认用户可能来自 user_ids 的 UMO 条目，同样归一化
            user_ids.add(_normalize(str(self._default_user_id)))
        if include_known_users and self._users_lookup:
            try:
                for uid in await self._users_lookup():
                    if uid:
                        # 已知用户索引可能混入 UMO 形式（工具/事件路径写入），
                        # 统一归一化去重，避免同一用户被发送两次
                        user_ids.add(_normalize(str(uid)))
            except Exception as lookup_err:
                logger.warning(f"{LOG_PREFIX} 读取已知用户失败: err={lookup_err}")
        return sorted(user_ids)

    async def reply_to_event(self, event: Any, message: str) -> None:
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
                await self.context.send_message(
                    session_id, MessageChain([Comp.Plain(message)])
                )
                return
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} session_id 直发失败，尝试下一层: {e}")

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
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} user_id 发送失败，尝试下一层: {e}")

        # 第三层：兜底告警，不抛异常
        logger.warning(
            f"{LOG_PREFIX} 回复失败，且无可用回退通道: message={message[:40]}"
        )
