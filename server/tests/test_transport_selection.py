# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Transport selection (auto/json2/jsonrpc/xmlrpc), replay rules and the deprecation notice."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fake_odoo_http import FakeOdoo, html_reply, json_reply, version_payload

from odoo_mcp.config import Settings
from odoo_mcp.errors import AuthError, ConfigError, OdooFault, RateLimited, TransportError
from odoo_mcp.registry import ToolContext, registry
from odoo_mcp.session import OdooSession
from odoo_mcp.telemetry import build_optin_payload
from odoo_mcp.tenancy import ConnectionManager
from odoo_mcp.tools.meta import odoo_version
from odoo_mcp.transport.base import parse_retry_after, retry_delay
from odoo_mcp.transport.fallback import (
    DEPRECATION,
    KINDS,
    LEGACY,
    READ_METHODS,
    FallbackTransport,
    deprecation_notice,
    select_order,
    series_of,
)
from odoo_mcp.transport.json2 import Json2Unavailable
from odoo_mcp.transport.jsonrpc import ApiKeyRejected, JsonRpcTransport, JsonRpcUnavailable
from odoo_mcp.transport.xmlrpc import XmlRpcTransport

KEY = "K3Y-DO-NOT-LEAK-0123456789abcdef01234567"

# --- the auto policy for every (S, K, U) -------------------------------------

ORDER_TABLE = [
    # series, kind, userinfo, expected order (or ConfigError)
    (None, "api_key", False, LEGACY),  # unknown series: today's order
    ((10, 0), "password", False, LEGACY),
    ((17, 0), "api_key", False, LEGACY),
    ((18, 0), "api_key", False, LEGACY),
    ((18, 3), "api_key", False, LEGACY),  # saas~18.3 has no JSON-2
    ((18, 4), "api_key", False, KINDS),
    ((18, 4), "password", False, LEGACY),
    ((18, 4), "api_key", True, LEGACY),
    ((19, 0), "api_key", False, KINDS),
    ((19, 0), "password", False, LEGACY),
    ((19, 0), "api_key", True, LEGACY),
    ((19, 4), "api_key", False, KINDS),
    ((20, 0), "api_key", False, KINDS),  # a clamped 20.0 target keeps its raw series here
    ((21, 0), "api_key", False, KINDS),  # on-premise 21.0 still has the legacy endpoints
    ((21, 0), "password", False, LEGACY),
    ((21, 1), "api_key", False, ("json2",)),  # Online saas~21.1: legacy removed
    ((22, 0), "api_key", False, ("json2",)),
    ((21, 1), "password", False, ConfigError),
    ((22, 0), "api_key", True, ConfigError),
    ((22, 0), "password", True, ConfigError),
]


@pytest.mark.parametrize(("series", "kind", "userinfo", "expected"), ORDER_TABLE)
def test_auto_order(series: tuple[int, int] | None, kind: str, userinfo: bool,
                    expected: Any) -> None:
    if expected is ConfigError:
        with pytest.raises(ConfigError, match="ODOO_API_KEY|user:pass@"):
            select_order("auto", series, kind, userinfo)
    else:
        assert select_order("auto", series, kind, userinfo) == expected


@pytest.mark.parametrize(("pref", "series", "kind", "userinfo", "expected"), [
    ("json2", None, "api_key", False, ("json2",)),
    ("json2", (19, 0), "api_key", False, ("json2",)),
    ("json2", (18, 4), "api_key", False, ("json2",)),
    ("json2", (18, 0), "api_key", False, ConfigError),  # needs saas~18.4 / 19.0+
    ("json2", None, "password", False, ConfigError),
    ("json2", None, "api_key", True, ConfigError),
    ("jsonrpc", (19, 0), "password", False, ("jsonrpc",)),
    ("xmlrpc", (17, 0), "api_key", False, ("xmlrpc",)),
    ("xmlrpc", (21, 1), "api_key", False, ConfigError),
    ("jsonrpc", (22, 0), "password", False, ConfigError),
])
def test_explicit_preferences(pref: str, series: Any, kind: str, userinfo: bool,
                              expected: Any) -> None:
    if expected is ConfigError:
        with pytest.raises(ConfigError):
            select_order(pref, series, kind, userinfo)
    else:
        assert select_order(pref, series, kind, userinfo) == expected


@pytest.mark.parametrize(("payload", "series"), [
    (version_payload(), (19, 0)),
    ({"server_version": "saas~18.4+e", "server_version_info": ["saas~18", 4, 0, "final", 0, "e"]},
     (18, 4)),
    ({"server_version": "20.0alpha1"}, (20, 0)),
    ({"server_version": "19.0-20260926"}, (19, 0)),
    ({"server_version": "junk"}, None),
    ("not a dict", None),
])
def test_series_is_parsed_unclamped(payload: Any, series: Any) -> None:
    assert series_of(payload) == series


# --- stubs --------------------------------------------------------------------


class _Stub:
    """A transport that records calls and raises or answers from a script."""

    def __init__(self, *outcomes: Any, version: dict | None = None) -> None:
        self.outcomes = list(outcomes) or ["ok"]
        self.calls: list[tuple[str, tuple, dict]] = []
        self._version = version

    def _next(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((name, args, kwargs))
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def version(self) -> Any:
        if self._version is not None:
            self.calls.append(("version", (), {}))
            return self._version
        return self._next("version")

    def authenticate(self, *args: Any) -> Any:
        return self._next("authenticate", *args)

    def execute_kw(self, *args: Any, **kwargs: Any) -> Any:
        return self._next("execute_kw", *args, **kwargs)


def _wire(pref: str = "auto", kind: str = "api_key", *, series: str | None = "19.0",
          j2: _Stub | None = None, js: _Stub | None = None, xs: _Stub | None = None,
          url: str = "https://odoo.example") -> tuple[FallbackTransport, _Stub, _Stub, _Stub]:
    sleeps: list[float] = []
    fb = FallbackTransport(url, timeout=5, pref=pref, secret_kind=kind, sleep=sleeps.append)
    fb.sleeps = sleeps  # type: ignore[attr-defined]
    j2 = j2 or _Stub(2)
    js = js or _Stub(2)
    xs = xs or _Stub(2)
    fb._j2, fb._json, fb._xml = j2, js, xs  # type: ignore[assignment]
    if series:
        fb._remember_version({"server_version": series})
    return fb, j2, js, xs


# --- sign-in and pinning ------------------------------------------------------


def test_json2_is_pinned_after_the_first_sign_in() -> None:
    fb, j2, js, xs = _wire()
    assert fb.active == "json2(auto)"
    assert fb.authenticate("db", "admin", KEY) == 2
    assert fb.active == "json2"
    j2.outcomes = [Json2Unavailable("json2: HTTP 404")]
    with pytest.raises(Json2Unavailable):  # pinned: no switch to the legacy endpoints
        fb.execute_kw("db", 2, KEY, "res.partner", "create", [{}])
    assert js.calls == [] and xs.calls == []


def test_unavailable_json2_falls_back_and_pins_the_one_that_answers(
        caplog: pytest.LogCaptureFixture) -> None:
    fb, j2, js, xs = _wire(j2=_Stub(Json2Unavailable("json2: HTTP 404 (text/html)")))
    with caplog.at_level(logging.WARNING, logger="odoo_mcp.transport"):
        assert fb.authenticate("db", "admin", KEY) == 2
        fb.execute_kw("db", 2, KEY, "res.partner", "search_read", [[]], {})
        fb.execute_kw("db", 2, KEY, "res.partner", "search_read", [[]], {})
    assert fb.active == "jsonrpc"
    assert (len(j2.calls), len(js.calls), len(xs.calls)) == (1, 3, 0)
    falls = [r for r in caplog.records if "falling back" in r.getMessage()]
    assert len(falls) == 1 and "JSON-RPC" in falls[0].getMessage()
    notice = fb.transport_notice
    assert notice and notice.startswith(DEPRECATION) and "/json/2" in notice


def test_bad_api_key_is_never_replayed_on_legacy() -> None:
    fb, _j2, js, xs = _wire(j2=_Stub(AuthError("JSON-2 refused the API key")))
    with pytest.raises(AuthError):
        fb.authenticate("db", "admin", KEY)
    assert js.calls == [] and xs.calls == []


def test_legacy_sign_in_keeps_the_auto_order() -> None:
    fb, j2, js, _xs = _wire(kind="password", series="17.0")
    fb.authenticate("db", "admin", "pw")
    assert fb.active == "jsonrpc(auto)" and j2.calls == []
    js.outcomes = [ApiKeyRejected("api key rejected")]
    fb.execute_kw("db", 2, "pw", "res.partner", "read", [[1]], {})
    assert fb.active == "xmlrpc"  # the fallback still works within the legacy pair


def test_a_forced_preference_never_switches() -> None:
    fb, j2, _js, xs = _wire(pref="jsonrpc", kind="api_key",
                           js=_Stub(JsonRpcUnavailable("jsonrpc: HTTP 404")))
    with pytest.raises(JsonRpcUnavailable):
        fb.execute_kw("db", 2, KEY, "res.partner", "create", [{}])
    assert xs.calls == [] and j2.calls == [] and fb.active == "jsonrpc"


def test_pref_json2_needs_an_api_key_and_no_basic_auth_before_any_request() -> None:
    fb, j2, js, xs = _wire(pref="json2", kind="password", series=None)
    with pytest.raises(ConfigError, match="ODOO_API_KEY"):
        fb.authenticate("db", "admin", "pw")
    fb, j2, js, xs = _wire(pref="json2", series=None, url="https://gw:pw@odoo.example")
    with pytest.raises(ConfigError, match="user:pass@"):
        fb.execute_kw("db", 2, KEY, "res.partner", "read", [[1]])
    assert j2.calls == js.calls == xs.calls == []


def test_pref_json2_on_an_older_series_is_a_clear_config_error() -> None:
    fb, j2, _js, _xs = _wire(pref="json2", series="18.0")
    with pytest.raises(ConfigError, match=r"saas~18\.4 / 19\.0.*ODOO_TRANSPORT_PREF=auto"):
        fb.authenticate("db", "admin", KEY)
    assert j2.calls == []


def test_pref_json2_unavailable_suggests_auto() -> None:
    fb, _j2, js, xs = _wire(pref="json2", j2=_Stub(Json2Unavailable("json2: HTTP 404")))
    with pytest.raises(Json2Unavailable, match="ODOO_TRANSPORT_PREF=auto"):
        fb.authenticate("db", "admin", KEY)
    assert js.calls == [] and xs.calls == []


def test_password_on_saas_21_1_is_a_config_error_at_sign_in() -> None:
    fb, _j2, js, xs = _wire(kind="password", series="saas~21.1")
    with pytest.raises(ConfigError, match="ODOO_API_KEY"):
        fb.authenticate("db", "admin", "pw")
    assert js.calls == [] and xs.calls == []


def test_saas_21_1_with_an_api_key_uses_json2_only() -> None:
    fb, _j2, js, xs = _wire(series="saas~21.1", j2=_Stub(Json2Unavailable("json2: HTTP 404")))
    with pytest.raises(Json2Unavailable):
        fb.authenticate("db", "admin", KEY)
    assert js.calls == [] and xs.calls == []


# --- replay rules ---------------------------------------------------------------


def test_a_write_is_not_replayed_after_an_uncertain_json2_error() -> None:
    # not signed in yet, so the auto order still lists the legacy endpoints
    fb, _j2, js, xs = _wire(j2=_Stub(TransportError("json2 transport error: timed out")))
    with pytest.raises(TransportError, match="may or may not have been applied"):
        fb.execute_kw("db", 2, KEY, "res.partner", "create", [{}])
    assert js.calls == [] and xs.calls == []


def test_a_read_is_replayed_after_an_uncertain_json2_error() -> None:
    fb, _j2, js, _xs = _wire(j2=_Stub(TransportError("json2: HTTP 502 without an Odoo body")))
    assert fb.execute_kw("db", 2, KEY, "res.partner", "search_read", [[]]) == 2
    assert len(js.calls) == 1 and fb.active == "jsonrpc"


def test_an_unavailable_json2_write_is_safe_to_replay() -> None:
    fb, _j2, js, _xs = _wire(j2=_Stub(Json2Unavailable("json2: HTTP 415")))
    assert fb.execute_kw("db", 2, KEY, "res.partner", "create", [{}]) == 2
    assert len(js.calls) == 1


def test_odoo_faults_are_never_replayed() -> None:
    fb, _j2, js, xs = _wire(j2=_Stub(OdooFault("odoo.exceptions.ValidationError: no")))
    with pytest.raises(OdooFault):
        fb.execute_kw("db", 2, KEY, "res.partner", "search_read", [[]])
    assert js.calls == [] and xs.calls == []


def test_429_on_a_read_waits_and_retries_the_same_transport_without_pinning() -> None:
    fb, j2, js, _xs = _wire(j2=_Stub(RateLimited("429", retry_after=4), RateLimited("429"), [1]))
    assert fb.execute_kw("db", 2, KEY, "res.partner", "search", [[]]) == [1]
    assert fb.sleeps == [4.0, 10.0]  # type: ignore[attr-defined]  # Retry-After, then default
    assert len(j2.calls) == 3 and js.calls == [] and fb.active != "jsonrpc"


def test_429_gives_up_after_three_tries() -> None:
    fb, _j2, js, _xs = _wire(j2=_Stub(RateLimited("429", retry_after=99)))
    with pytest.raises(RateLimited, match="still rate limited after 3 tries"):
        fb.execute_kw("db", 2, KEY, "res.partner", "search", [[]])
    assert fb.sleeps == [30.0, 30.0]  # type: ignore[attr-defined]  # capped
    assert js.calls == []


def test_429_on_a_write_is_reported_not_retried() -> None:
    fb, j2, js, xs = _wire(j2=_Stub(RateLimited("json2: HTTP 429", retry_after=1)))
    with pytest.raises(RateLimited, match="refused the call"):
        fb.execute_kw("db", 2, KEY, "res.partner", "write", [[1], {}])
    assert len(j2.calls) == 1 and fb.sleeps == []  # type: ignore[attr-defined]
    assert js.calls == [] and xs.calls == []


def test_429_on_jsonrpc_no_longer_pins_xmlrpc() -> None:
    fb, _j2, _js, xs = _wire(kind="password", series="17.0",
                           js=_Stub(RateLimited("jsonrpc: HTTP 429"), [3]))
    assert fb.execute_kw("db", 2, "pw", "res.partner", "search", [[]]) == [3]
    assert xs.calls == [] and fb.active == "jsonrpc(auto)"


def test_read_methods_include_the_new_reads() -> None:
    assert {"formatted_read_group", "web_read_group", "context_get", "has_access",
            "has_groups", "get_field_translations"} <= READ_METHODS
    assert not {"create", "write", "unlink", "load", "execute_import"} & READ_METHODS


def test_retry_after_parsing() -> None:
    assert parse_retry_after("12") == 12.0
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412470.0) == 10.0
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412490.0) == 0.0
    assert parse_retry_after("soon") is None and parse_retry_after(None) is None
    assert retry_delay(None) == 10.0 and retry_delay(500) == 30.0 and retry_delay(-1) == 0.0


# --- ids on every transport -----------------------------------------------------


@pytest.mark.parametrize("kind", ["json2", "jsonrpc", "xmlrpc"])
def test_execute_ids_reach_every_transport(kind: str) -> None:
    fb, j2, js, xs = _wire(pref=kind, kind="api_key")
    fb.execute_kw("db", 2, KEY, "res.partner", "copy", [], {"default": {}}, ids=[7])
    stub = {"json2": j2, "jsonrpc": js, "xmlrpc": xs}[kind]
    _name, args, kwargs = stub.calls[-1]
    if kind == "json2":
        assert args[5:] == ([], {"default": {}}) and kwargs == {"ids": [7]}
    else:  # the classic execute_kw form: ids first
        assert args[5:] == ([[7]], {"default": {}}) and kwargs == {}


# --- the deprecation notice ------------------------------------------------------


@pytest.mark.parametrize(("pref", "kind", "userinfo", "active", "series", "hint"), [
    ("auto", "password", False, "jsonrpc", (19, 0), "Create an API key"),
    ("auto", "api_key", True, "jsonrpc", (19, 0), "Basic auth in ODOO_URL"),
    ("xmlrpc", "api_key", False, "xmlrpc", (19, 0), "ODOO_TRANSPORT_PREF=auto or json2"),
    ("auto", "api_key", False, "xmlrpc", (19, 2), "/json/2"),
])
def test_notice_texts(pref: str, kind: str, userinfo: bool, active: str,
                      series: tuple[int, int], hint: str) -> None:
    notice = deprecation_notice(pref, series, kind, userinfo, active)
    assert notice and notice.startswith(DEPRECATION) and hint in notice


@pytest.mark.parametrize(("series", "active"), [((18, 0), "jsonrpc"), ((18, 4), "xmlrpc"),
                                                ((19, 0), "json2"), (None, "jsonrpc")])
def test_no_notice_before_19_or_on_json2(series: Any, active: str) -> None:
    assert deprecation_notice("auto", series, "password", False, active) is None


def test_the_notice_is_logged_exactly_once(caplog: pytest.LogCaptureFixture) -> None:
    fb, j2, _js, _xs = _wire(kind="password")
    with caplog.at_level(logging.WARNING, logger="odoo_mcp.transport"):
        fb.authenticate("db", "admin", "pw")
        for _ in range(3):
            fb.execute_kw("db", 2, "pw", "res.partner", "search", [[]])
    notices = [r for r in caplog.records if DEPRECATION in r.getMessage()]
    assert len(notices) == 1 and j2.calls == []
    assert fb.transport_notice and "ODOO_API_KEY" in fb.transport_notice


# --- end to end over HTTP: probe order and zero legacy calls on 19.0 -------------


@pytest.fixture
def fake() -> Iterator[FakeOdoo]:
    server = FakeOdoo()
    try:
        yield server
    finally:
        server.close()


def _session(fake: FakeOdoo, *, api_key: str = "", password: str = "",
             pref: str = "auto") -> OdooSession:
    settings = Settings(url=fake.url, db="db", login="admin", api_key=api_key,
                        password=password, transport_pref=pref, timeout=5)
    return ConnectionManager(settings).default()


def test_auto_on_19_with_an_api_key_never_calls_the_legacy_endpoints(fake: FakeOdoo) -> None:
    fake.serve_version()
    fake.serve_json2(lambda model, method, body: 0 if method == "search_count" else None)
    fake.on("POST", "/jsonrpc", html_reply(500))
    session = _session(fake, api_key=KEY)
    result = odoo_version(ToolContext(session=session, manager=None), {})
    assert result["transport"] == "json2" and result["transport_notice"] is None
    assert result["version"] == 19 and result["edition"] == "community"
    assert fake.paths() == ["/web/webclient/version_info", "/json/2/res.users/context_get",
                            "/json/2/res.users/read", "/json/2/ir.module.module/search_count"]
    assert not fake.calls("/jsonrpc") and not fake.calls("/xmlrpc")


def test_auto_on_19_with_a_password_stays_legacy_with_the_notice(
        fake: FakeOdoo, caplog: pytest.LogCaptureFixture) -> None:
    fake.serve_version()
    fake.serve_jsonrpc(lambda model, method, args, kwargs: 0)
    session = _session(fake, password="pw")
    with caplog.at_level(logging.WARNING, logger="odoo_mcp.transport"):
        result = odoo_version(ToolContext(session=session, manager=None), {})
        session.execute("res.partner", "search_count", [[]])
    assert result["transport"] == "jsonrpc(auto)"
    assert result["transport_notice"] and "Create an API key" in result["transport_notice"]
    assert len([r for r in caplog.records if DEPRECATION in r.getMessage()]) == 1
    assert not fake.calls("/json/2/")
    # the version came from the web probe, not from a logged common.version call
    assert fake.paths()[0] == "/web/webclient/version_info"
    assert all(r["body"]["params"]["method"] != "version" for r in fake.calls("/jsonrpc"))


def test_auto_on_18_stays_legacy_without_a_notice(fake: FakeOdoo) -> None:
    fake.serve_version("18.0-20260908", [18, 0, 0, "final", 0, ""])
    fake.serve_jsonrpc(lambda model, method, args, kwargs: 0)
    session = _session(fake, api_key=KEY)
    result = odoo_version(ToolContext(session=session, manager=None), {})
    assert result["transport"] == "jsonrpc(auto)" and result["transport_notice"] is None
    assert not fake.calls("/json/2/")


def test_the_version_probe_order_ends_with_common_version(fake: FakeOdoo) -> None:
    fake.on("GET", "/json/version", html_reply(404))
    fake.serve_jsonrpc(version={"server_version": "17.0",
                                "server_version_info": [17, 0, 0, "final", 0, ""]})
    fb = FallbackTransport(fake.url, timeout=5, pref="auto", secret_kind="api_key")
    assert fb.version()["server_version"] == "17.0"
    fb.version()  # cached: no second probe
    assert fake.paths() == ["/web/webclient/version_info", "/json/version", "/jsonrpc"]


def test_jsonrpc_pref_keeps_common_version(fake: FakeOdoo) -> None:
    fake.serve_version()
    fake.serve_jsonrpc()
    fb = FallbackTransport(fake.url, timeout=5, pref="jsonrpc", secret_kind="password")
    fb.version()
    assert fake.paths() == ["/jsonrpc"]


def test_login_mismatch_through_the_session(fake: FakeOdoo) -> None:
    fake.serve_version()
    fake.serve_json2(login="demo", uid=6)
    session = _session(fake, api_key=KEY)
    with pytest.raises(AuthError, match="another Odoo user"):
        odoo_version(ToolContext(session=session, manager=None), {})
    assert not fake.calls("/jsonrpc")


def test_odoo_execute_ids_over_json2_end_to_end(fake: FakeOdoo) -> None:
    fake.serve_version()
    seen: list[tuple[str, str, dict]] = []

    def orm(model: str, method: str, body: dict) -> Any:
        seen.append((model, method, body))
        return 0 if method == "search_count" else [99]

    fake.serve_json2(orm)
    session = _session(fake, api_key=KEY)
    ctx = ToolContext(session=session, manager=None)
    tool = registry.get("odoo_execute")
    out = tool.handler(ctx, {"model": "res.partner", "method": "copy", "ids": [7],
                             "kwargs": {"default": {"name": "Copy"}}})
    assert out["result"] == [99]
    assert seen[-1] == ("res.partner", "copy", {"ids": [7], "default": {"name": "Copy"}})


# --- config and credentials -----------------------------------------------------


def test_json2_is_a_valid_preference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ODOO_TRANSPORT_PREF", "JSON2")
    assert Settings.from_env().transport_pref == "json2"
    monkeypatch.setenv("ODOO_TRANSPORT_PREF", "json3")
    assert Settings.from_env().transport_pref == "auto"


def test_the_credential_kind_comes_from_the_settings() -> None:
    both = ConnectionManager(Settings(url="https://o.example", db="d", login="l",
                                      api_key=KEY, password="pw")).default()
    assert both.creds.secret_kind == "api_key" and both.transport.secret_kind == "api_key"
    pw = ConnectionManager(Settings(url="https://o.example", db="d", login="l",
                                    password="pw")).default()
    assert pw.creds.secret_kind == "password"
    assert "secret_kind" not in repr(both.creds) and KEY not in repr(both.creds)
    assert both.creds.fingerprint() == "https://o.example|d|l"


def test_telemetry_knows_the_json2_label() -> None:
    payload = build_optin_payload(odoo_version_major=19, transport="json2")
    assert payload["transport"] == "json2"


def test_legacy_transports_map_429_to_rate_limited(fake: FakeOdoo) -> None:
    fake.on("POST", "/jsonrpc", html_reply(429, b"slow", **{"Retry-After": "2"}))
    with pytest.raises(RateLimited) as info:
        JsonRpcTransport(fake.url, timeout=5).version()
    assert info.value.retry_after == 2.0
    fake.on("POST", "/xmlrpc/2/common", html_reply(429, b"slow", **{"Retry-After": "5"}))
    with pytest.raises(RateLimited) as info:
        XmlRpcTransport(fake.url, timeout=5).version()
    assert info.value.retry_after == 5.0


def test_api_doc_is_offered_only_where_it_can_work(fake: FakeOdoo) -> None:
    fake.on("GET", "/doc-bearer/res.partner.json", json_reply(200, {"methods": {}}))
    fb = FallbackTransport(fake.url, timeout=5, secret_kind="api_key")
    assert fb.api_doc("db", KEY, "res.partner") is None  # series unknown
    fb._remember_version({"server_version": "saas~18.4"})
    assert fb.api_doc("db", KEY, "res.partner") is None  # no api_doc module before 19.0
    assert fb.json2_available and fake.seen == []
    fb._remember_version({"server_version": "19.0"})
    assert fb.api_doc("db", KEY, "res.partner") == {"methods": {}}
    assert fake.paths() == ["/doc-bearer/res.partner.json"]
    pw = FallbackTransport(fake.url, timeout=5, secret_kind="password")
    pw._remember_version({"server_version": "19.0"})
    assert pw.api_doc("db", "pw", "res.partner") is None and not pw.json2_available


def test_a_failed_first_detection_is_retried_at_the_next_sign_in() -> None:
    fb, j2, js, _xs = _wire(series=None, j2=_Stub(Json2Unavailable("down")),
                            js=_Stub(TransportError("down")))
    fb._xml = _Stub(TransportError("down"))  # type: ignore[assignment]
    with pytest.raises(TransportError):
        fb.authenticate("db", "admin", KEY)
    assert fb.series is None
    legacy_calls = len(js.calls)
    # the server is back: the next sign-in probes again and picks JSON-2
    j2.outcomes, j2._version = [2], version_payload()
    assert fb.authenticate("db", "admin", KEY) == 2
    assert fb.series == (19, 0) and fb.active == "json2"
    assert len(js.calls) == legacy_calls  # no legacy call this time


def test_odoo_execute_says_it_writes_and_accepts_ids() -> None:
    tool = registry.get("odoo_execute")
    assert not tool.read_only
    assert "(write operation)" in tool.description
    assert "refused in read-only mode (ODOO_READONLY)" in tool.description
    assert tool.input_schema["properties"]["ids"] == {
        "type": "array", "items": {"type": "integer"},
        "description": tool.input_schema["properties"]["ids"]["description"]}
    assert tool.input_schema["required"] == ["model", "method"]  # ids stays optional
    from odoo_mcp.server import check_readonly

    with pytest.raises(Exception, match="ODOO_READONLY"):
        check_readonly(Settings(readonly=True), tool)
