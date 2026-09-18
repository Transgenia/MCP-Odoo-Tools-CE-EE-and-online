# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Render a QWeb report to base64 (PDF/HTML) via the report registry."""

from __future__ import annotations

import base64
from typing import Any

from ..registry import ToolContext, obj, registry


@registry.tool(
    "odoo_report",
    "Render a report action (by report_name) for given record ids and return "
    "the document base64-encoded.",
    obj(
        {
            "report_name": {"type": "string", "description": "e.g. account.report_invoice"},
            "ids": {"type": "array", "items": {"type": "integer"}},
        },
        required=["report_name", "ids"],
    ),
)
def odoo_report(ctx: ToolContext, args: dict[str, Any]) -> Any:
    report_name = args["report_name"]
    ids = args["ids"]
    # ir.actions.report._render_qweb_pdf returns (bytes, type). Available across
    # supported versions; older lines used render_report but _render_qweb_pdf is
    # the stable modern entry point (v13+). For <13 callers should pass an HTML
    # report and use the report service via odoo_execute.
    result = ctx.session.execute(
        "ir.actions.report", "_render_qweb_pdf", [report_name, ids]
    )
    content = result[0] if isinstance(result, (list, tuple)) else result
    if isinstance(content, str):
        # xmlrpc may deliver base64 already
        encoded = content
    else:
        encoded = base64.b64encode(bytes(content)).decode("ascii")
    return {"report_name": report_name, "ids": ids, "mimetype": "application/pdf", "base64": encoded}
