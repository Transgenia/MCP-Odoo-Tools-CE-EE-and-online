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


_JSON_TYPES: dict[str, Callable[[Any], bool]] = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    # bool is an int subclass in Python but not a JSON number; 1.0 is an integer
    # in JSON Schema, as jsonschema (and so the MCP SDK) treats it.
    "integer": lambda v: not isinstance(v, bool)
    and (isinstance(v, int) or (isinstance(v, float) and v.is_integer())),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "null": lambda v: v is None,
}


def validate_arguments(schema: dict[str, Any], value: Any, path: str = "arguments") -> str | None:
    """Check ``value`` against a tool's input schema; return the first problem or ``None``.

    Covers exactly the JSON Schema keywords the tool schemas use (``type``,
    ``properties``, ``required``, ``additionalProperties``, ``items``, ``enum``,
    ``minItems``, ``maxItems``), so bad or misnamed arguments are refused before
    they reach Odoo, as the MCP SDK's input validation did.
    """
    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        if not any(_JSON_TYPES.get(n, lambda _v: True)(value) for n in names):
            return f"{path}: expected {' or '.join(names)}, got {type(value).__name__}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: must be one of {schema['enum']}"
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                return f"{path}: missing required property '{key}'"
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                problem = validate_arguments(props[key], item, f"{path}.{key}")
            elif extra is False:
                problem = f"{path}: unexpected property '{key}'"
            elif isinstance(extra, dict):
                problem = validate_arguments(extra, item, f"{path}.{key}")
            else:
                problem = None
            if problem:
                return problem
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            return f"{path}: needs at least {schema['minItems']} item(s)"
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return f"{path}: allows at most {schema['maxItems']} item(s)"
        items = schema.get("items")
        if isinstance(items, dict):
            for i, item in enumerate(value):
                problem = validate_arguments(items, item, f"{path}[{i}]")
                if problem:
                    return problem
    return None


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
