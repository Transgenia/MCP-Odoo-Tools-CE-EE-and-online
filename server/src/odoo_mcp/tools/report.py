# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""``odoo_report``: deprecated, it refuses before any RPC (removed in 2.0.0).

The tool used to call ``ir.actions.report._render_qweb_pdf``. That method is
private, and Odoo refuses private methods over XML-RPC, JSON-RPC and JSON-2 on
every version (our JSON-2 name check refuses it before sending), so the tool
could never succeed. It now says so without touching the session, and points to
``odoo_record_documents`` for the PDFs Odoo already stored. No private-method
allowance exists anywhere in the server.
"""

from __future__ import annotations

from typing import Any

from ..errors import CompatError
from ..registry import Access, ToolContext, obj, registry


@registry.tool(
    "odoo_report",
    "Deprecated (removed in 2.0.0): always returns an error without calling Odoo. "
    "It relied on ir.actions.report._render_qweb_pdf, a private method that Odoo "
    "refuses over RPC on every version, so it never worked. Use "
    "odoo_record_documents for the PDFs Odoo already stored (e.g. an invoice PDF "
    "made when it was sent or printed).",
    obj(
        {
            "report_name": {"type": "string", "description": "e.g. account.report_invoice"},
            "ids": {"type": "array", "items": {"type": "integer"}},
        },
        required=["report_name", "ids"],
    ),
    access=Access(stub=True),  # it never calls Odoo, so the policy has nothing to check
)
def odoo_report(ctx: ToolContext, args: dict[str, Any]) -> Any:
    raise CompatError(
        "odoo_report cannot work over RPC: Odoo refuses the private method "
        "ir.actions.report._render_qweb_pdf on every version",
        remediation="use odoo_record_documents for the PDFs Odoo already stored "
        "(e.g. an invoice PDF made when it was sent or printed)",
    )
