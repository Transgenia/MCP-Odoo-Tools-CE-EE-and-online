# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""JSON-2 transport against canned HTTP replies: requests, results and every error row."""

from __future__ import annotations

import gzip
import json
import logging
import socket
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from fake_odoo_http import (
    DEBUG_MARKER,
    NOT_FOUND_NODB,
    FakeOdoo,
    html_reply,
    json_reply,
    jsonrpc_result,
    odoo_error,
    version_payload,
)

from odoo_mcp.errors import (
    AuthError,
    CompatError,
    ConfigError,
    OdooFault,
    RateLimited,
    TransportError,
)
from odoo_mcp.transport.json2 import Json2Transport, Json2Unavailable, check_names
from odoo_mcp.transport.jsonrpc import JsonRpcUnavailable

KEY = "K3Y-DO-NOT-LEAK-0123456789abcdef01234567"


@pytest.fixture
def fake() -> Iterator[FakeOdoo]:
    server = FakeOdoo()
    try:
        yield server
    finally:
        server.close()


def _t(fake: FakeOdoo, **kw: Any) -> Json2Transport:
    transport = Json2Transport(fake.url, timeout=kw.pop("timeout", 5))
    transport.series = kw.pop("series", (19, 0))
    return transport


# --- request format ----------------------------------------------------------


def test_a_call_is_one_post_with_bearer_database_and_named_body(fake: FakeOdoo) -> None:
    fake.on("POST", "/json/2/res.partner/search_read", json_reply(200, [{"id": 1}]))
    rows = _t(fake).execute_kw("prod", 2, KEY, "res.partner", "search_read",
                               [[["is_company", "=", True]]],
                               {"fields": ["name"], "context": {"lang": "es_MX"}})
    assert rows == [{"id": 1}]
    sent = fake.seen[-1]
    headers = {k.lower(): v for k, v in sent["headers"].items()}
    assert sent["verb"] == "POST"
    assert headers["authorization"] == f"bearer {KEY}"
    assert headers["x-odoo-database"] == "prod"
    assert headers["content-type"] == "application/json"
    assert "cookie" not in headers and "accept-language" not in headers
    assert sent["body"] == {"domain": [["is_company", "=", True]], "fields": ["name"],
                            "context": {"lang": "es_MX"}}


def test_create_unwraps_a_single_id_but_not_a_list(fake: FakeOdoo) -> None:
    fake.on("POST", "/json/2/res.partner/create", json_reply(200, [42]))
    transport = _t(fake)
    assert transport.execute_kw("db", 2, KEY, "res.partner", "create", [{"name": "x"}]) == 42
    assert fake.seen[-1]["body"] == {"vals_list": {"name": "x"}}
    assert transport.execute_kw("db", 2, KEY, "res.partner", "create", [[{"name": "x"}]]) == [42]


def test_explicit_ids_and_gzip(fake: FakeOdoo) -> None:
    fake.on("POST", "/json/2/res.partner/copy",
            (200, {"Content-Type": "application/json", "Content-Encoding": "gzip"},
             gzip.compress(b"[9]")))
    assert _t(fake).execute_kw("db", 2, KEY, "res.partner", "copy", [], {"default": {}},
                               ids=[7]) == [9]
    assert fake.seen[-1]["body"] == {"ids": [7], "default": {}}
    assert "gzip" in fake.seen[-1]["headers"].get("Accept-Encoding", "")


def test_the_series_picks_the_parameter_names(fake: FakeOdoo) -> None:
    fake.on("POST", "/json/2/res.partner/default_get", json_reply(200, {"type": "contact"}))
    _t(fake, series=(18, 4)).execute_kw("db", 2, KEY, "res.partner", "default_get", [["type"]])
    assert fake.seen[-1]["body"] == {"fields_list": ["type"]}
    _t(fake, series=(19, 0)).execute_kw("db", 2, KEY, "res.partner", "default_get", [["type"]])
    assert fake.seen[-1]["body"] == {"fields": ["type"]}


@pytest.mark.parametrize(("model", "method"), [
    ("res partner", "read"), ("Res.Partner", "read"), ("res.partner", "_private"),
    ("res.partner", "bad name"), ("res.partner", "1read"), ("", "read"), ("res.partner", ""),
])
def test_names_are_validated_before_sending(fake: FakeOdoo, model: str, method: str) -> None:
    with pytest.raises(CompatError):
        _t(fake).execute_kw("db", 2, KEY, model, method, [])
    assert fake.seen == []  # nothing was sent


def test_check_names_accepts_real_names() -> None:
    check_names("x_custom.model_2", "action_confirm")
    check_names("ir.actions.report", "render_qweb_pdf")


# --- error mapping (one row each) --------------------------------------------


def test_invalid_apikey_is_an_auth_error(fake: FakeOdoo) -> None:
    fake.on("POST", "/json/2/res.partner/search_count",
            odoo_error(401, "werkzeug.exceptions.Unauthorized", "Invalid apikey"))
    with pytest.raises(AuthError, match="create a new API key") as info:
        _t(fake).execute_kw("db", 2, KEY, "res.partner", "search_count", [[]])
    assert KEY not in str(info.value) and DEBUG_MARKER not in str(info.value)


def test_a_dropped_authorization_header_is_unavailable_with_a_warning(
        fake: FakeOdoo, caplog: pytest.LogCaptureFixture) -> None:
    fake.on("POST", "/json/2/res.partner/search_count", odoo_error(
        401, "werkzeug.exceptions.Unauthorized",
        "User not authenticated, use an API Key with a Bearer Authorization header."))
    transport = _t(fake)
    with caplog.at_level(logging.WARNING, logger="odoo_mcp.transport"):
        for _ in range(2):
            with pytest.raises(Json2Unavailable, match="Authorization header"):
                transport.execute_kw("db", 2, KEY, "res.partner", "search_count", [[]])
    assert len([r for r in caplog.records if "Authorization header" in r.getMessage()]) == 1


@pytest.mark.parametrize(("status", "name"), [
    (400, "werkzeug.exceptions.BadRequest"),
    (403, "odoo.exceptions.AccessError"),
    (404, "werkzeug.exceptions.NotFound"),
    (404, "odoo.exceptions.MissingError"),
    (409, "odoo.exceptions.LockError"),
    (422, "werkzeug.exceptions.UnprocessableEntity"),
    (422, "odoo.exceptions.ValidationError"),
    (500, "builtins.ValueError"),
])
def test_odoo_error_bodies_are_faults_without_the_traceback(fake: FakeOdoo, status: int,
                                                            name: str) -> None:
    fake.on("POST", "/json/2/res.partner/write", odoo_error(status, name, "went wrong"))
    with pytest.raises(OdooFault) as info:
        _t(fake).execute_kw("db", 2, KEY, "res.partner", "write", [[1], {"name": "x"}])
    assert str(info.value) == f"{name}: went wrong"
    assert DEBUG_MARKER not in str(info.value) and "Traceback" not in str(info.value)


def test_the_nodb_page_is_a_config_error(fake: FakeOdoo) -> None:
    fake.on("POST", "/json/2/res.partner/search_count", html_reply(404, NOT_FOUND_NODB))
    with pytest.raises(ConfigError, match="ODOO_DB"):
        _t(fake).execute_kw("wrong_db", 2, KEY, "res.partner", "search_count", [[]])


@pytest.mark.parametrize("reply", [
    html_reply(303, b"", Location="/web/login?redirect=%2Fjson%2F2"),  # Odoo <= saas~18.3
    html_reply(405, b"<html>Method Not Allowed</html>"),
    html_reply(415, b"<html>Unsupported Media Type</html>"),
    html_reply(404, b"<html>proxy: no such path</html>"),
    html_reply(403, b"<html>WAF</html>"),
    json_reply(401, {"error": "gateway says no"}),  # JSON, but not an Odoo error body
])
def test_replies_that_never_reached_json2_are_unavailable(fake: FakeOdoo, reply: Any) -> None:
    fake.on("POST", "/json/2/res.partner/create", reply)
    with pytest.raises(Json2Unavailable) as info:
        _t(fake).execute_kw("db", 2, KEY, "res.partner", "create", [{"name": "x"}])
    assert isinstance(info.value, JsonRpcUnavailable)  # the fallback's "safe to replay" class
    assert len(fake.seen) == 1  # a redirect is not followed


def test_connect_errors_are_unavailable() -> None:
    transport = Json2Transport("http://127.0.0.1:9", timeout=2)
    with pytest.raises(Json2Unavailable):
        transport.execute_kw("db", 2, KEY, "res.partner", "search_count", [[]])


@pytest.mark.parametrize(("retry_after", "expected"), [("7", 7.0), (None, None), ("junk", None)])
def test_429_is_rate_limited_with_retry_after(fake: FakeOdoo, retry_after: str | None,
                                              expected: float | None) -> None:
    headers = {"Retry-After": retry_after} if retry_after else {}
    fake.on("POST", "/json/2/res.partner/search_count",
            html_reply(429, b"<html>slow down</html>", **headers))
    with pytest.raises(RateLimited) as info:
        _t(fake).execute_kw("db", 2, KEY, "res.partner", "search_count", [[]])
    assert info.value.retry_after == expected


@pytest.mark.parametrize("reply", [
    html_reply(502, b"<html>bad gateway</html>"),
    html_reply(500, b"<html>oops</html>"),
    (503, {"Content-Type": "application/json"}, b"{}"),  # JSON, but no Odoo error body
    html_reply(200, b"<html>login</html>"),  # 2xx that is not JSON
    (200, {"Content-Type": "application/json"}, b"{not json"),
])
def test_uncertain_outcomes_are_plain_transport_errors(fake: FakeOdoo, reply: Any) -> None:
    fake.on("POST", "/json/2/res.partner/create", reply)
    with pytest.raises(TransportError) as info:
        _t(fake).execute_kw("db", 2, KEY, "res.partner", "create", [{"name": "x"}])
    assert not isinstance(info.value, (JsonRpcUnavailable, RateLimited))


def _raw_server(reply: bytes | None) -> tuple[str, socket.socket]:
    """Accept one request, then send ``reply`` (``None``: never answer)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)

    def serve() -> None:
        conn, _ = sock.accept()
        conn.recv(65536)
        if reply is None:
            threading.Event().wait(5)
        else:
            conn.sendall(reply)
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return f"http://127.0.0.1:{sock.getsockname()[1]}", sock


@pytest.mark.parametrize("reply", [
    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n[1",
    b"GARBAGE-NOT-HTTP\r\n\r\n",
    None,  # sent, then no reply before the timeout
])
def test_cut_garbled_or_timed_out_replies_are_uncertain(reply: bytes | None) -> None:
    url, sock = _raw_server(reply)
    try:
        with pytest.raises(TransportError) as info:
            Json2Transport(url, timeout=1).execute_kw("db", 2, KEY, "res.partner", "create",
                                                      [{"name": "x"}])
        assert not isinstance(info.value, JsonRpcUnavailable)
    finally:
        sock.close()


def test_basic_auth_urls_cannot_use_json2(fake: FakeOdoo) -> None:
    url = fake.url.replace("http://", "http://gw:PW-NOT-LEAKED@")
    with pytest.raises(ConfigError, match="user:pass@") as info:
        Json2Transport(url, timeout=5).execute_kw("db", 2, KEY, "res.partner", "search", [[]])
    assert "PW-NOT-LEAKED" not in str(info.value) and fake.seen == []


# --- sign-in ------------------------------------------------------------------


def test_sign_in_reads_the_uid_then_checks_the_login(fake: FakeOdoo) -> None:
    fake.serve_json2(login="Admin@Example.com", uid=7)
    assert _t(fake).authenticate("db", "admin@example.com", KEY) == 7  # case-insensitive
    assert [r["path"] for r in fake.seen] == ["/json/2/res.users/context_get",
                                              "/json/2/res.users/read"]
    assert fake.seen[-1]["body"] == {"ids": [7], "fields": ["login"]}


def test_sign_in_refuses_a_key_of_another_user(fake: FakeOdoo) -> None:
    fake.serve_json2(login="demo", uid=6)
    with pytest.raises(AuthError, match="another Odoo user"):
        _t(fake).authenticate("db", "admin", KEY)


def test_sign_in_with_a_bad_key_is_an_auth_error(fake: FakeOdoo) -> None:
    fake.on("POST", "/json/2/res.users/context_get",
            odoo_error(401, "werkzeug.exceptions.Unauthorized", "Invalid apikey"))
    with pytest.raises(AuthError):
        _t(fake).authenticate("db", "admin", KEY)


def test_sign_in_without_a_uid_is_an_auth_error(fake: FakeOdoo) -> None:
    fake.on("POST", "/json/2/res.users/context_get", json_reply(200, {"lang": "en_US"}))
    with pytest.raises(AuthError, match="no user"):
        _t(fake).authenticate("db", "admin", KEY)


# --- version probes (no login, no deprecated endpoint) -----------------------


def test_version_prefers_the_web_client_route(fake: FakeOdoo) -> None:
    fake.serve_version()
    assert _t(fake).version()["server_version"] == "19.0-20260926"
    assert fake.paths() == ["/web/webclient/version_info"]
    assert fake.seen[0]["body"]["method"] == "call"


def test_version_falls_back_to_json_version(fake: FakeOdoo) -> None:
    fake.on("GET", "/json/version", json_reply(200, {
        "version_info": [19, 0, 0, "final", 0, ""], "version": "19.0-20260926"}))
    payload = _t(fake).version()
    assert payload["server_version_info"] == [19, 0, 0, "final", 0, ""]
    assert payload["server_serie"] == "19.0"
    assert fake.paths() == ["/web/webclient/version_info", "/json/version"]


def test_version_probes_that_both_fail_are_unavailable(fake: FakeOdoo) -> None:
    fake.on("GET", "/json/version", html_reply(303, b"", Location="/web/login"))
    with pytest.raises(Json2Unavailable, match="version probes failed"):
        _t(fake).version()


def test_version_probe_errors_in_the_envelope_do_not_count(fake: FakeOdoo) -> None:
    fake.on("POST", "/web/webclient/version_info",
            json_reply(200, {"jsonrpc": "2.0", "id": 1, "error": {"message": "x"}}))
    fake.on("GET", "/json/version", json_reply(404, {"name": "NotFound", "message": "x"}))
    with pytest.raises(Json2Unavailable):
        _t(fake).version()


def test_version_probe_sends_basic_auth_for_a_gateway(fake: FakeOdoo) -> None:
    fake.serve_version()
    url = fake.url.replace("http://", "http://gw:secret@")
    Json2Transport(url, timeout=5).version()
    assert fake.seen[-1]["headers"].get("Authorization", "").startswith("Basic ")


def test_version_probe_rate_limit(fake: FakeOdoo) -> None:
    fake.on("POST", "/web/webclient/version_info", html_reply(429, b"", **{"Retry-After": "3"}))
    with pytest.raises(RateLimited):
        _t(fake).version()


# --- /doc-bearer -----------------------------------------------------------------

DOC = {"model": "res.partner", "methods": {
    "get_formview_id": {"signature": "(access_uid=None)",
                        "parameters": {"access_uid": {"default": None}}, "api": []},
    "search": {"signature": "(domain, offset=0)", "parameters": {"domain": {}, "offset": {}},
               "api": ["model", "readonly"]},
    "sum_it": {"signature": "(a, *more, **kw)", "parameters": {
        "a": {}, "more": {"kind": "VAR_POSITIONAL"}, "kw": {"kind": "VAR_KEYWORD"}},
        "api": ["model"]},
}}


def test_doc_bearer_is_cached_and_revalidated_with_the_etag(fake: FakeOdoo) -> None:
    def doc(request: dict[str, Any]) -> Any:
        if request["headers"].get("If-None-Match") == '"v1"':
            return 304, {"ETag": '"v1"'}, b""
        return json_reply(200, DOC, ETag='"v1"')

    fake.on("GET", "/doc-bearer/res.partner.json", doc)
    transport = _t(fake)
    first = transport.api_doc("db", KEY, "res.partner")
    assert first == DOC
    assert transport.api_doc("db", KEY, "res.partner") == DOC  # 304 -> cached copy
    assert [r["headers"].get("If-None-Match") for r in fake.seen] == [None, '"v1"']
    assert fake.seen[0]["headers"]["Authorization"] == f"bearer {KEY}"


def test_positional_args_outside_the_table_use_doc_bearer(fake: FakeOdoo) -> None:
    fake.on("GET", "/doc-bearer/res.partner.json", json_reply(200, DOC))
    fake.on("POST", "/json/2/res.partner/get_formview_id", json_reply(200, 12))
    fake.on("POST", "/json/2/res.partner/sum_it", json_reply(200, 3))
    transport = _t(fake)
    assert transport.execute_kw("db", 2, KEY, "res.partner", "get_formview_id", [[1], 5]) == 12
    assert fake.seen[-1]["body"] == {"ids": [1], "access_uid": 5}
    transport.execute_kw("db", 2, KEY, "res.partner", "sum_it", [1])
    assert fake.seen[-1]["body"] == {"a": 1}  # model method: no ids; *more/**kw not named
    assert len(fake.calls("/doc-bearer/")) == 1  # fetched once per model


def test_without_doc_bearer_positional_args_ask_for_kwargs(fake: FakeOdoo) -> None:
    fake.on("GET", "/doc-bearer/res.partner.json", odoo_error(
        403, "odoo.exceptions.AccessError",
        "This page is only accessible to Technical Documentation users."))
    transport = _t(fake)
    with pytest.raises(CompatError, match="named arguments only"):
        transport.execute_kw("db", 2, KEY, "res.partner", "get_formview_id", [[1]])
    assert transport.api_doc("db", KEY, "res.partner") is None
    # no /doc-bearer before 19.0 (saas~18.4 has no api_doc module): no request at all
    old = _t(fake, series=(18, 4))
    with pytest.raises(CompatError):
        old.execute_kw("db", 2, KEY, "res.partner", "get_formview_id", [[1]])
    assert len(fake.calls("/doc-bearer/")) == 2  # the 403 fetch + the explicit api_doc call


def test_legacy_version_payload_shape_from_json_version() -> None:
    from odoo_mcp.transport.json2 import version_from_json_version

    assert version_from_json_version({"version": "saas~19.2", "version_info": [
        "saas~19", 2, 0, "final", 0, ""]})["server_serie"] == "saas~19.2"
    assert version_from_json_version({"nope": 1}) is None


def test_payload_helpers_do_not_leak_the_key(fake: FakeOdoo) -> None:
    fake.on("POST", "/json/2/res.partner/read", jsonrpc_result(version_payload()))
    transport = _t(fake)
    transport.execute_kw("db", 2, KEY, "res.partner", "read", [[1]])
    assert KEY not in repr(transport.__dict__.get("base_url"))
    assert KEY not in json.dumps(fake.seen[-1]["body"])
