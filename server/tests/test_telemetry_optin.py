# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Tests for opt-in telemetry: default-off, allowlist-only, no PII."""

from __future__ import annotations

import pytest

from odoo_mcp import telemetry
from odoo_mcp.telemetry import assert_no_pii, build_optin_payload, is_opted_in


def test_default_is_disabled() -> None:
    assert is_opted_in({}) is False
    assert is_opted_in({"ODOO_TELEMETRY": ""}) is False
    assert is_opted_in({"ODOO_TELEMETRY": "off"}) is False


def test_explicit_opt_in_only() -> None:
    assert is_opted_in({"ODOO_TELEMETRY": "opt-in"}) is True
    assert is_opted_in({"ODOO_TELEMETRY": "1"}) is True
    assert is_opted_in({"ODOO_TELEMETRY": " True "}) is True
    assert is_opted_in({"ODOO_TELEMETRY": "yes-please"}) is False


def test_payload_has_only_allowed_keys() -> None:
    payload = build_optin_payload(
        odoo_version_major=17,
        odoo_edition="community",
        odoo_deployment="onprem",
        transport="auto",
        tool_calls_by_tool={"odoo_search_read": 3, "odoo_version": 1},
    )
    assert set(payload) <= telemetry.ALLOWED_KEYS
    assert payload["tool_calls_total"] == 4


def test_payload_drops_unknown_tool_names() -> None:
    payload = build_optin_payload(
        odoo_version_major=18,
        tool_calls_by_tool={"odoo_search_read": 2, "crm.lead": 9, "evil": 1},
    )
    assert payload["tool_calls_by_tool"] == {"odoo_search_read": 2}


def test_forbidden_keys_rejected() -> None:
    with pytest.raises(ValueError):
        assert_no_pii({"plugin_version": "0.1.0", "email": "a@b.c"})
    with pytest.raises(ValueError):
        assert_no_pii({"plugin_version": "0.1.0", "db": "prod"})
    with pytest.raises(ValueError):
        assert_no_pii({"plugin_version": "0.1.0", "tool_calls_by_tool": {"x": "a@b.c"}})


def test_version_range_enforced() -> None:
    with pytest.raises(ValueError):
        build_optin_payload(odoo_version_major=9)
    with pytest.raises(ValueError):
        build_optin_payload(odoo_version_major=20)
