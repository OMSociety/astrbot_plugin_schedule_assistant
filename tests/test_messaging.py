"""
消息服务测试：UMO 解析与目标用户归一化去重

测试 MessageTarget.from_umo 的解析规则，以及
resolve_target_users 对纯 ID / UMO 混存场景的去重（修复重复发送的关键）。
包环境由 conftest.py 模拟。
"""

import asyncio
from types import SimpleNamespace

from schedule_assistant.messaging import MessageTarget, MessagingService


class TestMessageTargetFromUmo:
    """UMO 字符串解析"""

    def test_valid_umo(self):
        t = MessageTarget.from_umo("Flandre:FriendMessage:UID123")
        assert t is not None
        assert t.platform_id == "Flandre"
        assert t.session_type == "FriendMessage"
        assert t.session_id == "UID123"

    def test_session_id_with_colons(self):
        t = MessageTarget.from_umo("qq:GroupMessage:123:456:789")
        assert t is not None
        assert t.session_id == "123:456:789"

    def test_invalid_session_type(self):
        t = MessageTarget.from_umo(
            "Flandre:UnknownType:UID123", session_types={"FriendMessage"}
        )
        assert t is None

    def test_too_few_parts(self):
        assert MessageTarget.from_umo("Flandre:UID123") is None

    def test_empty(self):
        assert MessageTarget.from_umo("") is None
        assert MessageTarget.from_umo(None) is None

    def test_to_session_roundtrip(self):
        t = MessageTarget.from_umo("Flandre:FriendMessage:UID123")
        assert t.to_session() == "Flandre:FriendMessage:UID123"


class TestResolveTargetUsers:
    """目标用户解析归一化去重（修复重复发送的核心逻辑）"""

    UID = "D097688D60BFA4D7D716B66DB75BE662"
    UMO = f"Flandre:FriendMessage:{UID}"

    class _FakeCtx:
        class PM:
            def __init__(self):
                self.platform_insts = []

        platform_manager = PM()

    @staticmethod
    def _make_service(config_user_ids, default_user_id, known_users):
        async def fake_lookup():
            return known_users

        return MessagingService(
            TestResolveTargetUsers._FakeCtx(),
            {"user_ids": config_user_ids},
            users_lookup=fake_lookup,
            default_user_id=default_user_id,
        )

    def test_pure_id_and_umo_dedup(self):
        """配置含纯 ID + 同用户 UMO → 只解析出一个用户（核心修复点）"""
        ms = self._make_service([self.UID, self.UMO], None, [])
        result = asyncio.run(ms.resolve_target_users(include_known_users=True))
        assert result == [self.UID]

    def test_known_users_umo_dedup(self):
        """已知用户索引混入 UMO 与纯 ID → 去重"""
        ms = self._make_service([self.UID], None, [self.UID, self.UMO])
        result = asyncio.run(ms.resolve_target_users(include_known_users=True))
        assert result == [self.UID]

    def test_default_user_id_umo_normalized(self):
        """默认用户是 UMO 形式 → 归一化为 session_id"""
        ms = self._make_service([self.UMO], self.UMO, [])
        result = asyncio.run(ms.resolve_target_users(include_known_users=False))
        assert result == [self.UID]

    def test_multiple_users_sorted(self):
        """多个不同用户正确解析且排序"""
        ms = self._make_service(
            [self.UID, f"qq:GroupMessage:{self.UID}", "other_user_123"], None, []
        )
        result = asyncio.run(ms.resolve_target_users(include_known_users=False))
        assert set(result) == {self.UID, "other_user_123"}
        assert result == sorted(result)

    def test_no_known_users_when_disabled(self):
        """include_known_users=False 时不含已知用户"""
        ms = self._make_service([self.UID], None, ["known_user_1", "known_user_2"])
        result = asyncio.run(ms.resolve_target_users(include_known_users=False))
        assert result == [self.UID]


class _FakePlatform:
    """模拟平台实例（meta() 返回 id/name，用于平台类型映射）"""

    def __init__(self, pid: str, name: str):
        self._pid = pid
        self._name = name

    def meta(self):
        return SimpleNamespace(id=self._pid, name=self._name)


class TestBuildMarkdownChain:
    """主动推送 markdown 降级（QQ 官方适配器 send_by_session 不支持 use_markdown_）"""

    SAMPLE = (
        "早安喵~\n\n#### 📅 早安播报\n2026-08-16 周日\n\n"
        "**🌤️ 天气** 小雨 22°C\n\n| 时间 | 事项 |\n|------|------|\n| 09:00 | 组会 |"
    )

    class _FakeCtx:
        class PM:
            def __init__(self):
                self.platform_insts = [
                    _FakePlatform("Flandre", "qq_official"),
                    _FakePlatform("webchat", "webchat"),
                ]

        platform_manager = PM()

    def _service(self, md_enabled: bool = True) -> MessagingService:
        return MessagingService(
            self._FakeCtx(),
            {
                "markdown_enabled": md_enabled,
                "markdown_native_platforms": [],
                "qq_markdown_enabled": None,
            },
        )

    def test_proactive_qq_official_no_md_symbols(self):
        """主动推送 QQ 官方 → QQ 排版降级（无 md 符号，标题转【】）"""
        chain = self._service()._build_markdown_chain(
            self.SAMPLE, "Flandre", proactive=True
        )
        text = chain.chain[0].text
        assert "####" not in text
        assert "**" not in text
        assert "【📅 早安播报】" in text
        assert "时间：事项" in text  # 表格转键值

    def test_reply_qq_official_keeps_native(self):
        """被动回复 QQ 官方 → 保留 native（use_markdown_ 交给适配器渲染）"""
        chain = self._service()._build_markdown_chain(
            self.SAMPLE, "Flandre", proactive=False
        )
        assert getattr(chain, "use_markdown_", False) is True

    def test_proactive_webchat_still_strips(self):
        """主动推送 webchat → strip 干净文本（不受 QQ 降级影响）"""
        chain = self._service()._build_markdown_chain(
            self.SAMPLE, "webchat", proactive=True
        )
        text = chain.chain[0].text
        assert "####" not in text
        assert "**" not in text

    def test_proactive_md_disabled_keeps_raw(self):
        """markdown_enabled=False → 维持原文直发（配置语义不变）"""
        chain = self._service(md_enabled=False)._build_markdown_chain(
            self.SAMPLE, "Flandre", proactive=True
        )
        text = chain.chain[0].text
        assert "####" in text  # 原文直发
