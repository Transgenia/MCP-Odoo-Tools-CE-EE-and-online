# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Studio-style low-code tools: custom fields and automated actions.

These bring the most common Odoo Studio operations to plain RPC, so you can add
a field or an automation on **Community or Enterprise** without the (Enterprise-
only) Studio app. Changes live in the instance/DB (same place Studio stores its
customizations), not as module code in a repository.

Guardrails:
  * Custom fields are created with ``state='manual'`` and an ``x_`` name prefix,
    exactly as Odoo requires for fields added to existing models via the ORM.
  * Automation/server-action python is validated against Odoo's ``safe_eval``
    restrictions BEFORE it is sent (no imports, defs, classes, returns, or
    dunder access). This matters most on Odoo online/SaaS, where arbitrary
    python is refused server-side.
The tools introspect the target model's schema (cached) so they adapt across
Odoo 10-19 instead of assuming one version's field layout.
"""

from __future__ import annotations

import ast
from typing import Any

from ..compat import requires_edition, resolve_model
from ..errors import CompatError, OdooFault
from ..registry import ToolContext, obj, registry

_FIELD_TYPES = (
    "char", "text", "html", "boolean", "integer", "float", "monetary",
    "date", "datetime", "many2one", "one2many", "many2many", "selection",
)
_NEEDS_RELATION = {"many2one", "one2many", "many2many"}

# safe_eval forbidden AST nodes / patterns (mirrors Odoo's server-side rules).
_FORBIDDEN_NODES = (ast.Import, ast.ImportFrom, ast.FunctionDef,
                    ast.AsyncFunctionDef, ast.ClassDef, ast.Return, ast.Global,
                    ast.Nonlocal, ast.With, ast.AsyncWith)


def validate_safe_eval(code: str) -> None:
    """Raise CompatError if ``code`` would be rejected by Odoo's safe_eval.

    Mirrors ``odoo/tools/safe_eval.py`` ``_BLACKLIST``: ``STORE_ATTR`` /
    ``DELETE_ATTR`` are forbidden, so direct field assignment such as
    ``rec.priority = '3'`` fails server-side. Callers must use
    ``records.write({...})`` instead. Only a bare ``action = {...}`` Name
    assignment is allowed as the return channel.
    """
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise CompatError(
            f"server-action code has a syntax error: {exc.msg} (line {exc.lineno})",
            remediation="write plain statements; the last one may assign action = {...}",
        ) from exc
    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_NODES):
            raise CompatError(
                f"server-action code uses '{type(node).__name__}', which Odoo safe_eval forbids",
                remediation="no import/def/class/return/with; use only expressions and "
                "assignments over env, model, record(s), datetime, etc.",
            )
        if isinstance(node, ast.Attribute) and isinstance(
            node.ctx, (ast.Store, ast.AugStore, ast.Del)
        ):
            raise CompatError(
                "server-action code assigns to an attribute; Odoo safe_eval "
                "forbids STORE_ATTR/DELETE_ATTR",
                remediation="use records.write({'field': value}) instead of "
                "rec.field = value; only 'action = {...}' may be assigned",
            )
        if isinstance(node, ast.Subscript) and isinstance(
            node.ctx, (ast.Store, ast.AugStore, ast.Del)
        ):
            raise CompatError(
                "server-action code assigns to a subscript; Odoo safe_eval forbids it",
                remediation="use records.write({'field': value}) instead of rec['field'] = value",
            )
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise CompatError(
                f"server-action code accesses a private attribute '{node.attr}'",
                remediation="safe_eval blocks names/attributes starting with underscore",
            )
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise CompatError(
                f"server-action code references a dunder name '{node.id}'",
                remediation="safe_eval blocks dunder access",
            )


def _model_id(ctx: ToolContext, model: str) -> int:
    ids = ctx.session.execute("ir.model", "search", [[["model", "=", model]]], {"limit": 1})
    if not ids:
        raise CompatError(
            f"model '{model}' not found in ir.model",
            remediation="check the model name with odoo_list_models",
        )
    return ids[0]


@registry.tool(
    "odoo_add_field",
    "Add a custom field to a model (Studio-style, works on CE and EE). Creates a "
    "manual ir.model.fields record; the name is forced to the required 'x_' prefix. "
    "(write operation)",
    obj(
        {
            "model": {"type": "string", "description": "target model, e.g. res.partner"},
            "name": {"type": "string", "description": "field name; 'x_' prefix added if missing"},
            "label": {"type": "string", "description": "human label (field_description)"},
            "field_type": {"type": "string", "enum": list(_FIELD_TYPES)},
            "relation": {"type": "string", "description": "co-model for relational types"},
            "relation_field": {"type": "string", "description": "inverse field for one2many (required when field_type is one2many)"},
            "currency_field": {
                "type": "string",
                "description": "for monetary fields: many2one to res.currency holding the currency (defaults to currency_id)",
            },
            "selection": {
                "type": "array",
                "description": "for selection fields: list of [value, label] pairs",
                "items": {"type": "array", "minItems": 2, "maxItems": 2},
            },
            "required": {"type": "boolean", "default": False},
            "help": {"type": "string"},
        },
        required=["model", "name", "label", "field_type"],
    ),
    read_only=False,
)
def odoo_add_field(ctx: ToolContext, args: dict[str, Any]) -> Any:
    facts = ctx.session.facts()
    model = resolve_model(args["model"], facts)
    requires_edition(model, facts)

    ftype = args["field_type"]
    if ftype not in _FIELD_TYPES:
        raise CompatError(f"unsupported field_type '{ftype}'",
                          remediation=f"one of: {', '.join(_FIELD_TYPES)}")
    if ftype in _NEEDS_RELATION and not (args.get("relation") or "").strip():
        raise CompatError(f"field_type '{ftype}' requires 'relation' (the co-model)")
    if ftype == "one2many" and not (args.get("relation_field") or "").strip():
        raise CompatError(
            "field_type 'one2many' requires 'relation_field' (the inverse many2one on the co-model)",
            remediation="pass the existing many2one field name on the relation model",
        )
    if ftype == "selection" and not args.get("selection"):
        raise CompatError("selection fields require a 'selection' list of [value, label] pairs")

    name = args["name"]
    if not name.startswith("x_"):
        name = "x_" + name

    vals: dict[str, Any] = {
        "name": name,
        "field_description": args["label"],
        "ttype": ftype,
        "model_id": _model_id(ctx, model),
        "model": model,
        "state": "manual",
        "required": bool(args.get("required", False)),
    }
    if args.get("help"):
        vals["help"] = args["help"]
    if args.get("relation"):
        relation_raw = (args["relation"] or "").strip()
        relation = resolve_model(relation_raw, facts)
        requires_edition(relation, facts)
        vals["relation"] = relation
    if args.get("relation_field"):
        vals["relation_field"] = args["relation_field"]
    if ftype == "monetary" and args.get("currency_field"):
        vals["currency_field"] = args["currency_field"]
    if ftype == "selection":
        # Custom selection fields accept the char repr on all supported versions.
        raw_pairs = args["selection"]
        if not isinstance(raw_pairs, (list, tuple)) or not raw_pairs:
            raise CompatError(
                "selection fields require a non-empty 'selection' list of [value, label] pairs"
            )
        pairs: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in raw_pairs:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise CompatError(
                    f"selection entry {item!r} must be exactly [value, label]",
                    remediation="pass selection as [[\"a\", \"A\"], [\"b\", \"B\"]]",
                )
            v, lbl = item
            if not isinstance(v, str) or not isinstance(lbl, str) or not v or not lbl:
                raise CompatError(
                    f"selection entry {item!r} must be two non-empty strings",
                    remediation="pass selection as [[\"a\", \"A\"], [\"b\", \"B\"]]",
                )
            if v in seen:
                raise CompatError(f"duplicate selection value {v!r}")
            seen.add(v)
            pairs.append((v, lbl))
        vals["selection"] = repr(pairs)

    new_id = ctx.session.execute("ir.model.fields", "create", [vals])
    try:
        inv = getattr(ctx.session, "invalidate_fields", None)
        if callable(inv):
            inv(model)
    except Exception:  # noqa: S110 — cache invalidation must not fail writes
        pass
    return {"model": model, "field": name, "type": ftype, "field_id": new_id}


@registry.tool(
    "odoo_add_automation",
    "Create an automated action (Studio-style) that runs server-action python on a "
    "model trigger. The python is validated against Odoo safe_eval before sending. "
    "Adapts to the base.automation schema of the target version. (write operation)",
    obj(
        {
            "model": {"type": "string"},
            "name": {"type": "string"},
            "code": {
                "type": "string",
                "description": "server-action python (safe_eval): use env, model, "
                "record(s), datetime, ...; assign action = {...} as the last line to return one",
            },
            "trigger": {
                "type": "string",
                "description": "e.g. on_create, on_write, on_create_or_write, on_unlink",
                "default": "on_create_or_write",
            },
            "filter_domain": {"type": "array", "description": "optional domain that gates the trigger"},
        },
        required=["model", "name", "code"],
    ),
    read_only=False,
)
def odoo_add_automation(ctx: ToolContext, args: dict[str, Any]) -> Any:
    facts = ctx.session.facts()
    model = resolve_model(args["model"], facts)
    requires_edition(model, facts)

    code = args["code"]
    validate_safe_eval(code)  # refuse forbidden python up front (esp. on SaaS)

    # Odoo 10 uses the legacy automated-action model; 11+ uses base.automation.
    automation_model = "base.action.rule" if facts.version == 10 else "base.automation"
    # Introspect the automation model so we adapt across versions (inline
    # server-action delegation in v16+, vs a linked ir.actions.server older).
    try:
        fg = ctx.session.fields_get(automation_model)
    except OdooFault as exc:
        module = "base_action_rule" if facts.version == 10 else "base_automation"
        raise CompatError(
            f"{automation_model} is not available on this instance",
            remediation=f"ensure the '{module}' module is installed",
        ) from exc

    model_id = _model_id(ctx, model)
    name = args["name"]
    trigger = args.get("trigger", "on_create_or_write")

    base_vals: dict[str, Any] = {"name": name, "model_id": model_id}
    if "trigger" in fg:
        base_vals["trigger"] = trigger
    if args.get("filter_domain") is not None and "filter_domain" in fg:
        base_vals["filter_domain"] = repr(args["filter_domain"])

    if "state" in fg and "code" in fg:
        # v16+: base.automation delegates to ir.actions.server (inline code).
        base_vals["state"] = "code"
        base_vals["code"] = code
        auto_id = ctx.session.execute(automation_model, "create", [base_vals])
        return {"model": model, "automation_id": auto_id, "mode": "inline-server-action"}

    # Older: resolve the link field BEFORE creating anything so we never
    # leave an orphan ir.actions.server behind.
    link_field = "action_server_id" if "action_server_id" in fg else (
        "action_server_ids" if "action_server_ids" in fg else None
    )
    if link_field is None:
        raise CompatError(
            f"could not find how {automation_model} links its server action on this version",
            remediation="inspect the automation model with odoo_fields_get and create it manually",
        )
    # Older: create the server action, then link it.
    server_vals = {"name": name, "model_id": model_id, "state": "code", "code": code}
    server_id = ctx.session.execute("ir.actions.server", "create", [server_vals])
    base_vals[link_field] = server_id if link_field.endswith("_id") else [(6, 0, [server_id])]
    try:
        auto_id = ctx.session.execute(automation_model, "create", [base_vals])
    except OdooFault as exc:
        try:
            ctx.session.execute("ir.actions.server", "unlink", [[server_id]])
        except Exception:  # noqa: S110 — best-effort orphan cleanup
            pass
        raise CompatError(
            f"automation creation failed; orphan server action {server_id} was removed",
            remediation="check trigger, domain and permissions, then retry",
        ) from exc
    return {"model": model, "automation_id": auto_id, "server_action_id": server_id,
            "mode": "linked-server-action"}
