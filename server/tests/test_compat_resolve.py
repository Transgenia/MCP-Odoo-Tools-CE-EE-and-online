# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
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


def facts(version: int, edition: str = "community", deployment: str = "onprem") -> EnvFacts:
    return EnvFacts(version=version, edition=edition, deployment=deployment)


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
    "model,field,version,expected",
    [
        # analytic distribution rename at v16
        ("account.move.line", "analytic_distribution", 15, "analytic_account_id"),
        ("account.move.line", "analytic_distribution", 16, "analytic_distribution"),
        ("account.move.line", "analytic_account_id", 16, "analytic_distribution"),
        # removed fields become None on the version where they're gone
        ("product.template", "uom_po_id", 16, "uom_po_id"),
        ("product.template", "uom_po_id", 17, None),
        ("res.partner", "company_type", 18, "company_type"),
        ("res.partner", "company_type", 19, None),
    ],
)
def test_resolve_field(model: str, field: str, version: int, expected) -> None:
    assert resolve_field(model, field, facts(version)) == expected


def test_resolve_fields_drops_unavailable() -> None:
    res = resolve_fields("res.partner", ["name", "company_type"], facts(19))
    assert res.mapping == {"name": "name"}
    assert "company_type" in res.dropped


def test_capabilities() -> None:
    assert has_capability("api_key_auth", facts(14)) is True
    assert has_capability("api_key_auth", facts(13)) is False
    # jsonrpc api key works up to 16, not on 17+
    assert has_capability("jsonrpc_api_key", facts(16)) is True
    assert has_capability("jsonrpc_api_key", facts(17)) is False
    with pytest.raises(CompatError):
        assert_capability("api_key_auth", facts(12))


def test_requires_edition() -> None:
    with pytest.raises(CompatError):
        requires_edition("documents.document", facts(17, edition="community"))
    # enterprise: no raise
    requires_edition("documents.document", facts(17, edition="enterprise"))
    # unknown edition: don't block
    requires_edition("documents.document", facts(17, edition="unknown"))
