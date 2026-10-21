# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Security: credentials must never leak via repr/str/log or the redacted view."""

from __future__ import annotations

import json
import re

from odoo_mcp.config import Settings

SECRET = "sup3r-secret-api-key-DO-NOT-LEAK"
PASSWORD = "pl4in-text-password-DO-NOT-LEAK"


def _settings() -> Settings:
    return Settings(
        url="https://example.odoo.com",
        db="demo",
        login="admin",
        api_key=SECRET,
        password=PASSWORD,
    )


def test_repr_and_str_do_not_leak_secret() -> None:
    s = _settings()
    for text in (repr(s), str(s), f"{s}", f"config={s!r}"):
        assert SECRET not in text
        assert PASSWORD not in text
    # but it should still be useful for debugging
    assert re.search(r"\bexample\.odoo\.com\b", repr(s))
    assert "has_secret" in repr(s)


def test_redacted_has_no_secret_values() -> None:
    red = _settings().redacted()
    assert SECRET not in red.values()
    assert PASSWORD not in red.values()
    assert "api_key" not in red and "password" not in red and "secret" not in red
    assert red["has_secret"] is True


def test_from_env_does_not_leak(monkeypatch) -> None:
    monkeypatch.setenv("ODOO_URL", "https://x.odoo.com")
    monkeypatch.setenv("ODOO_DB", "d")
    monkeypatch.setenv("ODOO_LOGIN", "u")
    monkeypatch.setenv("ODOO_API_KEY", SECRET)
    s = Settings.from_env()
    assert SECRET not in repr(s)
    assert s.secret == SECRET  # still accessible programmatically


def _policy_settings() -> Settings:
    s = _settings()
    s.policy_profile = "builder"
    s.policy_file = "/home/someone/.config/odoo-tools/policy.json"
    s.audit_dir = "/data/odoo-tools/audit"
    s.audit_retention_days = 30
    return s


def test_the_policy_fields_leak_nothing() -> None:
    s = _policy_settings()
    for text in (repr(s), str(s), f"{s}", json.dumps(s.redacted())):
        assert SECRET not in text
        assert PASSWORD not in text
    red = s.redacted()
    # the profile and the file path are not secrets; the audit folder is reduced to a flag
    assert red["policy_profile"] == "builder"
    assert red["policy_file"] == "/home/someone/.config/odoo-tools/policy.json"
    assert red["audit"] is True and "audit_dir" not in red
    assert "policy_profile" in repr(s) and "audit" in repr(s)


def test_the_policy_fields_from_env_leak_nothing(monkeypatch) -> None:
    monkeypatch.setenv("ODOO_API_KEY", SECRET)
    monkeypatch.setenv("ODOO_POLICY", "Standard")
    monkeypatch.setenv("ODOO_POLICY_FILE", "/etc/odoo-tools/policy.json")
    monkeypatch.setenv("ODOO_AUDIT_DIR", "off")
    s = Settings.from_env()
    assert SECRET not in repr(s)
    assert (s.policy_profile, s.policy_file, s.redacted()["audit"]) == (
        "standard", "/etc/odoo-tools/policy.json", False)


def test_the_policy_never_sees_a_credential() -> None:
    # The policy is built from the settings, but keeps nothing of the connection.
    from odoo_mcp.policy import load_policy

    p = load_policy(_policy_settings(), ["odoo_version"])
    assert p.locked and p.error_code == "E3"  # the file does not exist here
    for text in (repr(p), json.dumps(p.describe()), str(p.lock_error())):
        assert SECRET not in text and PASSWORD not in text
