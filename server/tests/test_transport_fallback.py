# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Regression guard: JSON-RPC api-key rejection must fall back to XML-RPC once."""

from __future__ import annotations

import logging

from odoo_mcp.transport.fallback import FallbackTransport
from odoo_mcp.transport.jsonrpc import ApiKeyRejected


class _FakeJson:
    def __init__(self) -> None:
        self.calls = 0

    def execute_kw(self, *a, **k):
        self.calls += 1
        raise ApiKeyRejected("API key is not supported on /jsonrpc")

    def version(self):
        return {"server_version": "17.0"}

    def authenticate(self, *a, **k):
        return 1


class _FakeXml:
    def __init__(self) -> None:
        self.calls = 0

    def execute_kw(self, *a, **k):
        self.calls += 1
        return [{"id": 1, "name": "ok-via-xmlrpc"}]

    def version(self):
        return {"server_version": "17.0"}

    def authenticate(self, *a, **k):
        return 1


def _wire(monkeypatch) -> tuple[FallbackTransport, _FakeJson, _FakeXml]:
    ft = FallbackTransport("https://example.odoo.com", pref="auto")
    fake_json, fake_xml = _FakeJson(), _FakeXml()
    monkeypatch.setattr(ft, "_jsonrpc", lambda: fake_json)
    monkeypatch.setattr(ft, "_xmlrpc", lambda: fake_xml)
    return ft, fake_json, fake_xml


def test_fallback_to_xmlrpc_on_api_key_rejection(monkeypatch, caplog) -> None:
    ft, fake_json, fake_xml = _wire(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="odoo_mcp.transport"):
        result = ft.execute_kw("db", 1, "key", "res.partner", "search_read", [[]], {})
    assert result == [{"id": 1, "name": "ok-via-xmlrpc"}]
    assert fake_json.calls == 1  # tried jsonrpc once
    assert fake_xml.calls == 1  # then xmlrpc
    assert ft.active == "xmlrpc"  # pinned after fallback
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_no_repeated_jsonrpc_after_pin(monkeypatch) -> None:
    ft, fake_json, fake_xml = _wire(monkeypatch)
    ft.execute_kw("db", 1, "key", "res.partner", "read", [[1]], {})
    ft.execute_kw("db", 1, "key", "res.partner", "read", [[2]], {})
    assert fake_json.calls == 1  # never retried jsonrpc after the pin
    assert fake_xml.calls == 2


def test_pref_xmlrpc_skips_jsonrpc(monkeypatch) -> None:
    ft = FallbackTransport("https://x.example.com", pref="xmlrpc")
    fake_json, fake_xml = _FakeJson(), _FakeXml()
    monkeypatch.setattr(ft, "_jsonrpc", lambda: fake_json)
    monkeypatch.setattr(ft, "_xmlrpc", lambda: fake_xml)
    ft.execute_kw("db", 1, "pw", "res.partner", "read", [[1]], {})
    assert fake_json.calls == 0
    assert fake_xml.calls == 1
