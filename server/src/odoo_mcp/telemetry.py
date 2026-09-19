# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Opt-in usage telemetry — disabled by default, no PII, no background sends.

Design contract (see SECURITY.md "Opt-in telemetry"):
  * Disabled unless the operator sets ``ODOO_TELEMETRY=opt-in`` explicitly.
  * No scheduler, no boot hook, no background thread, no network send inside
    this module. Sharing happens only when a human runs ``/odoo-doctor``,
    reads the exact payload on screen, and decides to paste it somewhere.
  * Payload allowlist ONLY (anything else is a bug):
    ``plugin_version``, ``odoo_version_major``, ``odoo_edition``,
    ``odoo_deployment``, ``transport``, ``tool_calls_total``,
    ``tool_calls_by_tool`` (keys restricted to known generic tool names).
  * NEVER collected, even under opt-in: URL, DB name, login/email, secrets,
    phone, company name, partner/lead records, module lists, revenues/billing,
    file paths, hostnames, or any free-text record content.
"""

from __future__ import annotations

import os

PLUGIN_VERSION = "0.1.0"

TELEMETRY_ENV_VAR = "ODOO_TELEMETRY"
OPT_IN_VALUES = {"1", "true", "yes", "on", "opt-in"}

ALLOWED_KEYS = frozenset(
    {
        "plugin_version",
        "odoo_version_major",
        "odoo_edition",
        "odoo_deployment",
        "transport",
        "tool_calls_total",
        "tool_calls_by_tool",
    }
)

# Generic tool names only — never model names, domains, ids, or values.
KNOWN_TOOLS = frozenset(
    {
        "odoo_version",
        "odoo_search",
        "odoo_read",
        "odoo_search_read",
        "odoo_search_count",
        "odoo_create",
        "odoo_write",
        "odoo_unlink",
        "odoo_execute",
        "odoo_fields_get",
        "odoo_list_models",
        "odoo_module_info",
        "odoo_export_records_json",
        "odoo_export_records_csv",
        "odoo_translate_get",
        "odoo_translate_set",
        "odoo_report",
        "odoo_connections",
        "odoo_add_field",
        "odoo_add_automation",
    }
)

FORBIDDEN_SUBSTRINGS = (
    "@",
    "http://",
    "https://",
    "odoo.com",
    ".env",
    "BEGIN PRIVATE",
)


def is_opted_in(env: dict[str, str] | None = None) -> bool:
    """Return True only on explicit opt-in. Default (unset/anything else) is False."""
    source = env if env is not None else os.environ
    raw = (source.get(TELEMETRY_ENV_VAR) or "").strip().lower()
    return raw in OPT_IN_VALUES


def _sanitize_counts(counts: dict[str, int] | None) -> dict[str, int]:
    clean: dict[str, int] = {}
    for tool, n in (counts or {}).items():
        if tool not in KNOWN_TOOLS:
            continue
        try:
            v = int(n)
        except (TypeError, ValueError):
            continue
        if v < 0:
            continue
        clean[tool] = v
    return clean


def assert_no_pii(payload: dict) -> None:
    """Guardrail: raise ValueError if the payload contains anything off-allowlist."""
    extra = set(payload) - ALLOWED_KEYS
    if extra:
        raise ValueError(f"telemetry payload has forbidden keys: {sorted(extra)}")
    blob = repr(payload)
    for bad in FORBIDDEN_SUBSTRINGS:
        if bad in blob:
            raise ValueError(f"telemetry payload looks like PII/secret ({bad!r} present)")


def build_optin_payload(
    *,
    odoo_version_major: int,
    odoo_edition: str = "unknown",
    odoo_deployment: str = "unknown",
    transport: str = "unknown",
    tool_calls_by_tool: dict[str, int] | None = None,
) -> dict:
    """Build the minimal opt-in payload. Raises on out-of-range input."""
    if not 10 <= int(odoo_version_major) <= 19:
        raise ValueError("odoo_version_major must be 10-19")
    edition = (odoo_edition or "unknown").strip().lower()
    if edition not in ("community", "enterprise", "unknown"):
        edition = "unknown"
    deployment = (odoo_deployment or "unknown").strip().lower()
    if deployment not in ("onprem", "saas", "unknown"):
        deployment = "unknown"
    counts = _sanitize_counts(tool_calls_by_tool)
    payload = {
        "plugin_version": PLUGIN_VERSION,
        "odoo_version_major": int(odoo_version_major),
        "odoo_edition": edition,
        "odoo_deployment": deployment,
        "transport": str(transport),
        "tool_calls_total": sum(counts.values()),
        "tool_calls_by_tool": counts,
    }
    assert_no_pii(payload)
    return payload
