"""Apple CalDAV 写操作状态码判定与发现降级路径测试。

覆盖：create_event 只在 2xx 返回 UID（401/403/404/重试耗尽的 500 不返回）、
delete_event 只在 2xx 返回 True、传输层异常视为失败、非法 uid 拒绝、
失败日志截断，_discover 两条正则降级路径拼出的 URL 主机正确，
以及 _discover / _list_calendars_with_status 按 HTTP 状态码判定失败并以 ERROR /
WARNING 报出可行动原因（同一原因只报一次，故不再出现"未配置 Apple 日历"这类误报）。
CalDAV 入口主机可配置，默认入口被 403 拒绝时回退中国大陆区入口；
_list_calendars_with_status 解析 displayname，并一次性列出「日历名 → UUID」。
读取完整性：get_all_events 交回（事件列表, 问题列表），任何一处没读全都记入问题
列表，供调用方判定"本轮不得删除本地日程"。
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

    async def _list_calendars_with_status():
        return (
            [{"id": "cal-uuid", "url": "https://x/cal-uuid", "href": "", "name": ""}],
            None,
        )

    monkeypatch.setattr(cal, "_list_calendars_with_status", _list_calendars_with_status)
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


class TestDiscoverFailureDiagnostics:
    """_discover 以 HTTP 状态码判定失败，并把可行动的原因报到 ERROR"""

    def test_403_empty_body_reports_actionable_reason(self, discoverable, caplog):
        """iCloud 凭据被拒时是 403 + 空响应体，原因只能来自状态码"""
        _FakeSession.statuses = [403, 403]
        _FakeSession.responses = ["", ""]

        # 插件日志走 astrbot 命名空间，其自身级别默认高于 DEBUG，需显式放开
        with caplog.at_level("DEBUG", logger="astrbot"):
            assert asyncio.run(discoverable._discover()) is False

        errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
        assert len(errors) == 1
        assert "403" in errors[0]
        assert "App 专用密码" in errors[0]
        # 凭据已填写却报"未配置 Apple 日历"是本次误报的根源，不得再出现
        assert not [r for r in caplog.records if "未配置 Apple 日历" in r.message]

    def test_403_with_principal_body_is_not_treated_as_success(
        self, discoverable, caplog
    ):
        """失败响应体里带着看似合法的 principal 路径时，不得据此认定发现成功"""
        # 入口由配置指定，就不触发中国大陆区回退，一次响应即可判定
        discoverable._caldav_entry_url = "https://p01-caldav.icloud.com.cn/"
        _FakeSession.statuses = [403]
        _FakeSession.responses = [
            '<D:multistatus xmlns:D="DAV:"><D:current-user-principal>'
            "<D:href>/1234567890/principal/</D:href>"
            "</D:current-user-principal></D:multistatus>"
        ]

        # 插件日志走 astrbot 命名空间，其自身级别默认高于 DEBUG，需显式放开
        with caplog.at_level("DEBUG", logger="astrbot"):
            assert asyncio.run(discoverable._discover()) is False

        # fail-closed：不再发起第二个 PROPFIND
        assert len(_FakeSession.calls) == 1
        assert any(
            r.levelname == "ERROR" and "403" in r.message for r in caplog.records
        )

    def test_same_reason_reports_error_once(self, discoverable, caplog):
        """同一原因只报一次 ERROR，之后降为 DEBUG（避免每轮同步刷屏）"""
        _FakeSession.statuses = [403, 403, 403, 403]
        _FakeSession.responses = ["", "", "", ""]

        # 插件日志走 astrbot 命名空间，其自身级别默认高于 DEBUG，需显式放开
        with caplog.at_level("DEBUG", logger="astrbot"):
            assert asyncio.run(discoverable._discover()) is False
            assert asyncio.run(discoverable._discover()) is False

        errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
        assert len(errors) == 1
        assert (
            len(
                [
                    r
                    for r in caplog.records
                    if r.levelname == "DEBUG" and "CalDAV 发现失败" in r.message
                ]
            )
            == 1
        )

    def test_transport_failure_reports_network_reason(
        self, discoverable, caplog, monkeypatch
    ):
        monkeypatch.setattr(apple_module.asyncio, "sleep", _no_sleep)
        _FakeSession.raise_error = apple_module.aiohttp.ClientError("boom")

        # 插件日志走 astrbot 命名空间，其自身级别默认高于 DEBUG，需显式放开
        with caplog.at_level("DEBUG", logger="astrbot"):
            assert asyncio.run(discoverable._discover()) is False

        errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
        assert len(errors) == 1
        assert "网络" in errors[0]

    def test_207_without_principal_reports_parse_failure(self, discoverable, caplog):
        _FakeSession.statuses = [207]
        _FakeSession.responses = ['<D:multistatus xmlns:D="DAV:"></D:multistatus>']

        # 插件日志走 astrbot 命名空间，其自身级别默认高于 DEBUG，需显式放开
        with caplog.at_level("DEBUG", logger="astrbot"):
            assert asyncio.run(discoverable._discover()) is False

        errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
        assert len(errors) == 1
        assert "principal URL" in errors[0]

    def test_success_after_failure_clears_reason(self, discoverable, caplog):
        """先失败后成功：失败态清空，同一原因下次再失败会重新报 ERROR"""
        # 指定入口主机则不回退，失败只需一次响应
        discoverable._caldav_entry_url = "https://p01-caldav.icloud.com.cn/"
        _FakeSession.statuses = [403, 207, 207]
        _FakeSession.responses = [
            "",
            '<D:multistatus xmlns:D="DAV:"><D:current-user-principal>'
            "<D:href>/1234567890/principal/</D:href>"
            "</D:current-user-principal></D:multistatus>",
            '<D:multistatus xmlns:D="DAV:"><D:calendar-home-set>'
            "<D:href>/1234567890/calendars/</D:href>"
            "</D:calendar-home-set></D:multistatus>",
        ]

        # 插件日志走 astrbot 命名空间，其自身级别默认高于 DEBUG，需显式放开
        with caplog.at_level("DEBUG", logger="astrbot"):
            assert asyncio.run(discoverable._discover()) is False
            assert asyncio.run(discoverable._discover()) is True

        assert discoverable._last_discover_reason is None
        assert discoverable._caldav_base_url == (
            "https://p01-caldav.icloud.com.cn/1234567890/calendars"
        )

    def test_create_event_pairs_reason_error_with_skip_warning(
        self, discoverable, caplog
    ):
        """用户可见两条：原因 ERROR（来自 _discover）+ 本次动作被跳过的 WARNING"""
        _FakeSession.statuses = [403, 403]
        _FakeSession.responses = ["", ""]

        # 插件日志走 astrbot 命名空间，其自身级别默认高于 DEBUG，需显式放开
        with caplog.at_level("DEBUG", logger="astrbot"):
            assert (
                asyncio.run(
                    discoverable.create_event("组会", datetime(2026, 9, 10, 9, 0))
                )
                is None
            )

        errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
        warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert len(errors) == 1 and "403" in errors[0]
        assert warnings == ["[AppleCalendar] CalDAV 未连接，无法创建事件"]

    def test_401_reports_missing_credentials(self, discoverable, caplog):
        """401 的文案指向"邮箱/App 专用密码是否填全"，且不触发国区回退"""
        _FakeSession.statuses = [401]
        _FakeSession.responses = [""]

        # 插件日志走 astrbot 命名空间，其自身级别默认高于 DEBUG，需显式放开
        with caplog.at_level("DEBUG", logger="astrbot"):
            assert asyncio.run(discoverable._discover()) is False

        errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
        assert len(errors) == 1
        assert "401" in errors[0] and "凭据" in errors[0]
        # 只有 403 才回退中国大陆区入口
        assert len(_FakeSession.calls) == 1

    def test_other_status_reports_status_and_body(self, discoverable, caplog):
        """其余状态码走泛化文案：带上状态码与被截断的响应体"""
        _FakeSession.statuses = [404]
        _FakeSession.responses = ["<html>not found</html>"]

        # 插件日志走 astrbot 命名空间，其自身级别默认高于 DEBUG，需显式放开
        with caplog.at_level("DEBUG", logger="astrbot"):
            assert asyncio.run(discoverable._discover()) is False

        errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
        assert len(errors) == 1
        assert "PROPFIND 返回 HTTP 404" in errors[0]
        assert "not found" in errors[0]


class TestListCalendarsDiagnostics:
    """_list_calendars 失败时报出状态码，并把失败原因交回调用方"""

    def test_non_207_is_reported_with_status(self, discoverable, caplog):
        discoverable._discovered = True
        discoverable._caldav_base_url = "https://caldav.icloud.com/123/calendars"
        _FakeSession.statuses = [403]
        _FakeSession.responses = [""]

        with caplog.at_level("WARNING"):
            calendars, issue = asyncio.run(discoverable._list_calendars_with_status())

        assert calendars == []
        assert issue and "403" in issue
        warnings = [r.message for r in caplog.records if "列出日历失败" in r.message]
        assert len(warnings) == 1
        assert "403" in warnings[0]


_PRINCIPAL_XML = (
    '<D:multistatus xmlns:D="DAV:"><D:current-user-principal>'
    "<D:href>/1234567890/principal/</D:href>"
    "</D:current-user-principal></D:multistatus>"
)

_HOME_XML = (
    '<D:multistatus xmlns:D="DAV:"><D:calendar-home-set>'
    "<D:href>/1234567890/calendars/</D:href>"
    "</D:calendar-home-set></D:multistatus>"
)

_UUID_A = "D6B0E7A1-1111-2222-3333-444455556666"
_UUID_B = "0A1B2C3D-AAAA-BBBB-CCCC-DDDDEEEEFFFF"

_CALENDARS_XML = (
    '<D:multistatus xmlns:D="DAV:">'
    f"<D:response><D:href>/1234567890/calendars/{_UUID_A}/</D:href>"
    "<D:propstat><D:prop><D:displayname>工作日</D:displayname></D:prop></D:propstat>"
    "</D:response>"
    f"<D:response><D:href>/1234567890/calendars/{_UUID_B}/</D:href>"
    "<D:propstat><D:prop><D:displayname>中国节假日</D:displayname></D:prop>"
    "</D:propstat></D:response>"
    "</D:multistatus>"
)


class TestCaldavHostConfig:
    """CalDAV 入口主机可配置；默认入口被 403 拒绝时回退中国大陆区入口"""

    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            ("", apple_module.CALDAV_ENTRY_URL),
            ("   ", apple_module.CALDAV_ENTRY_URL),
            ("caldav.icloud.com.cn", "https://caldav.icloud.com.cn/"),
            ("https://p01-caldav.icloud.com.cn", "https://p01-caldav.icloud.com.cn/"),
            ("https://p01-caldav.icloud.com.cn/", "https://p01-caldav.icloud.com.cn/"),
        ],
    )
    def test_entry_url_is_normalized(self, host, expected):
        assert AppleCalendar._normalize_entry_url(host) == expected

    def test_configured_host_is_used(self, discoverable):
        discoverable._caldav_entry_url = AppleCalendar._normalize_entry_url(
            "p01-caldav.icloud.com.cn"
        )
        _FakeSession.statuses = [207, 207]
        _FakeSession.responses = [_PRINCIPAL_XML, _HOME_XML]

        assert asyncio.run(discoverable._discover()) is True
        assert [c["url"] for c in _FakeSession.calls] == [
            "https://p01-caldav.icloud.com.cn/",
            "https://p01-caldav.icloud.com.cn/1234567890/principal",
        ]

    def test_default_entry_403_falls_back_to_cn(self, discoverable, caplog):
        """默认入口 403：同一份凭据再试国区入口，并在日志里写明生效入口"""
        _FakeSession.statuses = [403, 207, 207]
        _FakeSession.responses = ["", _PRINCIPAL_XML, _HOME_XML]

        # 插件日志走 astrbot 命名空间，其自身级别默认高于 DEBUG，需显式放开
        with caplog.at_level("DEBUG", logger="astrbot"):
            assert asyncio.run(discoverable._discover()) is True

        assert discoverable._caldav_entry_url == apple_module.CALDAV_CN_ENTRY_URL
        assert [c["url"] for c in _FakeSession.calls] == [
            apple_module.CALDAV_ENTRY_URL,
            apple_module.CALDAV_CN_ENTRY_URL,
            "https://caldav.icloud.com.cn/1234567890/principal",
        ]
        assert any(
            r.levelname == "INFO" and "中国大陆区" in r.message for r in caplog.records
        )

    def test_configured_host_403_does_not_fall_back(self, discoverable):
        """入口由用户指定时不再替他改主机，只报失败"""
        discoverable._caldav_entry_url = AppleCalendar._normalize_entry_url(
            "p01-caldav.icloud.com.cn"
        )
        _FakeSession.statuses = [403]
        _FakeSession.responses = [""]

        assert asyncio.run(discoverable._discover()) is False
        assert len(_FakeSession.calls) == 1

    def test_both_entries_403_reports_both_tried(self, discoverable, caplog):
        _FakeSession.statuses = [403, 403]
        _FakeSession.responses = ["", ""]

        # 插件日志走 astrbot 命名空间，其自身级别默认高于 DEBUG，需显式放开
        with caplog.at_level("DEBUG", logger="astrbot"):
            assert asyncio.run(discoverable._discover()) is False

        assert len(_FakeSession.calls) == 2
        errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
        assert len(errors) == 1
        assert "403" in errors[0]
        assert "中国大陆区" in errors[0]


class TestCalendarsListing:
    """列出日历时解析 displayname，并在首次列出时给出「日历名 → UUID」对照"""

    @staticmethod
    def _ready(cal):
        cal._discovered = True
        cal._caldav_base_url = "https://caldav.icloud.com/1234567890/calendars"

    def test_displayname_is_attached_to_uuid(self, discoverable):
        self._ready(discoverable)
        _FakeSession.statuses = [207]
        _FakeSession.responses = [_CALENDARS_XML]

        calendars, issue = asyncio.run(discoverable._list_calendars_with_status())

        assert issue is None
        assert [c["id"] for c in calendars] == [_UUID_A, _UUID_B]
        assert [c["name"] for c in calendars] == ["工作日", "中国节假日"]

    def test_uuid_listing_is_logged_once(self, discoverable, caplog):
        self._ready(discoverable)
        _FakeSession.statuses = [207, 207]
        _FakeSession.responses = [_CALENDARS_XML, _CALENDARS_XML]

        # 插件日志走 astrbot 命名空间，其自身级别默认高于 DEBUG，需显式放开
        with caplog.at_level("DEBUG", logger="astrbot"):
            asyncio.run(discoverable._list_calendars_with_status())
            # 绕过日历缓存再列一次：对照清单仍只应出现一次
            discoverable._calendars_cache = []
            discoverable._calendars_ts = 0.0
            asyncio.run(discoverable._list_calendars_with_status())

        listings = [r.message for r in caplog.records if "可用日历" in r.message]
        assert len(listings) == 1
        assert "工作日" in listings[0]
        assert _UUID_A in listings[0]


_CAL_ONE = {
    "id": _UUID_A,
    "url": "https://p01-caldav.icloud.com.cn/1/calendars/x",
    "href": "",
    "name": "日程",
}

_ICS_LIST_XML = (
    '<D:multistatus xmlns:D="DAV:">'
    "<D:response><D:href>/1/calendars/x/a.ics</D:href></D:response>"
    "<D:response><D:href>/1/calendars/x/b.ics</D:href></D:response>"
    "</D:multistatus>"
)

_ICS_BODY = (
    "BEGIN:VCALENDAR\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:ics-a\r\n"
    "SUMMARY:组会\r\n"
    "DTSTART:20300101T120000Z\r\n"
    "DTEND:20300101T130000Z\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


class TestReadCompleteness:
    """读取完整性：任何一处没读全都要进问题列表，供调用方判定本轮不得删除"""

    @staticmethod
    def _patch(monkeypatch, cal, calendars, list_issue, fetch_result):
        async def _listing():
            return calendars, list_issue

        async def _fetch(cal_url):
            return fetch_result

        monkeypatch.setattr(cal, "_list_calendars_with_status", _listing)
        monkeypatch.setattr(cal, "_caldav_fetch_with_status", _fetch)

    def test_clean_read_has_no_issues(self, discoverable, monkeypatch):
        evt = {"uid": "u1", "summary": "组会"}
        self._patch(monkeypatch, discoverable, [_CAL_ONE], None, ([evt], None))

        events, issues = asyncio.run(discoverable.get_all_events(days=1))

        assert [e["uid"] for e in events] == ["u1"]
        assert issues == []

    def test_listing_failure_is_reported(self, discoverable, monkeypatch):
        self._patch(monkeypatch, discoverable, [], "CalDAV 未连接", ([], None))

        events, issues = asyncio.run(discoverable.get_all_events(days=1))

        assert events == []
        assert issues == ["CalDAV 未连接"]

    def test_calendar_fetch_failure_is_prefixed_with_calendar_name(
        self, discoverable, monkeypatch
    ):
        """局部失败也要点名是哪个日历，日志里能直接定位"""
        evt = {"uid": "u1", "summary": "组会"}
        self._patch(
            monkeypatch,
            discoverable,
            [_CAL_ONE],
            None,
            ([evt], "抓取日历事件失败（status=403）"),
        )

        events, issues = asyncio.run(discoverable.get_all_events(days=1))

        # 已读到的事件仍然交回，只是标记本轮不完整
        assert [e["uid"] for e in events] == ["u1"]
        assert issues == ["日程: 抓取日历事件失败（status=403）"]

    def test_empty_calendar_is_not_an_issue(self, discoverable, monkeypatch):
        """日历确实是空的（207、零事件文件）不算读取不完整"""
        self._patch(monkeypatch, discoverable, [_CAL_ONE], None, ([], None))

        events, issues = asyncio.run(discoverable.get_all_events(days=1))

        assert events == []
        assert issues == []

    def test_webcal_failure_is_reported(self, discoverable, monkeypatch):
        self._patch(monkeypatch, discoverable, [_CAL_ONE], None, ([], None))

        async def _webcal(url):
            return [], "WebCal 读取失败"

        monkeypatch.setattr(discoverable, "fetch_webcal_with_status", _webcal)
        discoverable.webcal_urls = ["https://example.com/cal.ics"]

        events, issues = asyncio.run(discoverable.get_all_events(days=1))

        assert events == []
        assert issues == ["WebCal 读取失败"]

    def test_issues_are_cached_for_next_round(self, discoverable, monkeypatch):
        """问题列表随事件一起进缓存：30 分钟内重复调用不会误判为读干净了"""
        calls = []

        async def _listing():
            return [_CAL_ONE], None

        async def _fetch(cal_url):
            calls.append(cal_url)
            return [], "抓取日历事件失败（status=403）"

        monkeypatch.setattr(discoverable, "_list_calendars_with_status", _listing)
        monkeypatch.setattr(discoverable, "_caldav_fetch_with_status", _fetch)

        first_events, first_issues = asyncio.run(discoverable.get_all_events(days=1))
        second_events, second_issues = asyncio.run(discoverable.get_all_events(days=1))

        assert first_events == second_events == []
        assert second_issues == first_issues == ["日程: 抓取日历事件失败（status=403）"]
        assert len(calls) == 1

    def test_discover_failure_makes_listing_report_not_connected(self, discoverable):
        """未连接时列日历交回原因，而不是静默空列表"""
        _FakeSession.statuses = [403, 403]
        _FakeSession.responses = ["", ""]

        calendars, issue = asyncio.run(discoverable._list_calendars_with_status())

        assert calendars == []
        assert issue == "CalDAV 未连接"

    def test_calendar_propfind_non_207_reports_status(self, discoverable):
        _FakeSession.statuses = [403]
        _FakeSession.responses = [""]

        events, issue = asyncio.run(
            discoverable._caldav_fetch_with_status("https://x/1/calendars/x")
        )

        assert events == []
        assert issue == "抓取日历事件失败（status=403）"

    def test_single_ics_failure_counts_as_incomplete(self, discoverable):
        """一个 .ics 拉到、另一个没拉到：仍有事件可用，但必须标记不完整"""
        _FakeSession.statuses = [207, 200, 200]
        _FakeSession.responses = [_ICS_LIST_XML, _ICS_BODY, ""]

        events, issue = asyncio.run(
            discoverable._caldav_fetch_with_status("https://x/1/calendars/x")
        )

        assert [e["uid"] for e in events] == ["ics-a"]
        assert issue == "1/2 个事件文件未拉到"
