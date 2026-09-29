# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Table-driven tests for the cross-version compatibility resolver."""

from __future__ import annotations

import pytest

from odoo_mcp.compat import (
    EnvFacts,
    assert_capability,
    has_capability,
    requires_edition,
    resolve_field,
    resolve_fields,
    resolve_model,
)
from odoo_mcp.errors import CompatError


def facts(version: int, edition: str = "community", deployment: str = "onprem",
          minor: int = 0) -> EnvFacts:
    return EnvFacts(version=version, edition=edition, deployment=deployment, minor=minor)


@pytest.mark.parametrize(
    "requested,version,expected",
    [
        # MERGE (not a rename): account.move exists on ALL versions as journal
        # entries, so it must NEVER be rewritten to account.invoice. account.invoice
        # (invoices) exists on <=12 and is folded into account.move at v13.
        ("account.move", 12, "account.move"),  # journal entries; must stay account.move
        ("account.move", 13, "account.move"),
        ("account.move", 19, "account.move"),
        ("account.invoice", 12, "account.invoice"),  # invoices model exists on <=12
        ("account.invoice", 13, "account.move"),  # invoice model gone -> account.move
        ("account.invoice", 18, "account.move"),
        # invoice lines (same merge semantics)
        ("account.move.line", 11, "account.move.line"),  # journal items; must stay
        ("account.invoice.line", 11, "account.invoice.line"),  # invoice lines exist on <=12
        ("account.invoice.line", 13, "account.move.line"),  # gone -> merged
        ("account.move.line", 13, "account.move.line"),
        # stock package rename (best-effort boundary v19)
        ("stock.package", 18, "stock.quant.package"),
        ("stock.package", 19, "stock.package"),
        ("stock.quant.package", 19, "stock.package"),
        # unknown model passes through unchanged
        ("res.partner", 10, "res.partner"),
    ],
)
def test_resolve_model(requested: str, version: int, expected: str) -> None:
    assert resolve_model(requested, facts(version)) == expected


@pytest.mark.parametrize(
    "model,field,version,minor,expected",
    [
        # analytic distribution rename at v16
        ("account.move.line", "analytic_distribution", 15, 0, "analytic_account_id"),
        ("account.move.line", "analytic_distribution", 16, 0, "analytic_distribution"),
        ("account.move.line", "analytic_account_id", 16, 0, "analytic_distribution"),
        # removed fields become None from the first series without them: the
        # boundaries come from the odoo/odoo source of 16.0 ... saas-19.4
        ("product.template", "uom_po_id", 16, 0, "uom_po_id"),
        ("product.template", "uom_po_id", 17, 0, "uom_po_id"),
        ("product.template", "uom_po_id", 17, 4, "uom_po_id"),  # saas~17.4
        ("product.template", "uom_po_id", 18, 0, "uom_po_id"),  # checked live on 18.0
        ("product.template", "uom_po_id", 18, 1, None),  # saas~18.1 (Online)
        ("product.template", "uom_po_id", 19, 0, None),
        ("res.partner", "company_type", 18, 4, "company_type"),
        ("res.partner", "company_type", 19, 0, "company_type"),  # still in 19.0
        ("res.partner", "company_type", 19, 1, None),  # saas~19.1 (Online)
    ],
)
def test_resolve_field(model: str, field: str, version: int, minor: int, expected) -> None:
    assert resolve_field(model, field, facts(version, minor=minor)) == expected


def test_resolve_fields_drops_unavailable() -> None:
    res = resolve_fields("res.partner", ["name", "company_type"], facts(19, minor=1))
    assert res.mapping == {"name": "name"}
    assert "company_type" in res.dropped


def test_capabilities() -> None:
    assert has_capability("api_key_auth", facts(14)) is True
    assert has_capability("api_key_auth", facts(13)) is False
    # API keys work on /jsonrpc on every version (no such limit in the table)
    assert has_capability("jsonrpc_api_key", facts(17)) is True
    with pytest.raises(CompatError):
        assert_capability("api_key_auth", facts(12))


def test_requires_edition() -> None:
    with pytest.raises(CompatError):
        requires_edition("documents.document", facts(17, edition="community"))
    # enterprise: no raise
    requires_edition("documents.document", facts(17, edition="enterprise"))
    # unknown edition: don't block
    requires_edition("documents.document", facts(17, edition="unknown"))
