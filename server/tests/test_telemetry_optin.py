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
    # Docs promise exact-token consent: ONLY "opt-in" enables telemetry.
    assert is_opted_in({"ODOO_TELEMETRY": "opt-in"}) is True
    assert is_opted_in({"ODOO_TELEMETRY": " OPT-IN "}) is True
    assert is_opted_in({"ODOO_TELEMETRY": "1"}) is False
    assert is_opted_in({"ODOO_TELEMETRY": "true"}) is False
    assert is_opted_in({"ODOO_TELEMETRY": "yes"}) is False
    assert is_opted_in({"ODOO_TELEMETRY": "on"}) is False


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


def test_transport_labels_allowlisted() -> None:
    for label in ("auto", "jsonrpc", "xmlrpc", "unknown"):
        payload = build_optin_payload(odoo_version_major=17, transport=label)
        assert payload["transport"] == label
    # Arbitrary text (hostnames, secrets) can never reach the payload.
    payload = build_optin_payload(odoo_version_major=17, transport="prod.internal")
    assert payload["transport"] == "unknown"
    payload = build_optin_payload(odoo_version_major=17, transport="APIKEY-123")
    assert payload["transport"] == "unknown"


def test_plugin_version_format() -> None:
    import re

    assert re.match(r"^\d+\.\d+\.\d+", telemetry.PLUGIN_VERSION)


def test_preview_tool_disabled_by_default(monkeypatch) -> None:
    from odoo_mcp.registry import ToolContext
    from odoo_mcp.tools.meta import odoo_telemetry_preview

    monkeypatch.delenv("ODOO_TELEMETRY", raising=False)
    res = odoo_telemetry_preview(ToolContext(session=None, manager=None), {})
    assert res["opted_in"] is False
    assert res["payload"] is None


def test_preview_tool_renders_payload_when_opted_in(monkeypatch) -> None:
    from odoo_mcp.compat import EnvFacts
    from odoo_mcp.registry import ToolContext
    from odoo_mcp.tools.meta import odoo_telemetry_preview

    class FakeTransport:
        active = "auto"

    class FakeSession:
        transport = FakeTransport()

        def facts(self) -> EnvFacts:
            return EnvFacts(version=17, edition="community", deployment="onprem")

    class FakeManager:
        def tool_calls_snapshot(self) -> dict:
            return {"odoo_version": 2}

    monkeypatch.setenv("ODOO_TELEMETRY", "opt-in")
    res = odoo_telemetry_preview(
        ToolContext(session=FakeSession(), manager=FakeManager()), {}
    )
    assert res["opted_in"] is True
    assert res["payload"]["odoo_version_major"] == 17
    assert res["payload"]["tool_calls_by_tool"] == {"odoo_version": 2}


def test_manager_counts_tool_calls() -> None:
    from odoo_mcp.tenancy import ConnectionManager

    manager = ConnectionManager.__new__(ConnectionManager)
    from odoo_mcp.config import Settings

    manager.__init__(Settings())
    manager.record_tool_call("odoo_search")
    manager.record_tool_call("odoo_search")
    assert manager.tool_calls_snapshot() == {"odoo_search": 2}
