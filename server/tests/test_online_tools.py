# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The Odoo Online tools: profile, API catalog, access check, documents, imports."""

from __future__ import annotations

import csv
import datetime
import io
import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fake_odoo_http import FakeOdoo, json_reply, version_payload

from odoo_mcp.compat import EnvFacts
from odoo_mcp.config import Settings
from odoo_mcp.errors import CompatError, OdooFault, TransportError
from odoo_mcp.registry import ToolContext, registry
from odoo_mcp.server import McpServer, check_readonly
from odoo_mcp.session import Credentials, OdooSession
from odoo_mcp.support import INSTRUCTIONS
from odoo_mcp.telemetry import KNOWN_TOOLS
from odoo_mcp.tools import online
from odoo_mcp.tools.online import (
    IMPORT_OPTIONS,
    IMPORT_TRANSPORTS,
    MAX_CATALOG_METHODS,
    MAX_MESSAGES,
    builtin_methods,
    deployment_evidence,
    odoo_access_check,
    odoo_api_catalog,
    odoo_import,
    odoo_import_preview,
    odoo_online_profile,
    odoo_record_documents,
    series_label,
)
from odoo_mcp.transport.fallback import FallbackTransport
from odoo_mcp.transport.jsonrpc import JsonRpcUnavailable

ROOT = Path(__file__).resolve().parents[2]
KEY = "K3Y-ONLINE-DO-NOT-LEAK-0123456789abcdef0"
NOW = datetime.datetime(2026, 9, 28, 12, 0, 0, tzinfo=datetime.timezone.utc)

NEW_TOOLS = ("odoo_online_profile", "odoo_api_catalog", "odoo_access_check",
             "odoo_record_documents", "odoo_import_preview", "odoo_import")
WRITE_TOOLS = ("odoo_import_preview", "odoo_import")


# --- a scripted session --------------------------------------------------------

class FakeTransport:
    def __init__(self, active: str = "jsonrpc(auto)", series: tuple[int, int] | None = None,
                 json2_available: bool = False, notice: str | None = None,
                 secret_kind: str = "api_key") -> None:
        self.active = active
        self.series = series
        self.json2_available = json2_available
        self.transport_notice = notice
        self.secret_kind = secret_kind


Handler = Callable[..., Any]


class FakeSession:
    """Answers ``execute`` from ``handlers[(model, method)]`` and records every call."""

    def __init__(self, version: int = 18, *, minor: int = 0, raw: str | None = None,
                 deployment: str = "onprem", edition: str = "community",
                 transport: FakeTransport | None = None, uid: int = 2,
                 fields: dict[str, dict[str, Any]] | None = None,
                 modules: set[str] | None = None, doc: Any = None,
                 secret_kind: str = "api_key", missing: set[str] | None = None) -> None:
        raw = raw if raw is not None else (f"saas~{version}.{minor}" if minor
                                           else f"{version}.0")
        self._facts = EnvFacts(version=version, edition=edition, deployment=deployment,
                               raw_version=raw, minor=minor)
        self.transport = transport or FakeTransport(series=(version, minor))
        self.uid = uid
        self.creds = Credentials(url="https://odoo.example", db="db", login="admin",
                                 secret=KEY, secret_kind=secret_kind)
        self.fields = fields or {}
        self.modules = modules if modules is not None else {"base_import"}
        self.doc = doc
        self.missing = missing or set()
        self.handlers: dict[tuple[str, str], Handler] = {}
        self.calls: list[dict[str, Any]] = []

    def facts(self) -> EnvFacts:
        return self._facts

    def version_info(self) -> dict[str, Any]:
        return {"server_version": self._facts.raw_version}

    def module_installed(self, name: str) -> bool:
        return name in self.modules

    def fields_get(self, model: str, attributes: list[str] | None = None) -> dict[str, Any]:
        self.calls.append({"model": model, "method": "fields_get", "attributes": attributes})
        if model in self.missing:
            raise OdooFault(f"werkzeug.exceptions.NotFound: the model '{model}' does not exist")
        return self.fields.get(model, {})

    def name_get(self, model: str, ids: list[int]) -> list[list[Any]]:
        return [[i, f"{model} {i}"] for i in ids]

    def api_doc(self, model: str) -> Any:
        self.calls.append({"model": model, "method": "api_doc"})
        if isinstance(self.doc, BaseException):
            raise self.doc
        return self.doc

    def execute(self, model: str, method: str, args: list[Any] | None = None,
                kwargs: dict[str, Any] | None = None, *, ids: Any = None,
                transports: Any = None) -> Any:
        call = {"model": model, "method": method, "args": args or [], "kwargs": kwargs or {},
                "ids": ids, "transports": transports}
        self.calls.append(call)
        handler = self.handlers.get((model, method))
        if handler is None:
            raise AssertionError(f"unexpected call {model}.{method}")
        return handler(*(args or []), **(kwargs or {})) if ids is None else handler(
            ids, *(args or []), **(kwargs or {}))

    def executed(self, method: str | None = None) -> list[dict[str, Any]]:
        return [c for c in self.calls if "args" in c and (method is None or c["method"] == method)]


def _ctx(session: FakeSession) -> ToolContext:
    return ToolContext(session=session, manager=None)


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(online, "_now", lambda: NOW)


# --- the tool surface ------------------------------------------------------------

def test_the_six_tools_are_registered_with_the_right_read_only_flag() -> None:
    names = {t.name for t in registry.all()}
    assert set(NEW_TOOLS) <= names
    for name in NEW_TOOLS:
        assert registry.get(name).read_only is (name not in WRITE_TOOLS), name


@pytest.mark.parametrize("name", WRITE_TOOLS)
def test_import_tools_say_they_write_and_are_refused_in_read_only_mode(name: str) -> None:
    tool = registry.get(name)
    assert "(write operation)" in tool.description
    assert "refused in read-only mode (ODOO_READONLY)" in tool.description
    with pytest.raises(CompatError, match="ODOO_READONLY"):
        check_readonly(Settings(readonly=True), tool)


@pytest.mark.parametrize("name", WRITE_TOOLS)
def test_read_only_mode_refuses_imports_before_any_session_exists(name: str) -> None:
    server = McpServer(Settings(readonly=True))  # no credentials at all
    built: list[str] = []
    server.manager.default = lambda: built.append("session")  # type: ignore[method-assign]
    result = server.call_tool({"name": name, "arguments": {
        "model": "res.partner", "fields": ["name"], "rows": [["x"]]}})
    assert result["isError"] is True
    assert "ODOO_READONLY" in result["content"][0]["text"]
    assert built == []


@pytest.mark.parametrize("name", [n for n in NEW_TOOLS if n not in WRITE_TOOLS])
def test_the_read_tools_pass_read_only_mode(name: str) -> None:
    check_readonly(Settings(readonly=True), registry.get(name))


def test_every_registered_tool_is_known_to_telemetry_and_its_schema() -> None:
    assert {t.name for t in registry.all()} == set(KNOWN_TOOLS)
    schema = json.loads((ROOT / "docs" / "telemetry-schema.json").read_text())
    (pattern,) = schema["properties"]["tool_calls_by_tool"]["patternProperties"]
    assert set(re.fullmatch(r"\^\((.*)\)\$", pattern).group(1).split("|")) == set(KNOWN_TOOLS)


def test_the_instructions_name_every_write_tool() -> None:
    for tool in registry.all():
        if not tool.read_only:
            assert tool.name in INSTRUCTIONS, tool.name
    assert "odoo_online_profile" in INSTRUCTIONS


# --- helpers ---------------------------------------------------------------------

@pytest.mark.parametrize("series, raw, label", [
    ((19, 0), "19.0", "19.0"),
    ((18, 4), "saas~18.4", "saas~18.4"),
    ((19, 2), "saas~19.2+e", "saas~19.2"),
    ((20, 0), "20.0", "20.0"),
])
def test_series_label(series: tuple[int, int], raw: str, label: str) -> None:
    assert series_label(series, raw) == label


@pytest.mark.parametrize("deployment, raw, expected", [
    ("onprem", "saas~19.2+e", ("saas", "version")),  # Online on its own domain
    ("saas", "saas~18.4", ("saas", "version")),
    ("saas", "19.0+e", ("saas", "host")),  # *.odoo.com: Online or Odoo.sh
    ("onprem", "18.0", ("onprem", "host")),
    ("weird", "18.0", ("unknown", "host")),
])
def test_deployment_evidence(deployment: str, raw: str, expected: tuple[str, str]) -> None:
    facts = EnvFacts(version=19, edition="enterprise", deployment=deployment, raw_version=raw)
    got = deployment_evidence(facts)
    assert got[:2] == expected and got[2]


def test_deployment_evidence_prefers_a_confidence_the_facts_carry() -> None:
    class Facts:
        deployment, deployment_confidence, raw_version = "onprem", "override", "saas~19.2"

    assert deployment_evidence(Facts()) == ("onprem", "override",  # type: ignore[arg-type]
                                            "set by ODOO_DEPLOYMENT")


# --- odoo_online_profile ------------------------------------------------------

def _profile_session(version: int = 19, minor: int = 0, **kw: Any) -> FakeSession:
    fields = {
        "res.users": {f: {"type": "char"} for f in
                      ("login", "name", "company_id", "company_ids", "totp_enabled")},
        "res.users.apikeys": {f: {"type": "char"} for f in
                              ("name", "scope", "create_date", "expiration_date", "user_id")},
        "ir.module.module": {f: {"type": "char"} for f in
                             ("name", "shortdesc", "application", "imported", "state")},
    }
    fields.update(kw.pop("fields", {}))
    session = FakeSession(version, minor=minor, fields=fields, **kw)
    session.handlers.update({
        ("res.users", "context_get"): lambda: {"lang": "es_MX", "tz": "America/Mexico_City",
                                               "uid": 2},
        ("res.users", "read"): lambda ids, fields: [{
            "id": 2, "login": "bot@example.com", "name": "Bot", "company_id": [1, "Main"],
            "company_ids": [1, 3], "totp_enabled": False}],
        ("res.users.apikeys", "search_read"): lambda domain, fields: [
            {"id": 4, "name": "claude", "scope": "rpc", "create_date": "2026-09-27 12:00:00",
             "expiration_date": "2026-09-29 00:00:00", "key": "MUST-NOT-APPEAR"},
            {"id": 5, "name": "old", "scope": False, "create_date": "2026-01-01 00:00:00",
             "expiration_date": False},
        ],
        ("ir.module.module", "search_read"): lambda domain, fields, order: [
            {"name": "sale_management", "shortdesc": "Sales", "application": True,
             "imported": False},
            {"name": "web_studio", "shortdesc": "Studio", "application": True,
             "imported": False},
            {"name": "x_catalog_data", "shortdesc": "Catalog data", "application": False,
             "imported": True},
        ],
    })
    return session


def test_profile_on_19_with_an_api_key_and_json2() -> None:
    session = _profile_session(transport=FakeTransport(
        active="json2", series=(19, 0), json2_available=True), doc={"methods": {}})
    out = odoo_online_profile(_ctx(session), {})
    assert out["series"] == "19.0" and out["line"] == "stable"
    assert (out["deployment"], out["deployment_confidence"]) == ("onprem", "host")
    assert out["transport"] == "json2" and out["credential"] == "api_key"
    assert out["json2_available"] is True and out["doc_bearer"] is True
    assert out["legacy_rpc"]["available_on_this_series"] is True
    assert out["legacy_rpc"]["removed_on_odoo_online"].startswith("saas~21.1")
    user = out["user"]
    assert user["login"] == "bot@example.com" and user["company"] == [1, "Main"]
    assert user["companies"] == [[1, "res.company 1"], [3, "res.company 3"]]
    assert (user["lang"], user["tz"], user["totp_enabled"]) == (
        "es_MX", "America/Mexico_City", False)
    assert out["api_keys"] == [
        {"name": "claude", "scope": "rpc", "create_date": "2026-09-27 12:00:00",
         "expiration_date": "2026-09-29 00:00:00", "expires_in_hours": 12.0},
        {"name": "old", "scope": None, "create_date": "2026-01-01 00:00:00",
         "expiration_date": None, "expires_in_hours": None},
    ]
    assert "MUST-NOT-APPEAR" not in json.dumps(out) and KEY not in json.dumps(out)
    assert [a["name"] for a in out["applications"]] == ["sale_management", "web_studio"]
    assert out["imported_modules"] == [{"name": "x_catalog_data", "title": "Catalog data"}]
    assert out["studio_installed"] is True
    assert any("expires in 12.0 h" in h for h in out["hints"])
    assert out["online_hints_apply"] is False and len(out["online_hints"]) == 5
    assert "unavailable" not in out
    apikeys = next(c for c in session.executed("search_read")
                   if c["model"] == "res.users.apikeys")
    assert apikeys["args"] == [[["user_id", "=", 2]]]
    assert apikeys["kwargs"]["fields"] == ["name", "scope", "create_date", "expiration_date"]
    modules = next(c for c in session.executed("search_read")
                   if c["model"] == "ir.module.module")
    assert modules["args"][0] == [["state", "=", "installed"], "|", "|",
                                  ["application", "=", True], ["name", "=", "web_studio"],
                                  ["imported", "=", True]]


def test_profile_on_an_online_saas_line_with_a_custom_domain() -> None:
    session = _profile_session(19, 2, raw="saas~19.2+e", edition="enterprise",
                               deployment="onprem",
                               transport=FakeTransport(active="json2", series=(19, 2),
                                                       json2_available=True), doc=None)
    out = odoo_online_profile(_ctx(session), {})
    assert out["series"] == "saas~19.2" and out["line"] == "saas"
    assert (out["deployment"], out["deployment_confidence"]) == ("saas", "version")
    assert out["online_hints_apply"] is True
    assert out["doc_bearer"] is False  # 19.x, API key, but not an administrator's


def test_profile_on_13_degrades_per_version() -> None:
    session = _profile_session(13, fields={
        "res.users": {f: {} for f in ("login", "name", "company_id", "company_ids")},
        "ir.module.module": {f: {} for f in ("name", "shortdesc", "application")},
    }, transport=FakeTransport(active="jsonrpc(auto)", series=(13, 0)),
        secret_kind="password")
    session.handlers[("ir.module.module", "search_read")] = lambda domain, fields, order: [
        {"name": "sale", "shortdesc": "Sales", "application": True}]
    out = odoo_online_profile(_ctx(session), {})
    assert out["api_keys"] is None and "14" in out["unavailable"]["api_keys"]
    assert out["user"]["totp_enabled"] is None
    assert out["imported_modules"] is None and out["studio_installed"] is False
    assert out["doc_bearer"] is None and out["credential"] == "password"
    assert not any(c["model"] == "res.users.apikeys" for c in session.calls)
    read = next(c for c in session.executed("read") if c["model"] == "res.users")
    assert read["kwargs"]["fields"] == ["login", "name", "company_id", "company_ids"]
    modules = next(c for c in session.executed("search_read"))
    assert modules["args"][0] == [["state", "=", "installed"], "|",
                                  ["application", "=", True], ["name", "=", "web_studio"]]


def test_profile_records_a_refused_section_and_keeps_the_rest() -> None:
    session = _profile_session()

    def refuse(domain: Any, fields: Any) -> Any:
        raise OdooFault("odoo.exceptions.AccessError: not allowed")

    session.handlers[("res.users.apikeys", "search_read")] = refuse
    out = odoo_online_profile(_ctx(session), {})
    assert out["api_keys"] is None
    assert "AccessError" in out["unavailable"]["api_keys"]
    assert out["user"]["login"] == "bot@example.com" and out["applications"]


def test_profile_reports_expired_keys_and_the_transport_notice() -> None:
    session = _profile_session(transport=FakeTransport(
        active="jsonrpc(auto)", series=(19, 0), notice="Odoo 19 deprecates /xmlrpc"))
    session.handlers[("res.users.apikeys", "search_read")] = lambda domain, fields: [
        {"name": "gone", "scope": "rpc", "create_date": "2026-09-01 00:00:00",
         "expiration_date": "2026-09-27 12:00:00"}]
    out = odoo_online_profile(_ctx(session), {})
    assert out["api_keys"][0]["expires_in_hours"] == -24.0
    assert "1 API key(s) of this user have expired" in out["hints"][0]
    assert not any("expires in" in h for h in out["hints"])  # expired keys are not in use
    assert "Odoo 19 deprecates /xmlrpc" in out["hints"]
    assert out["transport_notice"] == "Odoo 19 deprecates /xmlrpc"
    assert out["doc_bearer"] is None  # JSON-2 not available: no /doc-bearer probe
    assert not any(c["method"] == "api_doc" for c in session.calls)


def test_no_key_hint_when_the_plugin_signs_in_with_a_password() -> None:
    session = _profile_session(secret_kind="password")
    out = odoo_online_profile(_ctx(session), {})
    assert not any("expires in" in h for h in out["hints"])


@pytest.mark.parametrize("series, available", [((20, 0), True), ((21, 0), True),
                                               ((21, 1), False), ((22, 0), False)])
def test_profile_uses_the_unclamped_series(series: tuple[int, int], available: bool) -> None:
    session = _profile_session(19, transport=FakeTransport(active="json2", series=series))
    out = odoo_online_profile(_ctx(session), {})
    assert (out["version"], out["minor"]) == series
    assert out["legacy_rpc"]["available_on_this_series"] is available


def test_profile_doc_bearer_failure_is_reported_not_raised() -> None:
    session = _profile_session(transport=FakeTransport(
        active="json2", series=(19, 0), json2_available=True),
        doc=TransportError("json2: HTTP 502"))
    out = odoo_online_profile(_ctx(session), {})
    assert out["doc_bearer"] is False and "502" in out["unavailable"]["doc_bearer"]


# --- odoo_api_catalog ------------------------------------------------------------

def _catalog_session(version: int = 19, minor: int = 0, *, json2: bool = True,
                     doc: Any = None, exists: bool = True) -> FakeSession:
    return FakeSession(version, minor=minor, doc=doc, transport=FakeTransport(
        active="json2" if json2 else "jsonrpc(auto)", series=(version, minor),
        json2_available=json2), missing=set() if exists else {"x.nope", "res.partner"})


DOC = {"model": "res.partner", "methods": {
    "search_read": {"signature": "(domain=None, fields=None, offset=0, limit=None, order=None, "
                                 "**read_kwargs)",
                    "parameters": {"domain": {"name": "domain"}, "fields": {"name": "fields"},
                                   "offset": {"name": "offset"}, "limit": {"name": "limit"},
                                   "order": {"name": "order"},
                                   "read_kwargs": {"name": "read_kwargs",
                                                   "kind": "VAR_KEYWORD"}},
                    "api": ["model", "readonly"], "model": "core", "module": "core"},
    "write": {"signature": "(vals)", "parameters": {"vals": {"name": "vals"}}, "api": []},
    "x_studio_action": {"signature": "(*, note)",
                        "parameters": {"note": {"name": "note", "kind": "KEYWORD_ONLY"}}},
}}


def test_catalog_reads_doc_bearer_on_19_with_an_admin_key() -> None:
    session = _catalog_session(doc=DOC)
    out = odoo_api_catalog(_ctx(session), {"model": "res.partner"})
    assert out["source"] == "doc-bearer" and out["count"] == 3 and out["truncated"] is False
    by_name = {m["name"]: m for m in out["methods"]}
    assert by_name["search_read"] == {
        "name": "search_read", "parameters": ["domain", "fields", "offset", "limit", "order"],
        "model_level": True, "readonly": True, "signature": DOC["methods"]["search_read"][
            "signature"]}
    assert by_name["write"]["model_level"] is False
    assert by_name["x_studio_action"]["parameters"] == ["note"]  # keyword-only is nameable
    assert not session.executed()  # the catalog itself proves the model exists


def test_catalog_filters_by_substring_and_caps_at_100() -> None:
    methods = {f"action_{i:03d}": {"parameters": {}, "api": []} for i in range(150)}
    methods["search"] = {"parameters": {}, "api": ["model"]}
    session = _catalog_session(doc={"methods": methods})
    out = odoo_api_catalog(_ctx(session), {"model": "res.partner"})
    assert out["count"] == 151 and len(out["methods"]) == MAX_CATALOG_METHODS
    assert out["truncated"] is True
    out = odoo_api_catalog(_ctx(session), {"model": "res.partner", "method": "SEAR"})
    assert [m["name"] for m in out["methods"]] == ["search"] and out["truncated"] is False


def test_catalog_falls_back_to_the_builtin_table_for_a_non_admin_key() -> None:
    session = _catalog_session(doc=None)
    out = odoo_api_catalog(_ctx(session), {"model": "res.partner"})
    assert out["source"] == "builtin" and "administrator" in out["note"]
    assert {"model": "res.partner", "method": "fields_get", "attributes": ["type"]} in (
        session.calls)  # the existence check any internal user may run (not ir.model)
    assert not session.executed()
    names = {m["name"] for m in out["methods"]}
    assert {"search_read", "formatted_read_group", "read_group", "has_access"} <= names
    default_get = next(m for m in out["methods"] if m["name"] == "default_get")
    assert default_get["parameters"] == ["fields"]  # 19.0 names it fields


def test_catalog_on_18_uses_the_builtin_table_without_asking_doc_bearer() -> None:
    session = _catalog_session(18, json2=False)
    out = odoo_api_catalog(_ctx(session), {"model": "sale.order"})
    assert out["source"] == "builtin" and "19.0" in out["note"]
    assert "no JSON-2" in out["note"]
    assert not any(c["method"] == "api_doc" for c in session.calls)
    names = {m["name"] for m in out["methods"]}
    assert "formatted_read_group" not in names  # saas~18.4+
    assert {"read_group", "check_access_rights", "has_access"} <= names
    # 18.0 names these default_fields / args: no unverified names below saas~18.4 (F2)
    assert all(m["parameters"] is None for m in out["methods"])
    assert "not given" in out["note"] and "positional 'args'" in out["note"]
    assert "name_get" not in names  # gone in 18.0


@pytest.mark.parametrize("series", [(10, 0), (16, 0), (17, 0), (18, 0), (18, 3)])
def test_builtin_table_gives_no_names_before_saas_18_4(series: tuple[int, int]) -> None:
    facts = EnvFacts(version=series[0], edition="community", deployment="onprem",
                     minor=series[1])
    methods = {m["name"]: m for m in builtin_methods("res.partner", series, facts)}
    assert methods and all(m["parameters"] is None for m in methods.values())
    assert methods["default_get"]["model_level"] is True
    assert methods["write"]["model_level"] is False
    assert ("name_get" in methods) is (series < (18, 0))  # name_get exists up to 17.0
    if "name_get" in methods:
        assert methods["name_get"]["model_level"] is False
    users = {m["name"]: m for m in builtin_methods("res.users", series, facts)}
    assert users["has_group"]["model_level"] is (series < (18, 0))


def test_builtin_table_names_from_saas_18_4_and_the_note_says_they_are_base_names() -> None:
    facts = EnvFacts(version=18, edition="community", deployment="saas", minor=4)
    methods = {m["name"]: m for m in builtin_methods("res.partner", (18, 4), facts)}
    assert methods["default_get"]["parameters"] == ["fields_list"]
    assert methods["write"]["parameters"] == ["vals"]
    out = odoo_api_catalog(_ctx(_catalog_session(18, 4, json2=False)), {"model": "res.partner"})
    assert out["source"] == "builtin"
    assert "base definitions" in out["note"] and "write(values)" in out["note"]
    spec = registry.get("odoo_api_catalog")
    assert "exactly what" not in spec.description
    assert "parameters null" in spec.description


def test_catalog_needs_an_api_key_for_doc_bearer() -> None:
    out = odoo_api_catalog(_ctx(_catalog_session(json2=False)), {"model": "res.partner"})
    assert out["source"] == "builtin" and "ODOO_API_KEY" in out["note"]


def test_catalog_reports_a_failing_doc_bearer_and_falls_back() -> None:
    session = _catalog_session(doc=TransportError("json2: HTTP 502"))
    out = odoo_api_catalog(_ctx(session), {"model": "res.partner"})
    assert out["source"] == "builtin" and "502" in out["note"]


def test_catalog_refuses_a_model_that_does_not_exist() -> None:
    with pytest.raises(CompatError, match="does not exist"):
        odoo_api_catalog(_ctx(_catalog_session(doc=None, exists=False)), {"model": "x.nope"})


def test_catalog_passes_other_fields_get_faults_through() -> None:
    session = _catalog_session(18, json2=False)

    def refuse(model: str, attributes: Any = None) -> Any:
        raise OdooFault("odoo.exceptions.AccessError: nope")

    session.fields_get = refuse  # type: ignore[method-assign]
    with pytest.raises(OdooFault, match="AccessError"):
        odoo_api_catalog(_ctx(session), {"model": "res.partner"})


@pytest.mark.parametrize("series, present, absent", [
    ((16, 0), {"read_group", "search_read"}, {"has_access", "formatted_read_group"}),
    ((18, 4), {"read_group", "formatted_read_group", "check_access_rights"}, set()),
    ((19, 2), {"formatted_read_group", "has_access"}, {"read_group", "check_access_rights",
                                                      "name_get"}),
])
def test_builtin_table_follows_the_series(series: tuple[int, int], present: set[str],
                                          absent: set[str]) -> None:
    facts = EnvFacts(version=series[0], edition="community", deployment="saas",
                     minor=series[1])
    names = {m["name"] for m in builtin_methods("res.partner", series, facts)}
    assert present <= names and not (absent & names)


def test_builtin_table_includes_the_methods_of_that_model() -> None:
    facts = EnvFacts(version=19, edition="community", deployment="onprem")
    users = {m["name"]: m for m in builtin_methods("res.users", (19, 0), facts)}
    assert users["context_get"]["model_level"] is True
    assert users["has_group"]["parameters"] == ["group_ext_id"]
    assert "execute_import" not in users
    wizard = {m["name"] for m in builtin_methods("base_import.import", (19, 0), facts)}
    assert "execute_import" in wizard


# --- odoo_access_check ------------------------------------------------------------

def _access_session(version: int = 18, minor: int = 0, *,
                    allowed: dict[str, bool] | None = None,
                    export: Any = True) -> FakeSession:
    session = FakeSession(version, minor=minor)
    allowed = allowed if allowed is not None else {}

    def has_access(ids: list[int], operation: str) -> bool:
        return allowed.get(operation, True)

    def check_rights(operation: str, raise_exception: bool = True) -> bool:
        assert raise_exception is False
        return allowed.get(operation, True)

    def has_group(*args: Any) -> Any:
        if isinstance(export, BaseException):
            raise export
        return export

    session.handlers.update({
        ("res.partner", "has_access"): has_access,
        ("res.partner", "check_access_rights"): check_rights,
        ("res.users", "has_group"): has_group,
    })
    return session


def test_access_check_on_18_uses_has_access_and_has_group_as_a_record_method() -> None:
    session = _access_session(allowed={"unlink": False})
    out = odoo_access_check(_ctx(session), {"model": "res.partner"})
    assert out["access"] == {"read": True, "write": True, "create": True, "unlink": False}
    assert out["method"] == "has_access" and out["level"] == "model"
    assert out["export_allowed"] is True
    calls = session.executed("has_access")
    assert [(c["args"], c["ids"]) for c in calls] == [
        (["read"], []), (["write"], []), (["create"], []), (["unlink"], [])]
    group = session.executed("has_group")[0]
    assert group["args"] == ["base.group_allow_export"] and group["ids"] == [2]
    assert any("ir.rule" in n for n in out["notes"])


def test_access_check_with_ids_on_18_is_record_level() -> None:
    session = _access_session()
    out = odoo_access_check(_ctx(session), {"model": "res.partner", "ids": [5, 6],
                                            "operations": ["write", "write", "read"]})
    assert out["level"] == "record" and out["ids"] == [5, 6]
    assert list(out["access"]) == ["write", "read"]  # deduplicated, order kept
    assert all(c["ids"] == [5, 6] for c in session.executed("has_access"))
    assert "notes" not in out


def test_access_check_on_17_uses_check_access_rights_and_model_level_has_group() -> None:
    session = _access_session(17)
    out = odoo_access_check(_ctx(session), {"model": "res.partner", "ids": [5]})
    assert out["method"] == "check_access_rights" and out["level"] == "model"
    assert all(c["kwargs"] == {"raise_exception": False}
               for c in session.executed("check_access_rights"))
    assert not session.executed("has_access")
    group = session.executed("has_group")[0]
    assert group["args"] == ["base.group_allow_export"] and group["ids"] is None
    assert any("Record-level checks need Odoo 18+" in n for n in out["notes"])


def test_access_check_before_16_has_no_export_group() -> None:
    session = _access_session(15)
    out = odoo_access_check(_ctx(session), {"model": "res.partner", "operations": ["read"]})
    assert out["export_allowed"] is None and not session.executed("has_group")
    assert any("Before Odoo 16" in n for n in out["notes"])


def test_access_check_on_saas_19_2_never_calls_the_removed_method() -> None:
    session = _access_session(19, 2)
    odoo_access_check(_ctx(session), {"model": "res.partner"})
    assert not session.executed("check_access_rights") and session.executed("has_access")


def test_access_check_reports_an_export_check_failure() -> None:
    session = _access_session(export=OdooFault("AccessError: nope"))
    out = odoo_access_check(_ctx(session), {"model": "res.partner", "operations": ["read"]})
    assert out["export_allowed"] is None
    assert any("export_allowed could not be checked" in n for n in out["notes"])


def test_access_check_resolves_historical_model_names() -> None:
    session = _access_session()
    session.handlers[("account.move", "has_access")] = lambda ids, op: True
    out = odoo_access_check(_ctx(session), {"model": "account.invoice", "operations": ["read"]})
    assert out["model"] == "account.move"


# --- odoo_record_documents -----------------------------------------------------

ATT = {
    10: {"id": 10, "name": "scan.png", "mimetype": "image/png", "file_size": 2048,
         "create_date": "2026-09-01 10:00:00", "type": "binary", "res_model": "account.move",
         "res_id": 7},
    11: {"id": 11, "name": "INV_2026_0001.pdf", "mimetype": "application/pdf",
         "file_size": 30000, "create_date": "2026-09-02 10:00:00", "type": "binary",
         "res_model": "account.move", "res_id": 7},
    12: {"id": 12, "name": "link", "mimetype": False, "file_size": 0,
         "create_date": "2026-09-03 10:00:00", "type": "url", "res_model": "account.move",
         "res_id": 7},
    20: {"id": 20, "name": "other.pdf", "mimetype": "application/pdf", "file_size": 10,
         "create_date": "2026-09-03 10:00:00", "type": "binary", "res_model": "res.partner",
         "res_id": 7},
}


def _documents_session(version: int = 18, *, flags: bool = True,
                       record: bool = True) -> FakeSession:
    fields = {"account.move": {"message_main_attachment_id": {}, "invoice_pdf_report_id": {}}
              if flags else {"name": {}}}
    session = FakeSession(version, fields=fields)

    def read_move(ids: list[list[int]], fields: list[str]) -> list[dict[str, Any]]:
        if not record:
            return []
        row = {"id": 7}
        if "message_main_attachment_id" in fields:
            row["message_main_attachment_id"] = [10, "scan.png"]
        if "invoice_pdf_report_id" in fields:
            row["invoice_pdf_report_id"] = [11, "INV_2026_0001.pdf"]
        return [row]

    def read_attachments(ids: list[int], fields: list[str]) -> list[dict[str, Any]]:
        rows = []
        for i in ids:
            if i in ATT:
                row = {k: v for k, v in ATT[i].items() if k in fields or k == "id"}
                if "datas" in fields:
                    row["datas"] = "UERGIGJ5dGVz"
                rows.append(row)
        return rows

    session.handlers.update({
        ("account.move", "read"): read_move,
        # the invoice PDF lives in a binary field (res_field): hidden from a plain search
        ("ir.attachment", "search_read"): lambda domain, fields, limit, order: [
            {k: ATT[i][k] for k in ["id", *fields]} for i in (12, 10)][:limit],
        ("ir.attachment", "read"): read_attachments,
    })
    return session


def test_documents_list_flags_the_main_attachment_and_the_hidden_invoice_pdf() -> None:
    session = _documents_session()
    out = odoo_record_documents(_ctx(session), {"model": "account.move", "res_id": 7})
    assert out["main_attachment_id"] == 10 and out["invoice_pdf_attachment_id"] == 11
    by_id = {d["id"]: d for d in out["documents"]}
    assert set(by_id) == {10, 11, 12} and out["count"] == 3
    assert by_id[10]["is_main_attachment"] and not by_id[10]["is_invoice_pdf"]
    assert by_id[11]["is_invoice_pdf"] and by_id[11]["mimetype"] == "application/pdf"
    assert "attachment" not in out
    search = session.executed("search_read")[0]
    assert search["args"] == [[["res_model", "=", "account.move"], ["res_id", "=", 7]]]
    assert search["kwargs"]["limit"] == 50
    assert not any("datas" in c["kwargs"].get("fields", []) for c in session.executed())


def test_documents_return_content_only_for_an_attachment_of_that_record() -> None:
    session = _documents_session()
    out = odoo_record_documents(_ctx(session), {"model": "account.move", "res_id": 7,
                                                "attachment_id": 11, "include_content": True})
    assert out["attachment"]["content_base64"] == "UERGIGJ5dGVz"
    assert out["attachment"]["is_invoice_pdf"] is True
    with pytest.raises(CompatError, match="does not belong"):
        odoo_record_documents(_ctx(session), {"model": "account.move", "res_id": 7,
                                              "attachment_id": 20, "include_content": True})
    with pytest.raises(CompatError, match="does not belong"):
        odoo_record_documents(_ctx(session), {"model": "account.move", "res_id": 7,
                                              "attachment_id": 999})


def test_documents_content_needs_an_attachment_id() -> None:
    session = _documents_session()
    with pytest.raises(CompatError, match="needs attachment_id"):
        odoo_record_documents(_ctx(session), {"model": "account.move", "res_id": 7,
                                              "include_content": True})
    assert not session.executed()  # refused before touching Odoo


def test_documents_skip_content_over_max_bytes_and_for_url_attachments() -> None:
    session = _documents_session()
    out = odoo_record_documents(_ctx(session), {"model": "account.move", "res_id": 7,
                                                "attachment_id": 11, "include_content": True,
                                                "max_bytes": 1000})
    assert "content_base64" not in out["attachment"]
    assert "30000 bytes" in out["attachment"]["content_skipped"]
    out = odoo_record_documents(_ctx(session), {"model": "account.move", "res_id": 7,
                                                "attachment_id": 12, "include_content": True})
    assert "URL" in out["attachment"]["content_skipped"]
    datas_reads = [c for c in session.executed("read")
                   if "datas" in c["kwargs"].get("fields", [])]
    assert datas_reads == []


def test_documents_cap_max_bytes_and_limit() -> None:
    session = _documents_session()
    out = odoo_record_documents(_ctx(session), {"model": "account.move", "res_id": 7,
                                                "max_bytes": 50 * 1024 * 1024, "limit": 2})
    assert "max_bytes was limited to 5242880" in out["notes"]
    assert any("limit=2" in n for n in out["notes"])
    odoo_record_documents(_ctx(session), {"model": "account.move", "res_id": 7,
                                          "limit": 10_000})
    assert session.executed("search_read")[-1]["kwargs"]["limit"] == 500


def test_documents_without_flag_fields_skip_the_record_read() -> None:
    session = _documents_session(flags=False)
    out = odoo_record_documents(_ctx(session), {"model": "account.move", "res_id": 7})
    assert out["main_attachment_id"] is None and out["invoice_pdf_attachment_id"] is None
    assert not [c for c in session.executed("read") if c["model"] == "account.move"]
    assert {d["id"] for d in out["documents"]} == {10, 12}


def test_documents_of_a_missing_record() -> None:
    with pytest.raises(CompatError, match="does not exist"):
        odoo_record_documents(_ctx(_documents_session(record=False)),
                              {"model": "account.move", "res_id": 7})


# --- odoo_import_preview / odoo_import ---------------------------------------------

FIELDS = ["name", "email", "country_id"]
ROWS = [["José, S.A. de C.V.", "jose@example.com", "Mexico"],
        ["Ana \"la jefa\"\nLópez", "", "Spain"]]


def _import_session(version: int = 18, *, active: str = "jsonrpc(auto)",
                    result: Any = None, modules: set[str] | None = None) -> FakeSession:
    session = FakeSession(version, transport=FakeTransport(active=active),
                          modules=modules)
    session.handlers.update({
        ("base_import.import", "create"): lambda vals: 42,
        ("base_import.import", "execute_import"): lambda ids, fields, columns, options,
        dryrun=False: result if result is not None else {
            "ids": [101, 102], "messages": [], "nextrow": 0, "name": ["a", "b"]},
        ("base_import.import", "unlink"): lambda ids: True,
        ("res.partner", "load"): lambda fields, rows: result if result is not None else {
            "ids": [201, 202], "messages": [], "nextrow": 0},
    })
    return session


def test_preview_runs_a_dry_run_through_base_import_and_cleans_up() -> None:
    session = _import_session()
    out = odoo_import_preview(_ctx(session), {"model": "res.partner", "fields": FIELDS,
                                              "rows": ROWS})
    assert out["would_import"] == 2 and out["ok"] is True and out["dry_run"] is True
    assert "ids" not in out and "101" not in json.dumps(out)  # never the rolled-back ids
    # the result itself warns that a rolled-back run is not free of side effects
    assert "Nothing was saved" in out["note"]
    assert "sequence numbers" in out["note"] and "webhooks" in out["note"]
    create, execute, unlink = session.executed()
    vals = create["args"][0]
    assert (vals["res_model"], vals["file_type"]) == ("res.partner", "text/csv")
    assert list(csv.reader(io.StringIO(vals["file"]))) == ROWS  # no header row, UTF-8 text
    # raw CSV text, never base64: base_import.import.file holds the file's bytes on 16-19
    assert vals["file"].startswith('"José, S.A. de C.V.",jose@example.com,Mexico\n"Ana ')
    assert execute["args"] == [[42], FIELDS, FIELDS, IMPORT_OPTIONS]
    assert execute["kwargs"] == {"dryrun": True}
    assert execute["args"][3]["has_headers"] is False  # so Odoo stores no column mapping
    assert unlink["args"] == [[42]]
    assert all(c["transports"] == IMPORT_TRANSPORTS for c in (create, execute, unlink))


def test_preview_counts_and_truncates_messages() -> None:
    messages = [{"type": "error", "message": f"bad {i}", "rows": {"from": i, "to": i},
                 "field": "email", "moreinfo": None} for i in range(120)]
    messages.append({"type": "warning", "message": "w", "rows": {"from": 0, "to": 0}})
    session = _import_session(result={"ids": False, "messages": messages})
    out = odoo_import_preview(_ctx(session), {"model": "res.partner", "fields": FIELDS,
                                              "rows": ROWS})
    assert out["ok"] is False and out["would_import"] == 0
    assert (out["errors"], out["warnings"]) == (120, 1)
    assert len(out["messages"]) == MAX_MESSAGES and out["messages_truncated"] == 21


def test_import_messages_keep_the_row_facts_and_drop_ui_actions() -> None:
    action = {"name": "Possible Values", "type": "ir.actions.act_window",
              "res_model": "res.country", "views": [[False, "list"]]}
    session = _import_session(result={"ids": False, "messages": [
        {"rows": {"from": 1, "to": 1}, "type": "error", "record": 1, "field": "country_id",
         "message": "No matching record found for name 'Atlantis' in field 'Country'",
         "moreinfo": action, "value": "Atlantis", "field_type": "name",
         "field_path": ["country_id"], "field_name": "Country"},
        {"type": "warning", "message": "w", "moreinfo": "see the docs"},
    ]})
    out = odoo_import(_ctx(session), {"model": "res.partner", "fields": FIELDS, "rows": ROWS})
    assert out["messages"] == [
        {"type": "error", "message": "No matching record found for name 'Atlantis' in field "
         "'Country'", "rows": {"from": 1, "to": 1}, "record": 1, "field": "country_id",
         "field_name": "Country", "value": "Atlantis"},
        {"type": "warning", "message": "w", "moreinfo": "see the docs"},
    ]


def test_preview_passes_a_validation_error_through() -> None:
    session = _import_session(result={"messages": [{"type": "error", "message": "no field"}]})
    out = odoo_import_preview(_ctx(session), {"model": "res.partner", "fields": FIELDS,
                                              "rows": ROWS})
    assert out["would_import"] == 0 and out["errors"] == 1 and out["ok"] is False


def test_preview_cleans_up_when_the_dry_run_fails_and_ignores_a_failed_cleanup() -> None:
    session = _import_session()

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise OdooFault("ValueError: boom")

    session.handlers[("base_import.import", "execute_import")] = fail
    with pytest.raises(OdooFault, match="boom"):
        odoo_import_preview(_ctx(session), {"model": "res.partner", "fields": FIELDS,
                                            "rows": ROWS})
    assert session.executed("unlink")
    session = _import_session()
    session.handlers[("base_import.import", "unlink")] = fail
    out = odoo_import_preview(_ctx(session), {"model": "res.partner", "fields": FIELDS,
                                              "rows": ROWS})
    assert out["would_import"] == 2


def test_preview_needs_odoo_16_and_base_import() -> None:
    session = _import_session(15)
    with pytest.raises(CompatError, match="Odoo 16"):
        odoo_import_preview(_ctx(session), {"model": "res.partner", "fields": FIELDS,
                                            "rows": ROWS})
    session = _import_session(modules=set())
    with pytest.raises(CompatError, match="base_import"):
        odoo_import_preview(_ctx(session), {"model": "res.partner", "fields": FIELDS,
                                            "rows": ROWS})
    assert not session.executed()


@pytest.mark.parametrize("tool", [odoo_import_preview, odoo_import])
@pytest.mark.parametrize("active", ["xmlrpc", "xmlrpc(auto)"])
def test_imports_refuse_an_xmlrpc_session_before_writing(tool: Any, active: str) -> None:
    session = _import_session(active=active)
    with pytest.raises(CompatError, match="needs JSON-RPC or JSON-2"):
        tool(_ctx(session), {"model": "res.partner", "fields": FIELDS, "rows": ROWS})
    assert not session.executed()


@pytest.mark.parametrize("tool", [odoo_import_preview, odoo_import])
@pytest.mark.parametrize("rows, match", [
    ([["only one"]], "row 0 has 1 value"),
    ([["a", "b", "c"], ["", "  ", ""]], "row 1 is empty"),
])
def test_imports_check_the_rows_before_touching_odoo(tool: Any, rows: list[list[str]],
                                                     match: str) -> None:
    session = _import_session()
    with pytest.raises(CompatError, match=match):
        tool(_ctx(session), {"model": "res.partner", "fields": FIELDS, "rows": rows})
    assert not session.executed()


def test_import_loads_the_rows_atomically() -> None:
    session = _import_session()
    out = odoo_import(_ctx(session), {"model": "res.partner", "fields": FIELDS, "rows": ROWS})
    assert out["ok"] is True and out["ids"] == [201, 202] and out["count"] == 2
    (load,) = session.executed()
    assert load["method"] == "load" and load["args"] == [FIELDS, ROWS]
    assert load["transports"] == IMPORT_TRANSPORTS


def test_import_reports_that_nothing_was_saved() -> None:
    session = _import_session(result={"ids": False, "messages": [
        {"type": "error", "message": "Invalid email", "rows": {"from": 1, "to": 1}}]})
    out = odoo_import(_ctx(session), {"model": "res.partner", "fields": FIELDS, "rows": ROWS})
    assert out["ok"] is False and out["ids"] == [] and out["count"] == 0
    assert out["errors"] == 1 and "Nothing was saved" in out["note"]


def test_import_with_warnings_is_saved() -> None:
    session = _import_session(result={"ids": [5], "messages": [
        {"type": "warning", "message": "Found multiple matches", "rows": {"from": 0, "to": 0}}]})
    out = odoo_import(_ctx(session), {"model": "res.partner", "fields": FIELDS,
                                      "rows": ROWS[:1]})
    assert out["ok"] is True and out["warnings"] == 1 and out["ids"] == [5]


def test_import_description_warns_about_the_external_id_upsert() -> None:
    assert "UPDATES" in registry.get("odoo_import").description
    assert "never imports" in registry.get("odoo_import_preview").description


# --- the transport restriction ------------------------------------------------------

class _Stub:
    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes) or [2]
        self.calls: list[tuple[Any, ...]] = []

    def _next(self, *args: Any) -> Any:
        self.calls.append(args)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def version(self) -> Any:
        return self._next("version")

    def authenticate(self, *args: Any) -> Any:
        return self._next("authenticate", *args)

    def execute_kw(self, *args: Any, **kwargs: Any) -> Any:
        return self._next("execute_kw", *args)


def _fallback(pref: str = "auto", kind: str = "password",
              series: str = "18.0") -> tuple[FallbackTransport, _Stub, _Stub, _Stub]:
    fb = FallbackTransport("https://odoo.example", timeout=5, pref=pref, secret_kind=kind,
                           sleep=lambda _s: None)
    j2, js, xs = _Stub(2), _Stub(2), _Stub(2)
    fb._j2, fb._json, fb._xml = j2, js, xs  # type: ignore[assignment]
    fb._remember_version({"server_version": series})
    return fb, j2, js, xs


def test_a_restricted_call_is_never_replayed_over_xmlrpc() -> None:
    fb, _j2, js, xs = _fallback()
    assert fb.authenticate("db", "admin", "pw") == 2  # legacy order frozen: jsonrpc, xmlrpc
    js.outcomes = [JsonRpcUnavailable("jsonrpc: HTTP 404")]
    with pytest.raises(JsonRpcUnavailable):
        fb.execute_kw("db", 2, "pw", "res.partner", "load", [["name"], [["a"]]],
                      transports=IMPORT_TRANSPORTS)
    assert xs.calls == [] and fb.active == "jsonrpc(auto)"  # not pinned to XML-RPC
    # an unrestricted write still falls back when the request never reached Odoo
    fb.execute_kw("db", 2, "pw", "res.partner", "create", [{}])
    assert len(xs.calls) == 1 and fb.active == "xmlrpc"


def test_a_restricted_call_on_an_xmlrpc_session_is_refused_without_a_request() -> None:
    fb, _j2, js, xs = _fallback(pref="xmlrpc")
    with pytest.raises(CompatError, match="res.partner.load needs JSON-2 or JSON-RPC"):
        fb.execute_kw("db", 2, "pw", "res.partner", "load", [[], []],
                      transports=IMPORT_TRANSPORTS)
    assert xs.calls == [] and js.calls == []


def test_a_restricted_call_runs_on_json2_when_it_is_pinned() -> None:
    fb, j2, js, xs = _fallback(kind="api_key", series="19.0")
    fb.authenticate("db", "admin", KEY)
    fb.execute_kw("db", 2, KEY, "res.partner", "load", [["name"], [["a"]]],
                  transports=IMPORT_TRANSPORTS)
    assert len(j2.calls) == 2 and js.calls == [] and xs.calls == []


def test_session_execute_passes_transports_only_when_given() -> None:
    seen: list[dict[str, Any]] = []

    class Transport:
        def authenticate(self, *args: Any) -> int:
            return 2

        def execute_kw(self, *args: Any, **kwargs: Any) -> Any:
            seen.append(kwargs)
            return True

    session = OdooSession(Credentials(url="https://odoo.example", db="db", login="admin",
                                      secret=KEY))
    session.transport = Transport()  # type: ignore[assignment]
    session.execute("res.partner", "search", [[]])
    session.execute("res.partner", "load", [[], []], transports=IMPORT_TRANSPORTS)
    session.execute("res.users", "has_group", ["g"], ids=[2])
    assert seen == [{}, {"transports": IMPORT_TRANSPORTS}, {"ids": [2]}]


def test_session_api_doc_keeps_the_secret_inside_the_session() -> None:
    session = OdooSession(Credentials(url="https://odoo.example", db="db", login="admin",
                                      secret=KEY, secret_kind="api_key"))
    seen: list[tuple[Any, ...]] = []
    session.transport.api_doc = lambda *a: seen.append(a) or {"methods": {}}  # type: ignore
    assert session.api_doc("res.partner") == {"methods": {}}
    assert seen == [("db", KEY, "res.partner")]


# --- end to end over a scripted Odoo (JSON-2 and JSON-RPC bodies) --------------------

@pytest.fixture
def fake() -> Iterator[FakeOdoo]:
    server = FakeOdoo()
    yield server
    server.close()


def _json2_session(fake: FakeOdoo, orm: Callable[[str, str, dict[str, Any]], Any]) -> Any:
    fake.serve_version()
    fake.serve_json2(orm)
    return OdooSession(Credentials(url=fake.url, db="db", login="admin", secret=KEY,
                                   secret_kind="api_key"), timeout=5, transport_pref="auto")


def _bodies(fake: FakeOdoo) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for request in fake.calls("/json/2/"):
        out.setdefault(request["path"][len("/json/2/"):], []).append(request["body"])
    return out


def test_json2_bodies_for_the_import_preview_and_the_import(fake: FakeOdoo) -> None:
    def orm(model: str, method: str, body: dict[str, Any]) -> Any:
        if method == "search_count":  # module probes: base_import yes, web_enterprise no
            return 1 if body["domain"][0][2] == "base_import" else 0
        if (model, method) == ("base_import.import", "create"):
            return [42]
        if method == "execute_import":
            return {"ids": [1], "messages": [], "nextrow": 0, "name": ["a"]}
        if method == "load":
            return {"ids": [9], "messages": [], "nextrow": 0}
        return True

    session = _json2_session(fake, orm)
    ctx = ToolContext(session=session, manager=None)
    out = odoo_import_preview(ctx, {"model": "res.partner", "fields": ["name"],
                                    "rows": [["Ñandú"]]})
    assert out["would_import"] == 1
    out = odoo_import(ctx, {"model": "res.partner", "fields": ["name", "id"],
                            "rows": [["Ñandú", "__import__.nandu"]]})
    assert out["ids"] == [9]
    bodies = _bodies(fake)
    (create,) = bodies["base_import.import/create"]
    assert create["vals_list"]["file"] == "Ñandú\n"
    assert bodies["base_import.import/execute_import"] == [{
        "ids": [42], "fields": ["name"], "columns": ["name"], "options": IMPORT_OPTIONS,
        "dryrun": True}]
    assert bodies["base_import.import/unlink"] == [{"ids": [42]}]
    assert bodies["res.partner/load"] == [{"fields": ["name", "id"],
                                           "data": [["Ñandú", "__import__.nandu"]]}]
    assert not fake.calls("/jsonrpc") and not fake.calls("/xmlrpc")


def test_json2_bodies_for_the_access_check(fake: FakeOdoo) -> None:
    def orm(model: str, method: str, body: dict[str, Any]) -> Any:
        return 0 if method == "search_count" else True

    session = _json2_session(fake, orm)
    out = odoo_access_check(ToolContext(session=session, manager=None),
                            {"model": "res.partner", "operations": ["read"], "ids": [3]})
    assert out["access"] == {"read": True} and out["export_allowed"] is True
    bodies = _bodies(fake)
    assert bodies["res.partner/has_access"] == [{"ids": [3], "operation": "read"}]
    assert bodies["res.users/has_group"] == [{"ids": [2],
                                              "group_ext_id": "base.group_allow_export"}]


def test_json2_profile_and_catalog_end_to_end(fake: FakeOdoo) -> None:
    def orm(model: str, method: str, body: dict[str, Any]) -> Any:
        if method == "search_count":
            return 0
        if method == "fields_get":
            return {"login": {"type": "char"}, "name": {"type": "char"},
                    "expiration_date": {"type": "datetime"}}
        if (model, method) == ("res.users", "read"):
            return [{"id": 2, "login": "admin", "name": "Admin"}]
        if method == "search_read":
            return []
        return {}

    fake.on("GET", "/doc-bearer/res.partner.json",
            json_reply(200, {"model": "res.partner", "methods": {
                "copy": {"parameters": {"default": {"name": "default"}}, "api": []}}},
                ETag='"v1"'))
    session = _json2_session(fake, orm)
    ctx = ToolContext(session=session, manager=None)
    profile = odoo_online_profile(ctx, {})
    assert profile["transport"] == "json2" and profile["doc_bearer"] is True
    assert profile["user"]["login"] == "admin" and profile["api_keys"] == []
    catalog = odoo_api_catalog(ctx, {"model": "res.partner"})
    assert catalog["source"] == "doc-bearer"
    assert catalog["methods"] == [{"name": "copy", "parameters": ["default"],
                                   "model_level": False, "readonly": False}]
    assert _bodies(fake)["res.users.apikeys/search_read"] == [
        {"domain": [["user_id", "=", 2]], "fields": ["name", "expiration_date"]}]
    assert not fake.calls("/jsonrpc") and not fake.calls("/xmlrpc")
    assert KEY not in json.dumps(profile) + json.dumps(catalog)


def test_jsonrpc_import_on_18_with_a_password(fake: FakeOdoo) -> None:
    def orm(model: str, method: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
        if method == "search_count":
            return 0
        assert (model, method) == ("res.partner", "load")
        return {"ids": [11], "messages": [], "nextrow": 0}

    fake.serve_jsonrpc(orm, version=version_payload("18.0", [18, 0, 0, "final", 0, ""]))
    session = OdooSession(Credentials(url=fake.url, db="db", login="admin", secret="pw"),
                          timeout=5)
    out = odoo_import(ToolContext(session=session, manager=None),
                      {"model": "res.partner", "fields": ["name"], "rows": [["a"]]})
    assert out["ids"] == [11]
    load = [r["body"]["params"]["args"] for r in fake.calls("/jsonrpc")
            if r["body"]["params"]["method"] == "execute_kw"
            and r["body"]["params"]["args"][4] == "load"]
    assert load[0][5] == [["name"], [["a"]]]
    assert not fake.calls("/xmlrpc")
