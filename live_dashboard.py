"""
Live Dashboard 功能模块

提供设备状态查询、LLM工具注入、命令处理等功能。
从 main.py 中提取，实现模块化。
"""

from typing import TYPE_CHECKING

from astrbot.api.event import filter
from astrbot.core.message.components import Node, Nodes, Plain, Reply
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .services.config_parser import parse_list_config

if TYPE_CHECKING:
    pass


class LiveDashboardMixin:
    """Live Dashboard 功能混入类"""

    def _get_live_dashboard_config(self) -> dict:
        """从主配置中提取 live_dashboard 相关配置（扁平键）"""
        cfg = self.config
        return {
            "base_url": cfg.get("live_dashboard_base_url", ""),
            "auth_token": cfg.get("live_dashboard_auth_token", ""),
            "request_timeout_sec": cfg.get("live_dashboard_request_timeout_sec", 30),
            "include_offline_devices": cfg.get(
                "live_dashboard_include_offline_devices", False
            ),
            "max_devices": cfg.get("live_dashboard_max_devices", 10),
            "device_whitelist_keywords": cfg.get(
                "live_dashboard_device_whitelist_keywords", ""
            ),
            "device_blacklist_keywords": cfg.get(
                "live_dashboard_device_blacklist_keywords", ""
            ),
            "group_blacklist_sessions": cfg.get(
                "live_dashboard_group_blacklist_sessions", ""
            ),
            "user_blacklist_senders": cfg.get(
                "live_dashboard_user_blacklist_senders", ""
            ),
            "info_blacklist_keywords": cfg.get(
                "live_dashboard_info_blacklist_keywords", ""
            ),
            "info_blacklist_replacement": cfg.get(
                "live_dashboard_info_blacklist_replacement",
                "不想让你看到我在干什么喵~",
            ),
            "show_platform": cfg.get("live_dashboard_show_platform", True),
            "show_app_name": cfg.get("live_dashboard_show_app_name", True),
            "show_display_title": cfg.get("live_dashboard_show_display_title", True),
            "show_battery": cfg.get("live_dashboard_show_battery", True),
            "show_music": cfg.get("live_dashboard_show_music", True),
            "show_last_seen": cfg.get("live_dashboard_show_last_seen", True),
            "show_viewer_count": cfg.get("live_dashboard_show_viewer_count", False),
            "show_server_time": cfg.get("live_dashboard_show_server_time", False),
        }

    def _get_live_dashboard_denied_text(self, event) -> str:
        """检查 Live Dashboard 查询权限"""
        sender_id = str(event.get_sender_id() or "")
        session_id = str(getattr(event.message_obj, "session_id", "") or "")

        # 检查群组黑名单
        group_raw = self.config.get("live_dashboard_group_blacklist_sessions", "") or ""
        group_list = parse_list_config(group_raw)
        if any(
            blocked == session_id or session_id.endswith(":" + blocked)
            for blocked in group_list
        ):
            return "该群组已禁用状态查询喵。"

        # 检查用户黑名单
        user_raw = self.config.get("live_dashboard_user_blacklist_senders", "") or ""
        user_list = parse_list_config(user_raw)
        if sender_id and any(blocked == sender_id for blocked in user_list):
            return "你已被禁止使用该查询喵。"

        return ""

    async def _ensure_live_dashboard_service(self):
        """延迟初始化 Live Dashboard 服务"""
        if getattr(self, "live_dashboard_service", None) is None:
            from .services.dashboard_service import DashboardService

            self.live_dashboard_service = DashboardService(
                self._get_live_dashboard_config()
            )

    async def _query_live_dashboard_message(self) -> tuple:
        """查询并渲染 Live Dashboard 消息"""
        await self._ensure_live_dashboard_service()
        return await self.live_dashboard_service.query_and_render()

    @filter.on_llm_request()
    async def inject_live_dashboard_tool_prompt(self, event, req):
        """注入 LLM 工具使用提示"""
        instruction = "\n[Live Dashboard]\n你可以调用 query_live_dashboard_status 获取用户实时设备状态。当用户询问视奸/设备状态等问题时优先调用。该工具无需参数。\n"  # noqa: E501
        req.system_prompt = (req.system_prompt or "") + instruction

    @filter.llm_tool(name="query_live_dashboard_status")
    async def query_live_dashboard_status_tool(self, event) -> str:
        """LLM 工具：查询 Live Dashboard 状态"""
        denied = self._get_live_dashboard_denied_text(event)
        if denied:
            return denied

        await self._ensure_live_dashboard_service()
        message, count = await self._query_live_dashboard_message()

        error_prefixes = (
            "未配置 Live Dashboard 地址",
            "请求超时：",
            "鉴权失败：",
            "请求失败：",
            "网络错误：",
        )
        if message.startswith(error_prefixes):
            return f"实时状态查询失败：{message}"

        return f"实时状态查询成功，当前展示设备数：{count}。\n{message}"

    @filter.command("视奸", alias={"live", "dashboard", "设备状态", "状态面板"})
    async def query_live_dashboard_cmd(self, event: AiocqhttpMessageEvent):
        """命令处理器：查询 Live Dashboard"""
        denied = self._get_live_dashboard_denied_text(event)
        if denied:
            yield event.chain_result(
                [
                    Reply(id=event.message_obj.message_id),
                    Plain(text=denied),
                ]
            )
            return

        await self._ensure_live_dashboard_service()
        message, count = await self._query_live_dashboard_message()

        if count < 2 or event.get_platform_name() != "aiocqhttp":
            yield event.chain_result(
                [Reply(id=event.message_obj.message_id), Plain(text=message)]
            )
            return

        # 合并转发模式
        blocks = self._split_message(message)
        forward_nodes = [
            Node(
                uin=str(event.get_self_id() or "0"),
                name="Live Dashboard",
                content=[
                    Reply(id=event.message_obj.message_id),
                    Plain(text=blocks[0] if blocks else message),
                ],
            )
        ]
        for block in blocks[1:]:
            forward_nodes.append(
                Node(
                    uin=str(event.get_self_id() or "0"),
                    name="Live Dashboard",
                    content=[Plain(text=block)],
                )
            )
        yield event.chain_result([Nodes(nodes=forward_nodes)])

    @staticmethod
    def _split_message(message: str, max_len: int = 500) -> list:
        """分块长消息"""
        blocks, current = [], ""
        for line in message.split("\n"):
            if len(current) + len(line) + 1 <= max_len:
                current = (current + "\n" + line) if current else line
            else:
                if current:
                    blocks.append(current)
                current = line
        if current:
            blocks.append(current)
        return blocks or [message]
