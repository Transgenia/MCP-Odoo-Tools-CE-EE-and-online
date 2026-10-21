# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Metadata / introspection tools: version, connections, fields, models."""

from __future__ import annotations

from typing import Any

from ..compat import resolve_model
from ..compat.detect import EnvFacts
from ..errors import CompatError, OdooFault, TransportError
from ..policy.texts import ADMIN_WARNING
from ..registry import NO_MODEL, Access, Internal, ToolContext, obj, registry


def _administrator(ctx: ToolContext, facts: EnvFacts) -> bool | None:
    """Whether the signed-in user is an administrator (base.group_system); ``None``
    when that cannot be told: the policy closes res.users, or the call fails."""
    if not ctx.policy.decide("inspect", "res.users").allowed:
        return None
    try:
        if facts.version >= 18:  # a record method from 18.0
            return bool(ctx.session.execute("res.users", "has_group", ["base.group_system"],
                                            ids=[ctx.session.uid]))
        # a model method before, which checks the current user
        return bool(ctx.session.execute("res.users", "has_group", ["base.group_system"]))
    except (OdooFault, TransportError, CompatError):
        return None


@registry.tool(
    "odoo_version",
    "Check the connection end to end (signs in with the configured credentials) "
    "and return the target Odoo version, edition (community/enterprise), "
    "deployment (onprem/saas), the active transport (json2, jsonrpc or xmlrpc) and "
    "transport_notice, set when the deprecated /xmlrpc or /jsonrpc is in use on Odoo 19+. "
    "'policy' describes the odoo-tools permission policy in force (profile, file, digest, "
    "hidden tools, openings, warnings, or the error that locked it).",
    obj({}),
    access=Access(
        internal=(Internal("res.users", frozenset({"has_group"}),
                           reason="W10: whether the Odoo user is an administrator"),),
    ),
)
def odoo_version(ctx: ToolContext, args: dict[str, Any]) -> Any:
    policy = ctx.policy
    if policy is not None and policy.locked:
        # Locked: say why without contacting Odoo (the server built no session).
        return {"policy": policy.describe(registry.all()), "note": str(policy.lock_error())}
    # The version itself needs no credentials; signing in first makes this the
    # connection check the guided route and /odoo-doctor rely on.
    _ = ctx.session.uid
    facts = ctx.session.facts()
    result: dict[str, Any] = {
        "version": facts.version,
        "raw_version": facts.raw_version,
        "edition": facts.edition,
        "deployment": facts.deployment,
        "transport": ctx.session.transport.active,
        # Odoo 19 deprecates the legacy endpoints and Odoo 22 removes them.
        "transport_notice": getattr(ctx.session.transport, "transport_notice", None),
    }
    if policy is not None:
        block = policy.describe(registry.all())
        if _administrator(ctx, facts):
            block["warnings"].append({"code": "W10", "text": ADMIN_WARNING})
        result["policy"] = block
    return result


@registry.tool(
    "odoo_connections",
    "List the Odoo instances this server currently has active sessions for.",
    obj({}),
    access=NO_MODEL,
)
def odoo_connections(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return {"connections": ctx.manager.connections()}


@registry.tool(
    "odoo_list_models",
    "List Odoo models, optionally filtered by a name fragment. Models the odoo-tools "
    "permission policy allows nothing on are left out; hidden_by_policy counts them.",
    obj(
        {
            "like": {"type": "string", "description": "case-insensitive fragment to match model name"},
            "limit": {"type": "integer", "default": 200},
        }
    ),
    access=Access(fixed=(("read", "ir.model"),)),
)
def odoo_list_models(ctx: ToolContext, args: dict[str, Any]) -> Any:
    domain: list[Any] = []
    if args.get("like"):
        domain = ["|", ("model", "ilike", args["like"]), ("name", "ilike", args["like"])]
    rows = ctx.session.execute(
        "ir.model", "search_read", [domain], {"fields": ["model", "name"], "limit": args.get("limit", 200)}
    )
    if ctx.policy is None:
        return {"models": rows}
    # A model the permission policy allows nothing on (the secrets tier) is left out.
    kept = [row for row in rows or []
            if isinstance(row, dict) and ctx.policy.decide("inspect", row.get("model")).allowed]
    return {"models": kept, "hidden_by_policy": len(rows or []) - len(kept)}


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
    access=Access(arg_ops=("inspect",)),
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
    access=Access(fixed=(("read", "ir.module.module"),)),
)
def odoo_module_info(ctx: ToolContext, args: dict[str, Any]) -> Any:
    rows = ctx.session.execute(
        "ir.module.module",
        "search_read",
        [[["name", "=", args["name"]]]],
        {"fields": ["name", "shortdesc", "state", "installed_version", "author", "license"]},
    )
    return {"module": rows[0] if rows else None}


@registry.tool(
    "odoo_telemetry_preview",
    "Show the exact opt-in telemetry payload the operator could share "
    "(or that telemetry is disabled). Read-only: renders the payload for human "
    "review, never transmits anything.",
    obj({}),
    access=NO_MODEL,
)
def odoo_telemetry_preview(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from ..telemetry import build_optin_payload, is_opted_in

    if not is_opted_in():
        return {
            "opted_in": False,
            "payload": None,
            "note": "telemetry disabled (default); set ODOO_TELEMETRY=opt-in to preview",
        }
    facts = ctx.session.facts()
    counts: dict[str, int] = {}
    snapshot = getattr(ctx.manager, "tool_calls_snapshot", None)
    if callable(snapshot):
        try:
            counts = snapshot() or {}
        except Exception:  # noqa: S110 - preview must work even without counters
            pass
    transport = getattr(getattr(ctx.session, "transport", None), "active", "unknown")
    payload = build_optin_payload(
        odoo_version_major=facts.version,
        odoo_edition=facts.edition,
        odoo_deployment=facts.deployment,
        transport=transport,
        tool_calls_by_tool=counts,
    )
    return {
        "opted_in": True,
        "payload": payload,
        "note": "manual preview only — nothing was transmitted; copy it yourself if you choose to share",
    }
