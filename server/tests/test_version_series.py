# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Stable vs Odoo Online (saas~N.M) series, name_get, the runtime version, auth checks."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest

import odoo_mcp
from odoo_mcp.compat import EnvFacts, probe, resolve_field
from odoo_mcp.compat.detect import parse_major, parse_version
from odoo_mcp.errors import AuthError
from odoo_mcp.registry import ToolContext
from odoo_mcp.session import Credentials, OdooSession
from odoo_mcp.telemetry import PLUGIN_VERSION
from odoo_mcp.tools.meta import odoo_version

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"server_version": "18.0", "server_version_info": [18, 0, 0, "final", 0, ""]}, (18, 0)),
        ({"server_version": "10.0", "server_version_info": [10, 0, 0, "final", 0, ""]}, (10, 0)),
        # Odoo Online: release.py has version_info = ('saas~18', 1, 0, FINAL, 0, '')
        ({"server_version": "saas~18.1+e",
          "server_version_info": ["saas~18", 1, 0, "final", 0, "e"]}, (18, 1)),
        ({"server_version": "saas~17.2+e"}, (17, 2)),
        ({"server_version": "16.0+e"}, (16, 0)),
        ({"server_version": "18.0-20260908"}, (18, 0)),
        ({"server_version_info": [16]}, (16, 0)),
        ({}, (19, 0)),
    ],
)
def test_parse_version(payload: dict[str, Any], expected: tuple[int, int]) -> None:
    major, minor, _raw = parse_version(payload)
    assert (major, minor) == expected
    assert parse_major(payload)[0] == expected[0]


def test_probe_keeps_the_saas_line() -> None:
    facts = probe("https://acme.odoo.com", {
        "server_version": "saas~19.1+e", "server_version_info": ["saas~19", 1, 0, "final", 0, "e"]})
    assert facts.series == (19, 1)
    assert facts.edition == "enterprise" and facts.deployment == "saas"
    assert resolve_field("res.partner", "company_type", facts) is None


def test_saas_lines_sort_between_stable_series() -> None:
    def removed(version: int, minor: int) -> bool:
        return resolve_field("product.template", "uom_po_id",
                             EnvFacts(version, "community", "onprem", minor=minor)) is None
    assert [removed(*s) for s in [(18, 0), (18, 1), (18, 4), (19, 0)]] == [False, True, True, True]


def test_clamp_from_a_newer_major_keeps_later_removals() -> None:
    newer = EnvFacts(20, "community", "onprem", "20.0").clamp()
    assert newer.version == 19 and newer.minor > 4
    assert resolve_field("res.partner", "company_type", newer) is None
    older = EnvFacts(9, "community", "onprem", "9.0", 3).clamp()
    assert older.series == (10, 0)


class _NameTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[Any], dict[str, Any] | None]] = []

    def version(self) -> dict[str, Any]:
        return {"server_version": "18.0", "server_version_info": [18, 0, 0, "final", 0, ""]}

    def authenticate(self, db: str, login: str, secret: str) -> int:
        return 2

    def execute_kw(self, db: str, uid: int, secret: str, model: str, method: str,
                   args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        self.calls.append((model, method, args, kwargs))
        if method == "name_get":  # what Odoo 18 answers
            raise AssertionError("The method 'res.partner.name_get' does not exist")
        return [{"id": i, "display_name": f"Partner {i}"} for i in args[0]]


def test_name_get_reads_display_name() -> None:
    session = OdooSession(Credentials("https://odoo.example", "db", "me", "k"), timeout=5)
    transport = _NameTransport()
    session.transport = transport  # type: ignore[assignment]
    assert session.name_get("res.partner", [3, 1]) == [[3, "Partner 3"], [1, "Partner 1"]]
    assert transport.calls[-1] == ("res.partner", "read", [[3, 1]], {"fields": ["display_name"]})


def test_runtime_version_is_the_release_version() -> None:
    pyproject = (ROOT / "server" / "pyproject.toml").read_text()
    release = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    assert release
    assert odoo_mcp.__version__ == PLUGIN_VERSION == release.group(1)


def _load_smoke() -> Any:
    spec = importlib.util.spec_from_file_location(
        "sandbox_smoke", ROOT / "scripts" / "sandbox_smoke.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["sandbox_smoke"] = module
    spec.loader.exec_module(module)
    return module


def test_smoke_reports_a_table_that_disagrees_with_the_live_model(monkeypatch) -> None:
    smoke = _load_smoke()
    live = {"res.partner": {"name", "is_company"}}  # an instance without company_type

    def fake_tool(proc: Any, msg_id: int, name: str, arguments: dict[str, Any]) -> dict:
        if name == "odoo_list_models":
            return {"models": [{"model": m} for m in live if m == arguments["like"]]}
        return {"fields": {name: {} for name in live[arguments["model"]]}}

    monkeypatch.setattr(smoke, "tool", fake_tool)
    report = smoke.check_deltas(None, 3, {"raw_version": "18.0"})
    assert report["checked"] == ["res.partner.company_type -> company_type"]
    assert any("product.template.uom_po_id" in s for s in report["skipped"])
    assert report["mismatches"] and "lacks 'company_type'" in report["mismatches"][0]
    live["res.partner"].add("company_type")
    assert smoke.check_deltas(None, 3, {"raw_version": "18.0"})["mismatches"] == []


# --- a wrong password must never look like a working connection -------------


class _BadAuthTransport(_NameTransport):
    def __init__(self, version_string: str) -> None:
        super().__init__()
        self.version_string = version_string

    def version(self) -> dict[str, Any]:
        return {"server_version": self.version_string}

    def authenticate(self, db: str, login: str, secret: str) -> int:
        raise AuthError("xmlrpc authenticate returned no uid (bad credentials/db)")


@pytest.mark.parametrize("version_string", ["18.0", "18.0+e"])
def test_odoo_version_signs_in_first(version_string: str) -> None:
    # "18.0+e" never reaches the module probe, so only signing in catches it
    session = OdooSession(Credentials("https://odoo.example", "db", "me", "wrong"), timeout=5)
    session.transport = _BadAuthTransport(version_string)  # type: ignore[assignment]
    with pytest.raises(AuthError):
        odoo_version(ToolContext(session=session, manager=None), {})


def test_probe_does_not_hide_bad_credentials() -> None:
    def module_installed(name: str) -> bool:
        raise AuthError("bad credentials")

    with pytest.raises(AuthError):
        probe("https://odoo.example", {"server_version": "17.0"}, module_installed)

    def flaky(name: str) -> bool:
        raise TimeoutError("probe timed out")

    assert probe("https://odoo.example", {"server_version": "17.0"}, flaky).edition == "unknown"


def test_credentials_repr_hides_the_secret() -> None:
    creds = Credentials("https://odoo.example", "db", "me", "S3CRET-VALUE")
    assert "S3CRET-VALUE" not in repr(creds)
    assert creds.secret == "S3CRET-VALUE"
