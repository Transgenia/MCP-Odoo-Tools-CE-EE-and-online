# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Security: credentials must never leak via repr/str/log or the redacted view."""

from __future__ import annotations

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
    assert "example.odoo.com" in repr(s)
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
