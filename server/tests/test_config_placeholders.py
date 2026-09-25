# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Unresolved plugin placeholders (``${user_config.x}``) must read as unset."""

from __future__ import annotations

import pytest

from odoo_mcp.config import Settings


def test_unresolved_placeholders_are_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ODOO_URL", "https://example.odoo.com/")
    monkeypatch.setenv("ODOO_DB", "demo")
    monkeypatch.setenv("ODOO_LOGIN", "admin")
    monkeypatch.setenv("ODOO_API_KEY", "${user_config.odoo_api_key}")
    monkeypatch.setenv("ODOO_PASSWORD", "${user_config.odoo_password}")
    monkeypatch.setenv("ODOO_TRANSPORT_PREF", "${user_config.odoo_transport_pref}")
    monkeypatch.setenv("ODOO_READONLY", "${user_config.odoo_readonly}")
    s = Settings.from_env()
    assert s.url == "https://example.odoo.com"
    assert s.api_key == "" and s.password == "" and s.secret == ""
    assert s.transport_pref == "auto"
    assert s.readonly is False


def test_plugin_boolean_option_enables_readonly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ODOO_READONLY", "true")
    assert Settings.from_env().readonly is True


def test_credentials_keep_surrounding_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ODOO_PASSWORD", "  pass with spaces ")
    monkeypatch.setenv("ODOO_API_KEY", " key ")
    s = Settings.from_env()
    assert s.password == "  pass with spaces "
    assert s.api_key == " key "
