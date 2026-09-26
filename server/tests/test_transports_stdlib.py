# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Standard-library transports: JSON-RPC over urllib, XML-RPC with a timeout."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import pytest

from odoo_mcp.errors import AuthError, OdooFault, TransportError
from odoo_mcp.transport.jsonrpc import ApiKeyRejected, JsonRpcTransport
from odoo_mcp.transport.xmlrpc import (
    XmlRpcTransport,
    _TimeoutSafeTransport,
    _TimeoutTransport,
)


class _Handler(BaseHTTPRequestHandler):
    # (status, body) the next request gets; the test sets it per call.
    reply: ClassVar[tuple[int, bytes]] = (200, b"{}")
    seen: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:  # http.server calls this by name
        length = int(self.headers.get("Content-Length", 0))
        _Handler.seen.append(
            {"path": self.path, "ctype": self.headers.get("Content-Type"),
             "body": json.loads(self.rfile.read(length))}
        )
        status, body = _Handler.reply
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:  # keep test output quiet
        pass


@pytest.fixture
def odoo() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _Handler.seen = []
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


def _reply(status: int, payload: Any) -> None:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    _Handler.reply = (status, body)


def test_jsonrpc_success_posts_a_jsonrpc_envelope(odoo: str) -> None:
    _reply(200, {"jsonrpc": "2.0", "id": 1, "result": {"server_version": "17.0"}})
    transport = JsonRpcTransport(odoo, timeout=5)
    assert transport.version() == {"server_version": "17.0"}
    sent = _Handler.seen[-1]
    assert sent["path"] == "/jsonrpc"
    assert sent["ctype"] == "application/json"
    assert sent["body"]["params"] == {"service": "common", "method": "version", "args": []}
    transport.close()


def test_jsonrpc_authenticate_and_execute(odoo: str) -> None:
    transport = JsonRpcTransport(odoo, timeout=5)
    _reply(200, {"jsonrpc": "2.0", "id": 1, "result": 7})
    assert transport.authenticate("db", "me", "secret") == 7
    _reply(200, {"jsonrpc": "2.0", "id": 2, "result": False})
    with pytest.raises(AuthError):
        transport.authenticate("db", "me", "wrong")
    _reply(200, {"jsonrpc": "2.0", "id": 3, "result": [1, 2]})
    assert transport.execute_kw("db", 7, "s", "res.partner", "search", [[]]) == [1, 2]
    assert _Handler.seen[-1]["body"]["params"]["args"][-1] == {}  # kwargs default


def test_jsonrpc_api_key_rejection_is_recoverable(odoo: str) -> None:
    _reply(200, {"jsonrpc": "2.0", "id": 1,
                 "error": {"message": "Odoo Server Error",
                           "data": {"message": "Invalid API key for jsonrpc"}}})
    with pytest.raises(ApiKeyRejected):
        JsonRpcTransport(odoo, timeout=5).version()


def test_jsonrpc_application_fault(odoo: str) -> None:
    _reply(200, {"jsonrpc": "2.0", "id": 1,
                 "error": {"message": "Odoo Server Error",
                           "data": {"message": "Traceback...\nValueError: nope"}}})
    with pytest.raises(OdooFault, match="ValueError: nope"):
        JsonRpcTransport(odoo, timeout=5).version()


@pytest.mark.parametrize(
    ("status", "payload"),
    [(500, {"error": "x"}), (404, b"not found"), (200, b"<html>login</html>"), (200, [1])],
)
def test_jsonrpc_transport_failures(odoo: str, status: int, payload: Any) -> None:
    _reply(status, payload)
    with pytest.raises(TransportError):
        JsonRpcTransport(odoo, timeout=5).version()


def test_jsonrpc_unreachable_host_is_a_transport_error() -> None:
    with pytest.raises(TransportError):
        JsonRpcTransport("http://127.0.0.1:9", timeout=2).version()


def test_xmlrpc_transports_carry_the_timeout() -> None:
    plain = XmlRpcTransport("http://odoo.example", timeout=12)
    secure = XmlRpcTransport("https://odoo.example", timeout=34)
    assert isinstance(plain._transport(), _TimeoutTransport)
    assert isinstance(secure._transport(), _TimeoutSafeTransport)
    assert plain._transport().make_connection("odoo.example").timeout == 12
    assert secure._transport().make_connection("odoo.example").timeout == 34
