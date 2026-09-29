# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Regression tests for the v1.2.0 review: session lock, transports, fallback, TLS, config."""

from __future__ import annotations

import base64
import gzip
import json
import os
import socket
import ssl
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import pytest

from odoo_mcp.config import Settings
from odoo_mcp.errors import TransportError
from odoo_mcp.session import Credentials, OdooSession
from odoo_mcp.transport import base as tls_base
from odoo_mcp.transport.fallback import FallbackTransport
from odoo_mcp.transport.json2 import Json2Unavailable
from odoo_mcp.transport.jsonrpc import JsonRpcTransport, JsonRpcUnavailable, split_userinfo
from odoo_mcp.transport.xmlrpc import XmlRpcTransport

SECRET = "PW-DO-NOT-LEAK"

# --- OdooSession: facts() on a Community instance must not deadlock ----------


class _CommunityTransport:
    def version(self) -> dict[str, Any]:
        return {"server_version": "16.0", "server_version_info": [16, 0, 0, "final", 0, ""]}

    def authenticate(self, db: str, login: str, secret: str) -> int:
        return 2

    def execute_kw(self, db: str, uid: int, secret: str, model: str, method: str,
                   args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        return 0  # module not installed


def test_facts_on_a_cold_community_session_does_not_deadlock() -> None:
    session = OdooSession(Credentials("https://odoo.example", "db", "me", "k"), timeout=5)
    session.transport = _CommunityTransport()  # type: ignore[assignment]
    result: dict[str, Any] = {}
    worker = threading.Thread(target=lambda: result.update(facts=session.facts()), daemon=True)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive(), "OdooSession.facts() deadlocked on a Community payload"
    assert result["facts"].version == 16


# --- a tiny HTTP server with scripted replies --------------------------------


class _Handler(BaseHTTPRequestHandler):
    status: ClassVar[int] = 200
    body: ClassVar[bytes] = b"{}"
    headers_out: ClassVar[dict[str, str]] = {}
    seen: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:  # http.server calls this by name
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        _Handler.seen.append({"path": self.path, "auth": self.headers.get("Authorization"),
                              "accept_encoding": self.headers.get("Accept-Encoding")})
        self.send_response(_Handler.status)
        for key, value in {"Content-Length": str(len(_Handler.body)),
                           **_Handler.headers_out}.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(_Handler.body)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def http_odoo() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Handler.status, _Handler.body, _Handler.headers_out, _Handler.seen = 200, b"{}", {}, []
    try:
        yield f"127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _script(status: int, body: bytes, **headers: str) -> None:
    _Handler.status, _Handler.body, _Handler.headers_out = status, body, headers


OK_VERSION = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"server_version": "17.0"}}).encode()


def test_basic_auth_userinfo_is_sent_as_a_header_and_never_echoed(http_odoo: str) -> None:
    _script(200, OK_VERSION)
    transport = JsonRpcTransport(f"http://bauser:{SECRET}@{http_odoo}", timeout=5)
    assert SECRET not in transport.base_url
    assert transport.version() == {"server_version": "17.0"}
    expected = "Basic " + base64.b64encode(f"bauser:{SECRET}".encode()).decode()
    assert _Handler.seen[-1]["auth"] == expected
    assert split_userinfo("https://odoo.example") == ("https://odoo.example", None)


def test_errors_never_carry_the_basic_auth_password() -> None:
    for url in (f"https://bauser:{SECRET}@odoo.invalid", f"http://u:{SECRET}@127.0.0.1:9"):
        with pytest.raises(TransportError) as info:
            JsonRpcTransport(url, timeout=2).version()
        assert SECRET not in str(info.value)
    assert SECRET not in repr(Settings(url=f"https://u:{SECRET}@odoo.example"))


def test_redirects_are_refused_not_followed(http_odoo: str) -> None:
    _script(302, b"", Location=f"http://{http_odoo}/elsewhere")
    with pytest.raises(JsonRpcUnavailable, match="302"):
        JsonRpcTransport(f"http://{http_odoo}", timeout=5).version()
    assert len(_Handler.seen) == 1  # no second (GET) request


def test_gzip_replies_are_decoded(http_odoo: str) -> None:
    _script(200, gzip.compress(OK_VERSION), **{"Content-Encoding": "gzip"})
    assert JsonRpcTransport(f"http://{http_odoo}", timeout=5).version()["server_version"] == "17.0"
    assert "gzip" in _Handler.seen[-1]["accept_encoding"]


@pytest.mark.parametrize(
    ("status", "body", "unavailable"),
    [(404, b"no", True), (403, b"waf", True), (200, b"<html>", False),
     (502, b"bad gateway", False), (500, b"{}", False)],
)
def test_failure_classification(http_odoo: str, status: int, body: bytes,
                                unavailable: bool) -> None:
    _script(status, body)
    with pytest.raises(TransportError) as info:
        JsonRpcTransport(f"http://{http_odoo}", timeout=5).version()
    assert isinstance(info.value, JsonRpcUnavailable) is unavailable


def _raw_server(reply: bytes) -> tuple[str, socket.socket]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)

    def serve() -> None:
        conn, _ = sock.accept()
        conn.recv(65536)
        conn.sendall(reply)
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return f"http://127.0.0.1:{sock.getsockname()[1]}", sock


@pytest.mark.parametrize(
    "reply",
    [b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{\"jsonrpc\"",  # truncated body
     b"GARBAGE-NOT-HTTP\r\n\r\n"],
)
def test_cut_or_garbled_replies_are_transport_errors(reply: bytes) -> None:
    url, sock = _raw_server(reply)
    try:
        with pytest.raises(TransportError):
            JsonRpcTransport(url, timeout=5).version()
    finally:
        sock.close()


def test_xmlrpc_protocol_errors_are_mapped_without_the_password(http_odoo: str) -> None:
    _script(502, b"bad gateway")
    transport = XmlRpcTransport(f"http://bauser:{SECRET}@{http_odoo}", timeout=5)
    with pytest.raises(TransportError) as info:
        transport.version()
    assert "HTTP 502" in str(info.value)
    assert SECRET not in str(info.value)


# --- FallbackTransport: never replay a call that may have run -----------------


class _Stub:
    def __init__(self, exc: Exception | None = None, result: Any = "ok") -> None:
        self.exc, self.result, self.calls = exc, result, 0

    def _do(self, *args: Any) -> Any:
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result

    version = authenticate = execute_kw = _do


def _fallback(json_exc: Exception, pref: str = "auto") -> tuple[FallbackTransport, _Stub, _Stub]:
    fb = FallbackTransport("https://odoo.example", timeout=5, pref=pref)
    js, xs = _Stub(json_exc), _Stub()
    fb._json, fb._xml = js, xs  # type: ignore[assignment]
    # The no-log version probes (web client, /json/version) find nothing here.
    fb._j2 = _Stub(Json2Unavailable("json2: HTTP 404"))  # type: ignore[assignment]
    return fb, js, xs


def test_uncertain_write_is_not_replayed_over_xmlrpc() -> None:
    fb, js, xs = _fallback(TransportError("jsonrpc: HTTP 502 Bad Gateway"))
    with pytest.raises(TransportError, match="may or may not have been applied"):
        fb.execute_kw("db", 2, "k", "res.partner", "create", [{}])
    assert (js.calls, xs.calls) == (1, 0)


def test_unavailable_jsonrpc_falls_back_and_pins_xmlrpc() -> None:
    fb, js, xs = _fallback(JsonRpcUnavailable("jsonrpc: HTTP 404 Not Found"))
    assert fb.execute_kw("db", 2, "k", "res.partner", "create", [{}]) == "ok"
    assert fb.execute_kw("db", 2, "k", "res.partner", "create", [{}]) == "ok"
    assert (js.calls, xs.calls, fb.active) == (1, 2, "xmlrpc")


def test_idempotent_calls_fall_back_after_uncertain_errors_and_pin_xmlrpc() -> None:
    fb, js, xs = _fallback(TransportError("timed out"))
    fb._remember_version({"server_version": "17.0"})  # sign-in detects the series first
    assert fb.authenticate("db", "me", "k") == "ok"
    assert fb.active == "xmlrpc"  # JSON-RPC failed where XML-RPC works
    assert fb.execute_kw("db", 2, "k", "res.partner", "create", [{}]) == "ok"
    assert (js.calls, xs.calls) == (1, 2)


@pytest.mark.parametrize("method", ["search_read", "read", "fields_get", "search_count"])
def test_reads_fall_back_after_uncertain_errors(method: str) -> None:
    fb, js, xs = _fallback(TransportError("jsonrpc: HTTP 502 Bad Gateway"))
    assert fb.execute_kw("db", 2, "k", "res.partner", method, [[]]) == "ok"
    assert (js.calls, xs.calls) == (1, 1)


def test_garbled_2xx_reply_is_uncertain_so_a_write_is_not_replayed(http_odoo: str) -> None:
    _script(200, b"<html>proxy page</html>")
    fb = FallbackTransport(f"http://{http_odoo}", timeout=5)
    xs = _Stub()
    fb._xml = xs  # type: ignore[assignment]
    with pytest.raises(TransportError, match="may or may not have been applied"):
        fb.execute_kw("db", 2, "k", "res.partner", "create", [{}])
    assert xs.calls == 0


def test_forced_jsonrpc_is_never_switched_to_xmlrpc() -> None:
    fb, _js, xs = _fallback(JsonRpcUnavailable("jsonrpc: HTTP 404"), pref="jsonrpc")
    with pytest.raises(JsonRpcUnavailable):
        fb.version()
    assert xs.calls == 0 and fb.active == "jsonrpc"


# --- TLS trust and config -------------------------------------------------------


def test_os_bundle_is_loaded_when_python_has_no_ca_file(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = next((b for b in tls_base._OS_CA_BUNDLES if os.path.isfile(b)), None)
    if bundle is None:
        pytest.skip("no OS CA bundle on this machine")
    empty = ssl.DefaultVerifyPaths(None, None, "SSL_CERT_FILE", "/nonexistent",  # type: ignore[call-arg]
                                   "SSL_CERT_DIR", "/nonexistent")
    monkeypatch.setattr(ssl, "get_default_verify_paths", lambda: empty)
    monkeypatch.setattr(ssl.SSLContext, "load_default_certs", lambda self, purpose=None: None)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "certifi", None)  # certifi absent
    assert tls_base.tls_context().cert_store_stats()["x509_ca"] > 0


def test_timeout_defaults_to_120_and_accepts_plugin_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ODOO_TIMEOUT", raising=False)
    assert Settings.from_env().timeout == 120
    monkeypatch.setenv("ODOO_TIMEOUT", "90.0")
    assert Settings.from_env().timeout == 90
    monkeypatch.setenv("ODOO_TIMEOUT", "${user_config.odoo_timeout}")
    assert Settings.from_env().timeout == 120


def test_malformed_urls_and_numbers_never_crash_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "<unparseable ODOO_URL>" in repr(Settings(url="http://["))
    assert split_userinfo("http://[") == ("http://[", None)
    with pytest.raises(JsonRpcUnavailable):
        JsonRpcTransport("http://[", timeout=2).version()
    for raw in ("inf", "-inf", "nan", "1e9999"):
        monkeypatch.setenv("ODOO_TIMEOUT", raw)
        assert Settings.from_env().timeout == 120
