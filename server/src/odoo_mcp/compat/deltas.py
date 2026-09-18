# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Declarative cross-version delta map for Odoo 10-19.

This is DATA, not logic. New deltas are added here and covered by table-driven
tests. All entries reflect publicly known Odoo API/schema changes; version
boundaries marked "best-effort" should be confirmed by a live probe when a user
reports a mismatch (that is what the compat layer's graceful errors are for).

Conventions:
  * ``changed_in`` = the first major version where the NEW name/behavior applies.
  * ``since`` = feature/model available from this major version onward.
  * ``until`` = feature/model available up to and including this major version.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_VERSION = 10
MAX_VERSION = 19


@dataclass(frozen=True)
class ModelRename:
    old: str
    new: str
    changed_in: int
    note: str = ""
    # A "merge" is NOT a clean rename: the ``new`` model already exists as a
    # DISTINCT model before ``changed_in`` (e.g. account.move = journal entries
    # exists on v10-12 alongside account.invoice = invoices, which was folded into
    # account.move at v13). For merges we must only resolve old->new on
    # ``version >= changed_in`` (where ``old`` is gone) and NEVER rewrite
    # new->old on older versions, or a call meant for the ``new`` model would be
    # redirected to a different model with different semantics.
    merge: bool = False


@dataclass(frozen=True)
class FieldRename:
    model: str
    old: str
    new: str
    changed_in: int
    note: str = ""


@dataclass(frozen=True)
class FieldRemoved:
    model: str
    field: str
    removed_in: int
    use_instead: str = ""
    note: str = ""


@dataclass(frozen=True)
class Capability:
    feature: str
    since: int | None = None  # available from this version
    until: int | None = None  # available up to and including this version
    note: str = ""


# --- Model renames -----------------------------------------------------------
MODEL_RENAMES: tuple[ModelRename, ...] = (
    # MERGE, not a rename: account.move (journal entries) already exists on v10-12
    # as a distinct model; account.invoice (invoices) was folded into it at v13.
    ModelRename(
        "account.invoice", "account.move", 13,
        "Invoices merged into account.move in v13; account.move pre-exists as journal entries",
        merge=True,
    ),
    ModelRename(
        "account.invoice.line", "account.move.line", 13,
        "Invoice lines merged into account.move.line in v13; account.move.line pre-exists",
        merge=True,
    ),
    # True rename: stock.package did not exist before v19.
    ModelRename(
        "stock.quant.package", "stock.package", 19, "Package model renamed (best-effort; saas~19.3)"
    ),
)

# --- Field renames -----------------------------------------------------------
FIELD_RENAMES: tuple[FieldRename, ...] = (
    FieldRename(
        "account.move.line",
        "analytic_account_id",
        "analytic_distribution",
        16,
        "Analytic accounting became distribution-based in v16",
    ),
)

# --- Field removals ----------------------------------------------------------
FIELD_REMOVED: tuple[FieldRemoved, ...] = (
    FieldRemoved(
        "product.template",
        "uom_po_id",
        17,
        use_instead="uom_id",
        note="Purchase UoM unified into uom_id (best-effort boundary)",
    ),
    FieldRemoved(
        "res.partner",
        "company_type",
        19,
        use_instead="is_company",
        note="company_type dropped; use is_company boolean (best-effort; saas~19.3)",
    ),
)

# --- Capabilities ------------------------------------------------------------
CAPABILITIES: tuple[Capability, ...] = (
    Capability("api_key_auth", since=14, note="API keys introduced in v14; older needs password"),
    Capability(
        "jsonrpc_api_key",
        until=16,
        note="/jsonrpc execute_kw rejects API keys on v17+; use XML-RPC (auto-fallback handles it)",
    ),
    Capability(
        "update_field_translations",
        since=16,
        note="Native translation write API; older versions need per-lang context writes",
    ),
)

# --- Edition-only models (heuristic; runtime probe is authoritative) ---------
# Presence of these models strongly implies Enterprise. The compat layer only
# BLOCKS when edition was positively detected as community.
ENTERPRISE_ONLY_MODELS: frozenset[str] = frozenset(
    {
        "documents.document",
        "sign.request",
        "account.consolidation.period",
        "quality.check",  # quality is EE in most lines
        "helpdesk.ticket",
        "planning.slot",
        "appraisal.appraisal",
    }
)
