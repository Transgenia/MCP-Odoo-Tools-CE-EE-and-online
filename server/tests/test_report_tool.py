# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""``odoo_report`` refuses before any RPC (deprecated in 1.5.0, removed in 2.0.0)."""

from __future__ import annotations

from typing import Any

import pytest

from odoo_mcp.config import Settings
from odoo_mcp.errors import CompatError
from odoo_mcp.registry import ToolContext, registry
from odoo_mcp.server import McpServer
from odoo_mcp.tools.report import odoo_report

ARGS = {"report_name": "account.report_invoice", "ids": [1]}


class _ExplodingSession:
    """Any use of the session, even reading an attribute, fails the test."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"odoo_report touched the session ({name})")


class _Manager:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def default(self) -> _ExplodingSession:
        return _ExplodingSession()

    def record_tool_call(self, name: str) -> None:
        self.calls.append(name)


def test_the_handler_raises_compat_error_without_touching_the_session() -> None:
    ctx = ToolContext(session=_ExplodingSession(), manager=_Manager())
    with pytest.raises(CompatError) as info:
        odoo_report(ctx, ARGS)
    assert "_render_qweb_pdf" in str(info.value) and "every version" in str(info.value)
    assert "odoo_record_documents" in (info.value.remediation or "")


def test_the_server_returns_the_refusal_as_a_tool_error() -> None:
    manager = _Manager()
    server = McpServer(Settings(), manager=manager)  # type: ignore[arg-type]
    result = server.call_tool({"name": "odoo_report", "arguments": ARGS})
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "cannot work over RPC" in text and "odoo_record_documents" in text
    assert manager.calls == ["odoo_report"]


def test_the_tool_stays_listed_read_only_and_says_it_is_deprecated() -> None:
    tool = registry.get("odoo_report")
    assert tool.read_only is True
    assert tool.description.startswith("Deprecated (removed in 2.0.0)")
    assert "odoo_record_documents" in tool.description
    server = McpServer(Settings(), manager=_Manager())  # type: ignore[arg-type]
    listed = {t["name"]: t for t in server.list_tools()["tools"]}
    assert listed["odoo_report"]["inputSchema"]["required"] == ["report_name", "ids"]
