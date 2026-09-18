# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Generic CRUD tools, all routed through the compat layer.

Model names are resolved for the target version; requested field names are
remapped and unavailable fields dropped with a warning in the response so a
caller written for one version keeps working on another.
"""

from __future__ import annotations

from typing import Any

from ..compat import requires_edition, resolve_fields, resolve_model
from ..registry import ToolContext, obj, registry

_DOMAIN = {
    "type": "array",
    "description": "Odoo search domain, e.g. [[\"state\",\"=\",\"posted\"]]",
}
_FIELDS = {"type": "array", "items": {"type": "string"}}


def _facts(ctx: ToolContext) -> Any:
    return ctx.session.facts()


def _remap_fields(ctx: ToolContext, model: str, fields: list[str] | None) -> tuple[list[str] | None, dict]:
    if not fields:
        return None, {}
    res = resolve_fields(model, fields, _facts(ctx))
    warn = {"dropped_fields": res.dropped} if res.dropped else {}
    return res.usable, warn


@registry.tool(
    "odoo_search",
    "Search a model and return matching record ids.",
    obj(
        {
            "model": {"type": "string"},
            "domain": _DOMAIN,
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
            "order": {"type": "string"},
        },
        required=["model"],
    ),
)
def odoo_search(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    requires_edition(model, _facts(ctx))
    kwargs = {k: args[k] for k in ("limit", "offset", "order") if k in args}
    ids = ctx.session.execute(model, "search", [args.get("domain", [])], kwargs)
    return {"model": model, "ids": ids}


@registry.tool(
    "odoo_search_count",
    "Count records matching a domain.",
    obj({"model": {"type": "string"}, "domain": _DOMAIN}, required=["model"]),
)
def odoo_search_count(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    requires_edition(model, _facts(ctx))
    count = ctx.session.execute(model, "search_count", [args.get("domain", [])])
    return {"model": model, "count": count}


@registry.tool(
    "odoo_read",
    "Read records by id, optionally limiting fields.",
    obj(
        {
            "model": {"type": "string"},
            "ids": {"type": "array", "items": {"type": "integer"}},
            "fields": _FIELDS,
        },
        required=["model", "ids"],
    ),
)
def odoo_read(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    requires_edition(model, _facts(ctx))
    fields, warn = _remap_fields(ctx, model, args.get("fields"))
    kwargs = {"fields": fields} if fields else {}
    rows = ctx.session.execute(model, "read", [args["ids"]], kwargs)
    return {"model": model, "records": rows, **warn}


@registry.tool(
    "odoo_search_read",
    "Search and read in one call (the workhorse query tool).",
    obj(
        {
            "model": {"type": "string"},
            "domain": _DOMAIN,
            "fields": _FIELDS,
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
            "order": {"type": "string"},
        },
        required=["model"],
    ),
)
def odoo_search_read(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    requires_edition(model, _facts(ctx))
    fields, warn = _remap_fields(ctx, model, args.get("fields"))
    kwargs: dict[str, Any] = {k: args[k] for k in ("limit", "offset", "order") if k in args}
    if fields:
        kwargs["fields"] = fields
    rows = ctx.session.execute(model, "search_read", [args.get("domain", [])], kwargs)
    return {"model": model, "records": rows, **warn}


@registry.tool(
    "odoo_create",
    "Create one record. Returns the new id. (write operation)",
    obj({"model": {"type": "string"}, "values": {"type": "object"}}, required=["model", "values"]),
    read_only=False,
)
def odoo_create(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    requires_edition(model, _facts(ctx))
    new_id = ctx.session.execute(model, "create", [args["values"]])
    return {"model": model, "id": new_id}


@registry.tool(
    "odoo_write",
    "Update records by id. (write operation)",
    obj(
        {
            "model": {"type": "string"},
            "ids": {"type": "array", "items": {"type": "integer"}},
            "values": {"type": "object"},
        },
        required=["model", "ids", "values"],
    ),
    read_only=False,
)
def odoo_write(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    requires_edition(model, _facts(ctx))
    ok = ctx.session.execute(model, "write", [args["ids"], args["values"]])
    return {"model": model, "ok": bool(ok)}


@registry.tool(
    "odoo_unlink",
    "Delete records by id. (write operation)",
    obj(
        {"model": {"type": "string"}, "ids": {"type": "array", "items": {"type": "integer"}}},
        required=["model", "ids"],
    ),
    read_only=False,
)
def odoo_unlink(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    requires_edition(model, _facts(ctx))
    ok = ctx.session.execute(model, "unlink", [args["ids"]])
    return {"model": model, "ok": bool(ok)}


@registry.tool(
    "odoo_execute",
    "Call an arbitrary model method (escape hatch). args/kwargs passed through.",
    obj(
        {
            "model": {"type": "string"},
            "method": {"type": "string"},
            "args": {"type": "array"},
            "kwargs": {"type": "object"},
        },
        required=["model", "method"],
    ),
    read_only=False,
)
def odoo_execute(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    result = ctx.session.execute(model, args["method"], args.get("args", []), args.get("kwargs", {}))
    return {"model": model, "method": args["method"], "result": result}
