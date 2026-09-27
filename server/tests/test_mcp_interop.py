# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
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

from odoo_mcp.registry import registry

RUN_STDIO = Path(__file__).resolve().parents[1] / "run_stdio.py"


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

            listed = await session.list_tools()
            assert {t.name for t in listed.tools} == {t.name for t in registry.all()}
            create = next(t for t in listed.tools if t.name == "odoo_create")
            assert create.annotations is not None
            assert create.annotations.readOnlyHint is False

            refused = await session.call_tool("odoo_create", {})
            assert refused.isError is True
            assert "ODOO_READONLY" in refused.content[0].text

            await session.send_ping()

    anyio.run(scenario)
