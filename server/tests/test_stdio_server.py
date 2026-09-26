# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""The standard-library MCP stdio server: protocol handling and the real entry point."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from odoo_mcp.config import Settings
from odoo_mcp.errors import AuthError
from odoo_mcp.registry import ToolDef, registry
from odoo_mcp.server import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SUPPORTED_PROTOCOL_VERSIONS,
    McpServer,
)
from odoo_mcp.telemetry import PLUGIN_VERSION

RUN_STDIO = Path(__file__).resolve().parents[1] / "run_stdio.py"


class _FakeManager:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def default(self) -> object:
        return object()

    def record_tool_call(self, name: str) -> None:
        self.calls.append(name)


def _server(**settings: Any) -> McpServer:
    return McpServer(Settings(**settings), manager=_FakeManager())  # type: ignore[arg-type]


def _req(method: str, params: dict[str, Any] | None = None, msg_id: Any = 1) -> dict[str, Any]:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def _run(lines: list[Any], **settings: Any) -> list[Any]:
    """Feed lines through the stdio loop; str/bytes go raw, anything else as JSON."""

    def encode(line: Any) -> bytes:
        if isinstance(line, bytes):
            return line
        return (line if isinstance(line, str) else json.dumps(line)).encode("utf-8")

    raw = b"".join(encode(line) + b"\n" for line in lines)
    out = io.BytesIO()
    _server(**settings).run(io.BytesIO(raw), out)
    return [json.loads(x) for x in out.getvalue().splitlines()]


@pytest.fixture
def echo_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
        if args.get("fail") == "odoo":
            raise AuthError("bad credentials")
        if args.get("fail") == "bug":
            raise RuntimeError("boom")
        return {"echo": args, "accent": "añadir"}

    monkeypatch.setitem(
        registry._tools,
        "t_echo",
        ToolDef(name="t_echo", description="echo", input_schema={"type": "object"},
                handler=handler),
    )


def test_initialize_echoes_supported_version_and_reports_plugin_version() -> None:
    srv = _server()
    for version in SUPPORTED_PROTOCOL_VERSIONS:
        result = srv.handle(_req("initialize", {"protocolVersion": version}))["result"]
        assert result["protocolVersion"] == version
    result = srv.handle(_req("initialize", {"protocolVersion": "1999-01-01"}))["result"]
    assert result["protocolVersion"] == SUPPORTED_PROTOCOL_VERSIONS[0]
    assert result["serverInfo"] == {"name": "odoo-mcp-tools", "version": PLUGIN_VERSION}
    assert result["capabilities"] == {"tools": {"listChanged": False}}


def test_tools_list_exposes_every_registered_tool() -> None:
    tools = _server().handle(_req("tools/list"))["result"]["tools"]
    assert [t["name"] for t in tools] == [t.name for t in registry.all()]
    by_name = {t["name"]: t for t in tools}
    assert by_name["odoo_search_read"]["annotations"] == {"readOnlyHint": True}
    assert by_name["odoo_create"]["annotations"] == {"readOnlyHint": False}
    for tool in tools:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"


def test_tool_call_success_error_and_bug(echo_tool: None) -> None:
    srv = _server()
    ok = srv.handle(_req("tools/call", {"name": "t_echo", "arguments": {"a": 1}}))["result"]
    assert ok["isError"] is False
    assert json.loads(ok["content"][0]["text"]) == {"echo": {"a": 1}, "accent": "añadir"}

    odoo = srv.handle(_req("tools/call", {"name": "t_echo", "arguments": {"fail": "odoo"}}))
    assert odoo["result"]["isError"] is True
    assert "bad credentials" in odoo["result"]["content"][0]["text"]

    bug = srv.handle(_req("tools/call", {"name": "t_echo", "arguments": {"fail": "bug"}}))
    assert bug["result"]["isError"] is True
    assert "boom" in bug["result"]["content"][0]["text"]
    assert srv.manager.calls == ["t_echo", "t_echo", "t_echo"]  # type: ignore[attr-defined]


def test_tool_call_without_arguments_passes_empty_object(echo_tool: None) -> None:
    result = _server().handle(_req("tools/call", {"name": "t_echo"}))["result"]
    assert json.loads(result["content"][0]["text"])["echo"] == {}


def test_readonly_refusal_is_a_tool_error_and_not_counted() -> None:
    srv = _server(readonly=True)
    result = srv.handle(_req("tools/call", {"name": "odoo_create", "arguments": {}}))["result"]
    assert result["isError"] is True
    assert "ODOO_READONLY" in result["content"][0]["text"]
    assert srv.manager.calls == []  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"name": "no_such_tool"}, INVALID_PARAMS),
        ({}, INVALID_PARAMS),
        ({"name": "odoo_version", "arguments": [1]}, INVALID_PARAMS),
    ],
)
def test_bad_tool_calls_are_protocol_errors(params: dict[str, Any], code: int) -> None:
    assert _server().handle(_req("tools/call", params))["error"]["code"] == code


def test_ping_unknown_method_and_notifications() -> None:
    srv = _server()
    assert srv.handle(_req("ping")) == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert srv.handle(_req("resources/list"))["error"]["code"] == METHOD_NOT_FOUND
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/whatever"}) is None
    assert srv.handle({"jsonrpc": "2.0", "id": 9, "result": {}}) is None  # a response


def test_invalid_messages() -> None:
    srv = _server()
    assert srv.handle([1])["error"]["code"] == INVALID_REQUEST  # type: ignore[arg-type]
    assert srv.handle({"id": 1, "method": "ping"})["error"]["code"] == INVALID_REQUEST
    assert srv.handle(_req("ping", msg_id="abc"))["id"] == "abc"
    bad_params = {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": [1]}
    assert srv.handle(bad_params)["error"]["code"] == INVALID_PARAMS


def test_stdio_loop_answers_everything_in_one_line_each(echo_tool: None) -> None:
    replies = _run([
        _req("initialize", {"protocolVersion": "2025-06-18"}, 1),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        _req("tools/call", {"name": "t_echo", "arguments": {"x": "línea\nnueva"}}, 2),
        _req("tools/call", {"name": "t_echo", "arguments": {"y": 2}}, 3),
        "",
        "not json",
        b"\xff\xfe",
        [_req("ping", msg_id=4), {"jsonrpc": "2.0", "method": "notifications/initialized"}],
        [],
    ])
    by_id = {r["id"]: r for r in replies if isinstance(r, dict) and r.get("id") is not None}
    assert by_id[1]["result"]["protocolVersion"] == "2025-06-18"
    assert json.loads(by_id[2]["result"]["content"][0]["text"])["echo"] == {"x": "línea\nnueva"}
    assert by_id[3]["result"]["isError"] is False
    errors = [r["error"]["code"] for r in replies if isinstance(r, dict) and "error" in r]
    assert errors.count(PARSE_ERROR) == 2
    assert INVALID_REQUEST in errors  # the empty batch
    assert [r for r in replies if isinstance(r, list)] == [[{"jsonrpc": "2.0", "id": 4,
                                                             "result": {}}]]


def test_cancelled_request_gets_no_response(echo_tool: None) -> None:
    srv = _server()
    srv._notification("notifications/cancelled", {"requestId": 7})
    out = io.BytesIO()
    srv._out = out
    srv._run_tool_call(_req("tools/call", {"name": "t_echo"}, 7))
    assert out.getvalue() == b""
    srv._run_tool_call(_req("tools/call", {"name": "t_echo"}, 8))
    assert json.loads(out.getvalue())["id"] == 8


def _entry_point(lines: list[dict[str, Any]], *extra_env: tuple[str, str]) -> list[Any]:
    env = {"PATH": os.environ.get("PATH", ""), "ODOO_READONLY": "1", **dict(extra_env)}
    # -S: no site-packages at all, so this proves the plugin needs only the stdlib.
    proc = subprocess.run(
        [sys.executable, "-S", str(RUN_STDIO)],
        input="".join(json.dumps(x) + "\n" for x in lines).encode(),
        capture_output=True,
        env=env,
        timeout=60,
        check=True,
    )
    assert b"starting" in proc.stderr  # logs go to stderr, never stdout
    return [json.loads(x) for x in proc.stdout.splitlines()]


def test_entry_point_runs_on_the_standard_library_alone() -> None:
    replies = _entry_point([
        _req("initialize", {"protocolVersion": "2025-03-26"}, 1),
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        _req("tools/list", msg_id=2),
        _req("tools/call", {"name": "odoo_create", "arguments": {}}, 3),
    ])
    by_id = {r["id"]: r for r in replies}
    assert by_id[1]["result"]["protocolVersion"] == "2025-03-26"
    assert len(by_id[2]["result"]["tools"]) == len(registry.all())
    assert by_id[3]["result"]["isError"] is True


def test_entry_point_ignores_unresolved_plugin_placeholders() -> None:
    replies = _entry_point(
        [_req("tools/call", {"name": "odoo_create", "arguments": {}}, 1)],
        ("ODOO_URL", "${user_config.odoo_url}"),
        ("ODOO_API_KEY", "${user_config.odoo_api_key}"),
    )
    assert replies[0]["result"]["isError"] is True  # refused by readonly, not a crash
