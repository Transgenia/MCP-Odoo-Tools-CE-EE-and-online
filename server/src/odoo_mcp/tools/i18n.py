# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Translation helpers, version-branched.

Odoo 16+ exposes ``update_field_translations``; older versions require writing
the field under a language context. The compat capability check selects the
right path so a single tool works on 10-19.
"""

from __future__ import annotations

from typing import Any

from ..compat import has_capability, resolve_model
from ..registry import ToolContext, obj, registry


@registry.tool(
    "odoo_translate_get",
    "Read a field's value in a specific language for a record.",
    obj(
        {
            "model": {"type": "string"},
            "id": {"type": "integer"},
            "field": {"type": "string"},
            "lang": {"type": "string", "description": "e.g. es_MX, en_US, zh_CN"},
        },
        required=["model", "id", "field", "lang"],
    ),
)
def odoo_translate_get(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], ctx.session.facts())
    rows = ctx.session.execute(
        model, "read", [[args["id"]], [args["field"]]], {"context": {"lang": args["lang"]}}
    )
    value = rows[0].get(args["field"]) if rows else None
    return {"model": model, "id": args["id"], "field": args["field"], "lang": args["lang"], "value": value}


@registry.tool(
    "odoo_translate_set",
    "Set a field's translation for one language. (write operation)",
    obj(
        {
            "model": {"type": "string"},
            "id": {"type": "integer"},
            "field": {"type": "string"},
            "lang": {"type": "string"},
            "value": {"type": "string"},
        },
        required=["model", "id", "field", "lang", "value"],
    ),
    read_only=False,
)
def odoo_translate_set(ctx: ToolContext, args: dict[str, Any]) -> Any:
    facts = ctx.session.facts()
    model = resolve_model(args["model"], facts)
    field, lang, value, rec_id = args["field"], args["lang"], args["value"], args["id"]

    if has_capability("update_field_translations", facts):
        # v16+: native API writes the per-language term in one call.
        ctx.session.execute(
            model, "update_field_translations", [[rec_id], field, {lang: value}]
        )
        method = "update_field_translations"
    else:
        # <=15: write the field within the language context.
        ctx.session.execute(model, "write", [[rec_id], {field: value}], {"context": {"lang": lang}})
        method = "write(lang-context)"
    return {"model": model, "id": rec_id, "field": field, "lang": lang, "method": method, "ok": True}
