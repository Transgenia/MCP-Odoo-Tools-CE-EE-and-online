# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Interop: the official MCP Python client drives our stdlib server end to end.

The ``mcp`` package is a dev-only dependency (Python 3.10+); the server itself
never imports it. Skipped when it is not installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")
import anyio  # installed with mcp
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from odoo_mcp.config import Settings
from odoo_mcp.registry import registry
from odoo_mcp.server import McpServer  # importing it registers the tools

RUN_STDIO = Path(__file__).resolve().parents[1] / "run_stdio.py"


def _visible(settings: Settings) -> set[str]:
    """What our own tools/list lists for these settings, in process."""
    return {t["name"] for t in McpServer(settings).list_tools()["tools"]}


def test_official_client_lists_and_calls_tools() -> None:
    async def scenario() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-S", str(RUN_STDIO)],
            env={"ODOO_READONLY": "1"},
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.serverInfo.name == "odoo-mcp-tools"

            # Read-only mode hides the write tools (1.5.0): the visible set only.
            listed = await session.list_tools()
            names = {t.name for t in listed.tools}
            assert names == _visible(Settings(readonly=True))
            assert names == {t.name for t in registry.all() if t.read_only}
            read = next(t for t in listed.tools if t.name == "odoo_search_read")
            assert read.annotations is not None
            assert read.annotations.readOnlyHint is True

            # a hidden write tool, called by name, still says why
            refused = await session.call_tool("odoo_create", {})
            assert refused.isError is True
            assert "ODOO_READONLY" in refused.content[0].text

            await session.send_ping()

    anyio.run(scenario)


def test_official_client_reads_the_write_tools_annotations() -> None:
    async def scenario() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-S", str(RUN_STDIO)],
            env={"ODOO_POLICY": "full"},
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            listed = {t.name: t for t in (await session.list_tools()).tools}
            assert set(listed) == _visible(Settings(policy_profile="full"))
            assert len(listed) == len(registry.all())
            create, unlink = listed["odoo_create"], listed["odoo_unlink"]
            assert create.annotations is not None and unlink.annotations is not None
            assert create.annotations.readOnlyHint is False
            assert create.annotations.destructiveHint is False
            assert unlink.annotations.destructiveHint is True

    anyio.run(scenario)
