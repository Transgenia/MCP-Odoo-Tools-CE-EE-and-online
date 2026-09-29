# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Declarative cross-version delta map for Odoo 10-19.

This is DATA, not logic. New deltas are added here and covered by table-driven
tests. All entries reflect publicly known Odoo API/schema changes; version
boundaries marked "best-effort" should be confirmed by a live probe when a user
reports a mismatch (that is what the compat layer's graceful errors are for).

Conventions:
  * ``changed_in`` = the first major version where the NEW name/behavior applies.
  * ``since`` = feature/model available from this major version onward.
  * ``until`` = feature/model available up to and including this major version.
  * ``removed_in`` + ``removed_in_minor`` = the first series without the field.
    Odoo Online runs saas~<major>.N lines between two stable series
    (18.0 < saas~18.1 < ... < saas~18.4 < 19.0), and a removal often lands on a
    saas line first: ``(18, 1)`` means gone from saas~18.1 and from 19.0 on.
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
    removed_in_minor: int = 0

    @property
    def removed_in_series(self) -> tuple[int, int]:
        return (self.removed_in, self.removed_in_minor)


@dataclass(frozen=True)
class MethodDelta:
    """An ORM method that appears, disappears or is superseded on a series.

    ``since`` is the first ``(major, minor)`` series that has the method,
    ``removed_in`` the first one without it. ``prefer_from`` is the first series
    where the plugin calls ``use_instead`` instead, although the method may
    still exist there.
    """

    method: str
    since: tuple[int, int] | None = None
    removed_in: tuple[int, int] | None = None
    use_instead: str = ""
    prefer_from: tuple[int, int] | None = None
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
        "stock.quant.package", "stock.package", 19, "Package model renamed in 19.0"
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
    # Boundaries checked against the public odoo/odoo source of every stable
    # and saas branch from 16.0 to saas-19.4.
    FieldRemoved(
        "product.template",
        "uom_po_id",
        18,
        use_instead="uom_id",
        note="Purchase UoM unified into uom_id (saas~18.1 on Odoo Online, 19.0 on-premise)",
        removed_in_minor=1,
    ),
    FieldRemoved(
        "res.partner",
        "company_type",
        19,
        use_instead="is_company",
        note="company_type dropped; use the is_company boolean (saas~19.1; still in 19.0)",
        removed_in_minor=1,
    ),
)

# --- Method deltas -----------------------------------------------------------
# Checked in odoo/orm/models.py and addons/web/models/models.py of saas-18.4,
# 19.0, saas-19.1 to saas-19.4 and master. A version clamped down from 20+ is
# (19, 99), past every saas~19 line, which matches 20.0 for these entries.
METHOD_DELTAS: tuple[MethodDelta, ...] = (
    MethodDelta(
        "formatted_read_group",
        since=(18, 4),
        note="the web module's grouping method, saas~18.4 and 19.0+",
    ),
    MethodDelta(
        "read_group",
        removed_in=(19, 1),
        use_instead="formatted_read_group",
        prefer_from=(18, 4),
        note="classic read_group: deprecated in 19.0, absent on saas~19.1 to saas~19.4, "
        "and back in 20.0 with the _read_group signature (tuples)",
    ),
    MethodDelta(
        "check_access_rights",
        removed_in=(19, 1),
        use_instead="has_access",
        note="deprecated in 19.0, removed from saas~19.1",
    ),
    MethodDelta("has_access", since=(18, 0), note="record-level access check, 18.0+"),
)

# --- Capabilities ------------------------------------------------------------
CAPABILITIES: tuple[Capability, ...] = (
    Capability("api_key_auth", since=14, note="API keys introduced in v14; older needs password"),
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
