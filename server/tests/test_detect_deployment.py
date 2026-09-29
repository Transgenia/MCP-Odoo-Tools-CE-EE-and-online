"""detect_deployment compares the host name, never a substring of the URL."""

from __future__ import annotations

import pytest

from odoo_mcp.compat.detect import detect_deployment


@pytest.mark.parametrize("url", [
    "https://acme.odoo.com",
    "https://acme.odoo.com/web",
    "https://ACME.Odoo.COM:443/odoo",
    "acme.odoo.com",
    "https://odoo.com",
    "https://acme.odoo.com./web",
    "acme.odoo.com.",
])
def test_odoo_com_hosts_are_saas(url: str) -> None:
    assert detect_deployment(url) == "saas"


@pytest.mark.parametrize("url", [
    "https://erp.example.com",
    "https://example.com/?next=.odoo.com",
    "https://evil-odoo.com",
    "https://acme.odoo.com.example.net",
    "https://user:acme.odoo.com@example.net/",
    "http://127.0.0.1:8069",
    "",
])
def test_other_hosts_are_onprem(url: str) -> None:
    assert detect_deployment(url) == "onprem"
