"""Apple CalDAV 写操作状态码判定与发现降级路径测试。

覆盖：create_event 只在 2xx 返回 UID（401/403/404/重试耗尽的 500 不返回）、
delete_event 只在 2xx 返回 True、传输层异常视为失败、非法 uid 拒绝、
失败日志截断，以及 _discover 两条正则降级路径拼出的 URL 主机正确。
aiohttp 会话用最小替身，不产生真实网络请求。
"""

import asyncio
from datetime import datetime

import pytest

import apple_calendar as apple_module
from apple_calendar import AppleCalendar


class _FakeResponse:
    """aiohttp 响应替身：只需 status / text()"""

    def __init__(self, status: int, body: str = ""):
        self.status = status
        self._body = body
        self.request_info = None
        self.history = ()

    async def text(self, encoding="utf-8", errors="replace"):
        return self._body


class _FakeRequest:
    """session.request(...) 返回的异步上下文管理器"""

    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    """aiohttp.ClientSession 替身，按调用顺序吐出预设响应"""

    responses: list = []
    statuses: list = []
    calls: list = []
    raise_error: Exception | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def request(self, method, url, **kwargs):
        type(self).calls.append({"method": method, "url": url, "kwargs": kwargs})
        if type(self).raise_error is not None:
            raise type(self).raise_error
        status = type(self).statuses.pop(0)
        body = ""
        if type(self).responses:
            body = type(self).responses.pop(0)
        return _FakeRequest(_FakeResponse(status, body))


@pytest.fixture
def caldav(monkeypatch):
    """已"发现"完毕的 AppleCalendar，网络层换成 _FakeSession"""
    _FakeSession.responses = []
    _FakeSession.statuses = []
    _FakeSession.calls = []
    _FakeSession.raise_error = None
    monkeypatch.setattr(apple_module.aiohttp, "ClientSession", _FakeSession)

    cal = AppleCalendar("user@example.com", "app-pass")
    cal._discovered = True
    cal._caldav_base_url = "https://caldav.icloud.com/123/calendars"

    async def _list_calendars():
        return [{"id": "cal-uuid", "url": "https://x/cal-uuid", "href": "", "name": ""}]

    monkeypatch.setattr(cal, "_list_calendars", _list_calendars)
    return cal


@pytest.fixture
def discoverable(monkeypatch):
    """未发现状态的 AppleCalendar，网络层换成 _FakeSession（用于 _discover 测试）"""
    _FakeSession.responses = []
    _FakeSession.statuses = []
    _FakeSession.calls = []
    _FakeSession.raise_error = None
    monkeypatch.setattr(apple_module.aiohttp, "ClientSession", _FakeSession)
    return AppleCalendar("user@example.com", "app-pass")


class TestDiscoverFallback:
    """_extract_href 解析不出时走正则降级：拼出的 URL 主机必须是 iCloud 而非数字 DSID"""

    def test_principal_regex_fallback_keeps_icloud_host(self, discoverable):
        # 降级正则带 $ 锚：路径必须正好落在响应体末尾，故用只有路径的正文
        _FakeSession.statuses = [207, 207]
        _FakeSession.responses = [
            "<html>您的用户名为 1234567890，请访问 /1234567890/principal",
            # 同样只有路径：压到第三层相对路径正则而非绝对 URL 分支
            "<html><D:href>/1234567890/123/calendars/",
        ]

        assert asyncio.run(discoverable._discover()) is True
        # 精确断言：主机仍是 caldav.icloud.com（"//1234567890/…" 会把 host 变成 DSID）
        assert discoverable._principal_url == (
            "https://caldav.icloud.com/1234567890/principal"
        )
        # 相对路径以 principal 为基准解析（urljoin 语义：替换最后一段）
        assert discoverable._caldav_base_url == (
            "https://caldav.icloud.com/123/calendars"
        )
        # 第二个 PROPFIND 必须打到 principal 路径，而不是 DSID 主机
        assert [c["url"] for c in _FakeSession.calls] == [
            "https://caldav.icloud.com/",
            "https://caldav.icloud.com/1234567890/principal",
        ]

    def test_calendar_home_regex_fallback_keeps_icloud_host(self, discoverable):
        # principal 走 XML 正常路径，calendar-home-set 用"只有路径"的降级正则
        _FakeSession.statuses = [207, 207]
        _FakeSession.responses = [
            '<D:multistatus xmlns:D="DAV:"><D:current-user-principal>'
            "<D:href>/1234567890/principal/</D:href>"
            "</D:current-user-principal></D:multistatus>",
            "<html><D:href>/1234567890/calendars/",
        ]

        assert asyncio.run(discoverable._discover()) is True
        assert discoverable._principal_url == (
            "https://caldav.icloud.com/1234567890/principal"
        )
        assert discoverable._caldav_base_url == (
            "https://caldav.icloud.com/1234567890/calendars"
        )
        assert [c["url"] for c in _FakeSession.calls] == [
            "https://caldav.icloud.com/",
            "https://caldav.icloud.com/1234567890/principal",
        ]


class TestCreateEventStatus:
    def test_201_returns_uid(self, caldav):
        _FakeSession.statuses = [201]
        uid = asyncio.run(caldav.create_event("组会", datetime(2026, 9, 10, 9, 0)))
        assert uid
        assert _FakeSession.calls[0]["method"] == "PUT"
        assert _FakeSession.calls[0]["url"].endswith(f"/{uid}.ics")

    @pytest.mark.parametrize("status", [401, 403, 404, 500])
    def test_non_2xx_returns_none(self, caldav, monkeypatch, status):
        # 4xx/5xx 同样会带回非空响应体，故"收到响应"不能作为写入成功的判据
        monkeypatch.setattr(apple_module.asyncio, "sleep", _no_sleep)
        _FakeSession.statuses = [status, status, status]
        _FakeSession.responses = ["<html>error</html>"] * 3
        assert (
            asyncio.run(caldav.create_event("组会", datetime(2026, 9, 10, 9, 0)))
            is None
        )

    def test_existing_uid_is_reused_for_update(self, caldav):
        _FakeSession.statuses = [201]
        uid = asyncio.run(
            caldav.create_event("改后标题", datetime(2026, 9, 11, 9, 0), uid="uid-keep")
        )
        assert uid == "uid-keep"
        assert _FakeSession.calls[0]["url"].endswith("/uid-keep.ics")
        # 同一 UID 的 PUT 覆盖原事件，而不是新建一份
        assert b"UID:uid-keep" in _FakeSession.calls[0]["kwargs"]["data"]

    def test_empty_uid_is_rejected(self, caldav, caplog):
        """空 uid 既非新建也非有效更新：拒绝执行，避免"更新"被静默降级成新建"""
        for bad_uid in ("", "   "):
            with caplog.at_level("WARNING"):
                assert (
                    asyncio.run(
                        caldav.create_event(
                            "组会", datetime(2026, 9, 10, 9, 0), uid=bad_uid
                        )
                    )
                    is None
                )
        # 不发起任何请求（未写出第二条事件）
        assert _FakeSession.calls == []
        assert any("非法 uid" in r.message for r in caplog.records)

    def test_non_string_falsy_uid_is_rejected(self, caldav, caplog):
        """守卫与赋值口径一致：0/False 这类非 None 的假值不能被当成"新建"放行"""
        for bad_uid in (0, False, 0.0):
            with caplog.at_level("WARNING"):
                assert (
                    asyncio.run(
                        caldav.create_event(
                            "组会", datetime(2026, 9, 10, 9, 0), uid=bad_uid
                        )
                    )
                    is None
                )
        assert _FakeSession.calls == []
        assert any("非法 uid" in r.message for r in caplog.records)

    def test_failure_log_truncates_body(self, caldav, monkeypatch, caplog):
        """失败日志截断响应体：状态码保留，整页 HTML 错误页不进日志"""
        monkeypatch.setattr(apple_module.asyncio, "sleep", _no_sleep)
        _FakeSession.statuses = [500, 500, 500]
        _FakeSession.responses = ["x" * 5000] * 3

        with caplog.at_level("WARNING"):
            asyncio.run(caldav.create_event("组会", datetime(2026, 9, 10, 9, 0)))

        warnings = [r.message for r in caplog.records if "创建事件失败" in r.message]
        assert len(warnings) == 1
        assert "status=500" in warnings[0]
        assert "truncated" in warnings[0]
        assert len(warnings[0]) < 500

    def test_transport_error_returns_none(self, caldav, monkeypatch):
        monkeypatch.setattr(apple_module.asyncio, "sleep", _no_sleep)
        _FakeSession.raise_error = apple_module.aiohttp.ClientError("boom")
        assert (
            asyncio.run(caldav.create_event("组会", datetime(2026, 9, 10, 9, 0)))
            is None
        )


class TestDeleteEventStatus:
    def test_204_returns_true(self, caldav):
        _FakeSession.statuses = [204]
        assert asyncio.run(caldav.delete_event("uid-1")) is True

    @pytest.mark.parametrize("status", [401, 403, 404])
    def test_non_2xx_returns_false(self, caldav, status):
        # DELETE 成功体是空串，4xx 体也可能是空串：必须按状态码判定
        _FakeSession.statuses = [status]
        _FakeSession.responses = [""]
        assert asyncio.run(caldav.delete_event("uid-1")) is False


async def _no_sleep(_seconds):
    return None


class TestRequestWrapper:
    """_aiohttp_request 保持既有契约（只返回文本），不破坏其它调用点"""

    def test_non_2xx_body_still_returned(self, caldav):
        _FakeSession.statuses = [404]
        _FakeSession.responses = ["<html>nf</html>"]
        assert asyncio.run(caldav._aiohttp_request("https://x/y")) == "<html>nf</html>"

    def test_status_helper_exposes_status(self, caldav):
        _FakeSession.statuses = [403]
        _FakeSession.responses = ["forbidden"]
        result = asyncio.run(caldav._aiohttp_request_with_status("https://x/y"))
        assert result == ("forbidden", 403)

    def test_transport_failure_is_none(self, caldav, monkeypatch):
        monkeypatch.setattr(apple_module.asyncio, "sleep", _no_sleep)
        _FakeSession.raise_error = apple_module.aiohttp.ClientError("boom")
        assert asyncio.run(caldav._aiohttp_request("https://x/y")) is None
        assert _FakeSession.calls and len(_FakeSession.calls) == 3  # 重试耗尽
