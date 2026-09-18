# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Read-only export tools (JSON / CSV) built on search_read."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from ..compat import requires_edition, resolve_fields, resolve_model
from ..registry import ToolContext, obj, registry


def _rows(ctx: ToolContext, args: dict[str, Any]) -> tuple[str, list[str], list[dict[str, Any]], dict]:
    facts = ctx.session.facts()
    model = resolve_model(args["model"], facts)
    requires_edition(model, facts)
    requested = args.get("fields") or []
    warn: dict[str, Any] = {}
    kwargs: dict[str, Any] = {k: args[k] for k in ("limit", "offset", "order") if k in args}
    if requested:
        res = resolve_fields(model, requested, facts)
        if res.dropped:
            warn["dropped_fields"] = res.dropped
        kwargs["fields"] = res.usable
    rows = ctx.session.execute(model, "search_read", [args.get("domain", [])], kwargs)
    columns = kwargs.get("fields") or (list(rows[0].keys()) if rows else [])
    return model, columns, rows, warn


_SCHEMA = obj(
    {
        "model": {"type": "string"},
        "domain": {"type": "array"},
        "fields": {"type": "array", "items": {"type": "string"}},
        "limit": {"type": "integer"},
        "offset": {"type": "integer"},
        "order": {"type": "string"},
    },
    required=["model"],
)


@registry.tool(
    "odoo_export_records_json",
    "Export records matching a domain as a JSON array (read-only).",
    _SCHEMA,
)
def odoo_export_records_json(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model, _cols, rows, warn = _rows(ctx, args)
    return {"model": model, "count": len(rows), "records": rows, **warn}


@registry.tool(
    "odoo_export_records_csv",
    "Export records matching a domain as CSV text (read-only).",
    _SCHEMA,
)
def odoo_export_records_csv(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model, columns, rows, warn = _rows(ctx, args)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({c: _flatten(r.get(c)) for c in columns})
    return {"model": model, "count": len(rows), "columns": columns, "csv": buf.getvalue(), **warn}


def _flatten(value: Any) -> Any:
    # Odoo many2one comes back as [id, "name"]; keep it CSV-friendly.
    if isinstance(value, (list, tuple)):
        if len(value) == 2 and isinstance(value[0], int):
            return value[1]
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return value
