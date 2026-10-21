# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Tool registry: declarative tool definitions the MCP server iterates.

Every tool declares its permission mapping (:class:`Access`): the models it
reads or changes, so the permission policy (``odoo_mcp.policy``) can decide a
call before any session exists. A tool without one cannot be registered, and a
definition placed in the registry by hand without one is never listed and is
refused when called (fail closed).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .policy.model import Touch

__all__ = [
    "NO_MODEL",
    "Access",
    "Internal",
    "ToolContext",
    "ToolDef",
    "ToolRegistry",
    "Touch",
    "obj",
    "registry",
    "validate_arguments",
]


@dataclass
class ToolContext:
    """Per-call context handed to every tool handler.

    Through the server, ``session`` is the guarded session of this call
    (``odoo_mcp.policy.guard.GuardedSession``), which checks every Odoo call
    against the permission policy before it is sent, and ``manager`` is a view of
    the connection manager with its connections and call counters only (needed by
    tools that operate above a single tenant, e.g. listing connections). A handler
    called directly (tests) may get a plain session and manager. ``policy`` is the
    server's permission policy; only ``odoo_version``, ``odoo_list_models`` and
    ``odoo_access_check`` read it, and a handler called directly gets ``None`` and
    behaves as before the policy existed.
    """

    session: Any
    manager: Any
    policy: Any = None


# A tool handler receives (context, arguments) and returns a JSON-serialisable
# result.
ToolHandler = Callable[[ToolContext, dict[str, Any]], Any]


@dataclass(frozen=True)
class Internal:
    """A fixed call a tool makes that the agent does not choose (curated verb mechanics).

    ``model`` is a literal model name, or ``"$automation"`` for the automation
    model of the target version (``base.automation``, ``base.action.rule`` on
    Odoo 10). ``check`` is a predicate on the actual call; ``reason`` says why
    the tool needs the call.
    """

    model: str
    methods: frozenset[str]
    check: Callable[[Any, Any], bool] | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "methods", frozenset(self.methods))


@dataclass(frozen=True)
class Access:
    """What a tool reads or changes, declared for the permission policy.

    A tool declares every model whose data it returns or whose records it
    leaves changed; the fixed mechanics calls it makes are ``internal``.
    """

    arg_ops: tuple[str, ...] = ()  # operations on the model in args["model"]
    fixed: tuple[tuple[str, str], ...] = ()  # (op, model) on every call
    optional: tuple[tuple[str, str], ...] = ()  # (op, argument): when that argument is given
    dynamic: Callable[[dict[str, Any]], list[Touch]] | None = None  # odoo_execute
    internal: tuple[Internal, ...] = ()
    degrade: bool = False  # odoo_online_profile: a refused section degrades, the tool runs
    columns_arg: str | None = None  # imports: args[columns_arg] are load() column paths
    stub: bool = False  # odoo_report in 1.5.x: it never calls Odoo


# The mapping of a tool that touches no model of the agent's choosing.
NO_MODEL = Access()

MISSING_MAPPING = ("tool '{name}' has no permission mapping: pass access=... to registry.tool "
                   "(docs/policy.md#tool-mapping)")


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    read_only: bool = True
    # None only for a definition built by hand: never listed, refused when called.
    access: Access | None = None
    # For a tool that is not read-only: whether it may overwrite or delete (MCP
    # destructiveHint). MCP assumes true when a tool says nothing.
    destructive: bool | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        if tool.access is None:
            raise ValueError(MISSING_MAPPING.format(name=tool.name))
        self._tools[tool.name] = tool

    def tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        *,
        access: Access,
        read_only: bool = True,
        destructive: bool | None = None,
    ) -> Callable[[ToolHandler], ToolHandler]:
        def deco(fn: ToolHandler) -> ToolHandler:
            self.register(
                ToolDef(
                    name=name,
                    description=description,
                    input_schema=input_schema,
                    handler=fn,
                    read_only=read_only,
                    access=access,
                    destructive=destructive,
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
