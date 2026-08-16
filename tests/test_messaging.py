"""
消息服务测试：UMO 解析与目标用户归一化去重

测试 MessageTarget.from_umo 的解析规则，以及
resolve_target_users 对纯 ID / UMO 混存场景的去重（修复重复发送的关键）。
包环境由 conftest.py 模拟。
"""

import asyncio

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
