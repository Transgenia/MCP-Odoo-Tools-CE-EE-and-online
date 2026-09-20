# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""MCP server wiring (stdio). Exposes the shared registry as MCP tools."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from . import tools as _tools  # noqa: F401  (import registers all tools)
from .config import Settings
from .errors import OdooMcpError
from .observability import Observability
from .registry import ToolContext, registry
from .tenancy import ConnectionManager

log = logging.getLogger("odoo_mcp.server")


def build_server(settings: Settings) -> Server:
    manager = ConnectionManager(settings)
    obs = Observability(
        metrics=settings.metrics,
        metrics_port=settings.metrics_port,
        otel_endpoint=settings.otel_endpoint,
    )
    server: Server = Server("odoo-mcp-tools")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(name=t.name, description=t.description, inputSchema=t.input_schema)
            for t in registry.all()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        try:
            tool = registry.get(name)
        except KeyError:
            raise ValueError(f"unknown tool: {name}")

        started = time.monotonic()
        status = "ok"
        try:
            def _run() -> Any:
                session = manager.default()  # stdio = single-tenant from env
                ctx = ToolContext(session=session, manager=manager)
                with obs.span(name):
                    return tool.handler(ctx, arguments or {})

            result = await anyio.to_thread.run_sync(_run)
            text = json.dumps(result, default=str, ensure_ascii=False)
            return [types.TextContent(type="text", text=text)]
        except OdooMcpError as exc:
            status = "error"
            # Clean, actionable message; SDK marks the result as isError.
            raise ValueError(str(exc)) from exc
        finally:
            obs.record(name, status, time.monotonic() - started)
            try:
                manager.record_tool_call(name)
            except Exception:  # noqa: S110 - counters must never fail a tool call
                pass

    return server


async def run_stdio(settings: Settings) -> None:
    server = build_server(settings)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def serve(settings: Settings | None = None) -> None:
    settings = settings or Settings.from_env()
    log.info("odoo-mcp-tools starting: %s", settings.redacted())
    anyio.run(run_stdio, settings)
