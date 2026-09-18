# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Metadata / introspection tools: version, connections, fields, models."""

from __future__ import annotations

from typing import Any

from ..compat import resolve_model
from ..registry import ToolContext, obj, registry


@registry.tool(
    "odoo_version",
    "Return the target Odoo version, edition (community/enterprise) and "
    "deployment (onprem/saas), plus the active transport.",
    obj({}),
)
def odoo_version(ctx: ToolContext, args: dict[str, Any]) -> Any:
    facts = ctx.session.facts()
    return {
        "version": facts.version,
        "raw_version": facts.raw_version,
        "edition": facts.edition,
        "deployment": facts.deployment,
        "transport": ctx.session.transport.active,
    }


@registry.tool(
    "odoo_connections",
    "List the Odoo instances this server currently has active sessions for.",
    obj({}),
)
def odoo_connections(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return {"connections": ctx.manager.connections()}


@registry.tool(
    "odoo_list_models",
    "List Odoo models, optionally filtered by a name fragment.",
    obj(
        {
            "like": {"type": "string", "description": "case-insensitive fragment to match model name"},
            "limit": {"type": "integer", "default": 200},
        }
    ),
)
def odoo_list_models(ctx: ToolContext, args: dict[str, Any]) -> Any:
    domain: list[Any] = []
    if args.get("like"):
        domain = ["|", ("model", "ilike", args["like"]), ("name", "ilike", args["like"])]
    rows = ctx.session.execute(
        "ir.model", "search_read", [domain], {"fields": ["model", "name"], "limit": args.get("limit", 200)}
    )
    return {"models": rows}


@registry.tool(
    "odoo_fields_get",
    "Return the field definitions of a model (cached). Accepts historical or "
    "modern model names; the compat layer resolves to the right one.",
    obj(
        {
            "model": {"type": "string"},
            "attributes": {"type": "array", "items": {"type": "string"}},
        },
        required=["model"],
    ),
)
def odoo_fields_get(ctx: ToolContext, args: dict[str, Any]) -> Any:
    facts = ctx.session.facts()
    model = resolve_model(args["model"], facts)
    fields = ctx.session.fields_get(model, args.get("attributes"))
    return {"model": model, "fields": fields}


@registry.tool(
    "odoo_module_info",
    "Look up an Odoo module's install state and metadata by technical name.",
    obj({"name": {"type": "string"}}, required=["name"]),
)
def odoo_module_info(ctx: ToolContext, args: dict[str, Any]) -> Any:
    rows = ctx.session.execute(
        "ir.module.module",
        "search_read",
        [[["name", "=", args["name"]]]],
        {"fields": ["name", "shortdesc", "state", "installed_version", "author", "license"]},
    )
    return {"module": rows[0] if rows else None}
