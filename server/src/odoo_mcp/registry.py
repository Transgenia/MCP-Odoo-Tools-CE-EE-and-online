# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Tool registry: declarative tool definitions the MCP server iterates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolContext:
    """Per-call context handed to every tool handler.

    ``session`` is the resolved :class:`odoo_mcp.session.OdooSession` for this
    call; ``manager`` is the :class:`odoo_mcp.tenancy.ConnectionManager` (needed
    by tools that operate above a single tenant, e.g. listing connections).
    """

    session: Any
    manager: Any


# A tool handler receives (context, arguments) and returns a JSON-serialisable
# result.
ToolHandler = Callable[[ToolContext, dict[str, Any]], Any]


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    read_only: bool = True


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        *,
        read_only: bool = True,
    ) -> Callable[[ToolHandler], ToolHandler]:
        def deco(fn: ToolHandler) -> ToolHandler:
            self.register(
                ToolDef(
                    name=name,
                    description=description,
                    input_schema=input_schema,
                    handler=fn,
                    read_only=read_only,
                )
            )
            return fn

        return deco

    def get(self, name: str) -> ToolDef:
        if name not in self._tools:
            raise KeyError(name)
        return self._tools[name]

    def all(self) -> list[ToolDef]:
        return list(self._tools.values())


# Shared singleton the tools/* modules register against on import.
registry = ToolRegistry()


def obj(properties: dict[str, Any], required: list[str] | None = None,
        additional: bool = False) -> dict[str, Any]:
    """Helper to build a JSON-schema object for a tool's inputSchema."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional,
    }
    if required:
        schema["required"] = required
    return schema
