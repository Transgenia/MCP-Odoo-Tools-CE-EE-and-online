# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The permission-policy checks of ``scripts/sandbox_smoke.py`` (design 9.7), without Odoo.

The sandbox matrix runs them against Odoo 10 to 19. Here they run against the
real MCP server and its guarded session over a scripted Odoo session
(``policy_fakes``), so the rules the smoke test expects are the rules the
policy applies, and a policy that let a call through would be reported.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

import pytest
from policy_fakes import CHAR, FIELDS, ScriptedSession, m2m, m2o, o2m, server

from odoo_mcp.audit import AuditLog
from odoo_mcp.policy import texts
from odoo_mcp.policy.model import Policy
from odoo_mcp.policy.tiers import DELEGATES

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def smoke() -> Any:
    spec = importlib.util.spec_from_file_location(
        "sandbox_smoke", ROOT / "scripts" / "sandbox_smoke.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["sandbox_smoke"] = module
    spec.loader.exec_module(module)
    return module


def runner(smoke: Any, srv: Any) -> Any:
    """A ``Run`` over an in-process server: what ``Client`` does over stdio."""
    def run(name: str, arguments: dict) -> Any:
        return smoke.outcome(srv.call_tool({"name": name, "arguments": arguments}))
    return run


# --- the instance the scripted session stands for -----------------------------------

INSTALLED = {"res.partner", "res.users", "res.company", "ir.attachment", "ir.model",
             "ir.config_parameter", "ir.cron", "ir.actions.server", "ir.ui.view",
             "mail.mail", "mail.message", "website.page", "payment.provider"}


def ir_model_rows(args: Any, kwargs: Any, ids: Any) -> list[dict[str, Any]]:
    """``ir.model`` search_read: ``model in [...]`` or ``model =like 'x.%'``."""
    (_field, operator, value), = args[0]
    if operator == "in":
        names = [name for name in INSTALLED if name in value]
    else:
        names = [name for name in INSTALLED if name.startswith(value[:-1])]
    return [{"id": n, "model": name} for n, name in enumerate(sorted(names), 1)]


def session(**extra: Any) -> ScriptedSession:
    fields = {"res.users": {**FIELDS["res.users"], "password": CHAR},
              "ir.cron": {"name": CHAR, "code": {"type": "text"},
                          "ir_actions_server_id": m2o("ir.actions.server")},
              **extra.pop("fields", {})}
    results = {("res.users", "search_read"): [
        {"id": 4, "partner_id": [7, "Bot user"], "company_id": [1, "Acme"]}],
        ("ir.model", "search_read"): ir_model_rows, **extra.pop("results", {})}
    rows = {"res.users": {4: {"id": 4, "login": "bot@example.com", "password": ""}},
            **extra.pop("rows", {})}
    return ScriptedSession(fields=fields, results=results, rows=rows, **extra)


EXPECTED_REFUSALS = [
    ("odoo_write", "relational"),  # res.company user_ids
    ("odoo_write", "relational"),  # res.partner user_ids
    ("odoo_write", "identity"),
    ("odoo_read", "field"),
    ("odoo_search_read", "field"),
    ("odoo_search_count", "field"),
    ("odoo_search_read", "tier:secrets"),
    ("odoo_search_read", "attachment-pin"),
    ("odoo_search_read", "attachment-pin"),
    ("odoo_execute", "context"),  # a trailing positional context with a list default
]


# --- the refusal texts ------------------------------------------------------------------

def test_the_rule_is_read_from_every_kind_of_refusal(smoke: Any) -> None:
    policy = Policy()
    cases = {
        "tier:security": texts.refused(policy, policy.decide("write", "res.users")),
        "relational": texts.relational(policy, method="write", model="res.company",
                                       op="write", comodel="res.users", field="user_ids",
                                       command=4, rule="tier:security"),
        "field": texts.field(policy, "read", "res.users", "password"),
        "attachment-pin": texts.attachment_pin(policy),
        "identity": texts.identity(policy, 7),
        "tier:customization": texts.refused(policy, policy.decide("write", "base.action.rule")),
    }
    for rule, exc in cases.items():
        assert smoke.Outcome(False, str(exc)).rule == rule, str(exc)
    assert smoke.Outcome(False, "Odoo said no").rule is None
    assert smoke.outcome({"content": [{"type": "text", "text": '{"a": 1}'}],
                          "isError": False}).data == {"a": 1}


# --- standard: the refusals ---------------------------------------------------------

def test_the_standard_refusals_hold_on_the_real_policy(smoke: Any) -> None:
    raw = session()
    checks = smoke.check_standard(runner(smoke, server(raw)), "bot@example.com")
    assert checks.problems == []
    assert checks.skipped == []
    assert sorted(checks.refusals) == sorted(EXPECTED_REFUSALS)
    assert any("withheld from a read without a field list" in c for c in checks.checked)
    assert "ir.attachment search pinned to res.partner: allowed" in checks.checked
    assert "certificate.key does not exist on this series" in checks.notes
    # every refusal stopped before Odoo: nothing was written, no attachment searched
    assert raw.sent("write") == []
    assert ("ir.attachment", "search_read") in raw.sent()  # the allowed one only
    assert len([c for c in raw.sent() if c == ("ir.attachment", "search_read")]) == 1
    # the read with a positional context never reached Odoo (the other res.partner
    # search_read, the signup_token field list, is refused before Odoo too)
    assert ("res.partner", "search_read") not in raw.sent()
    assert any(c.startswith("odoo_execute with a trailing positional context holding a list "
                            "default: refused (rule context)") for c in checks.checked)


@pytest.mark.parametrize("version", [10, 12, 13, 19])
def test_the_positional_context_check_holds_on_every_series(smoke: Any, version: int) -> None:
    # Layer A refuses it before the series matters; the guard is never reached.
    raw = session(version=version)
    checks = smoke.check_standard(runner(smoke, server(raw)), "bot@example.com")
    assert [p for p in checks.problems if p.startswith("odoo_execute")] == []
    assert ("odoo_execute", "context") in checks.refusals
    assert ("res.partner", "search_read") not in raw.sent()


def test_a_policy_that_lets_the_calls_through_is_reported(smoke: Any) -> None:
    checks = smoke.check_standard(runner(smoke, server(session(), policy_profile="full")),
                                  "bot@example.com")
    allowed = [p for p in checks.problems if "was allowed" in p]
    assert len(allowed) >= 6, checks.problems
    assert any(p.startswith("res.company write linking user_ids") for p in allowed)
    assert any(p.startswith("a user's contact e-mail") for p in allowed)


def test_a_field_or_model_the_series_lacks_is_skipped_with_its_reason(smoke: Any) -> None:
    partner = {k: v for k, v in FIELDS["res.partner"].items()
               if k not in ("signup_token", "user_ids")}
    raw = session(fields={"res.partner": partner, "res.users": FIELDS["res.users"]})
    checks = smoke.check_standard(runner(smoke, server(raw)), "bot@example.com")
    assert checks.problems == []
    assert any("res.partner.user_ids is not a one2many" in s for s in checks.skipped)
    assert any(s.startswith("res.partner.signup_token (not on this series") for s in
               checks.skipped)
    assert any(s.startswith("res.users.password (no user, or no password field")
               for s in checks.skipped)


# --- odoo_version and the offline check ----------------------------------------------

@pytest.mark.parametrize("profile", ["standard", "builder"])
def test_the_policy_block_matches_the_offline_check(smoke: Any, profile: str) -> None:
    offline = smoke.offline_policy(profile)
    run = runner(smoke, server(session(), policy_profile=profile))
    version = run("odoo_version", {}).data
    checks = smoke.check_policy_block(version, profile, offline)
    assert checks.problems == []
    assert f"policy.profile = '{profile}'" in checks.checked
    expected_hidden = [] if profile == "builder" else ["odoo_unlink", "odoo_add_field",
                                                       "odoo_add_automation"]
    assert offline["hidden_tools"] == expected_hidden
    other = smoke.check_policy_block({"policy": {**version["policy"], "digest": "0" * 12}},
                                     profile, offline)
    assert [p for p in other.problems if p.startswith("policy.digest is '000000000000'")]


def test_builder_without_w6_and_a_missing_block_are_problems(smoke: Any) -> None:
    offline = {"digest": "a" * 12, "hidden_tools": []}
    block = {"profile": "builder", "error": None, "readonly": False, "digest": "a" * 12,
             "hidden_tools": [], "warnings": []}
    assert smoke.check_policy_block({"policy": block}, "builder", offline).problems == [
        "profile builder loaded without warning W6"]
    assert smoke.check_policy_block({}, "standard", offline).problems == [
        "odoo_version returned no policy block"]


# --- delegation --------------------------------------------------------------------

def test_every_delegates_row_has_its_documented_series(smoke: Any) -> None:
    assert set(smoke.DELEGATE_SERIES) == set(DELEGATES)
    assert {parent for parent, _link in DELEGATES.values()} <= set(smoke.PARENT_FIELDS)


def test_the_delegates_rows_on_a_series(smoke: Any) -> None:
    raw = session(fields={"website.page": {"name": CHAR, "arch": {"type": "text"},
                                           "view_id": m2o("ir.ui.view")}})
    checks = smoke.check_delegates(runner(smoke, server(raw)), 17)
    assert checks.problems == []
    assert checks.checked == [
        ("ir.cron.ir_actions_server_id -> many2one ir.actions.server (ir.actions.server.code "
         "shown on ir.cron)"),
        "website.page.view_id -> many2one ir.ui.view (ir.ui.view.arch shown on website.page)"]
    assert "product.document.ir_attachment_id (model not installed)" in checks.skipped


def test_a_delegates_row_the_live_model_contradicts(smoke: Any) -> None:
    cron = {"name": CHAR, "model": CHAR, "function": CHAR}  # Odoo 10: no server action
    page = {"name": CHAR, "view_id": m2m("ir.ui.view")}
    raw = session(fields={"ir.cron": cron, "website.page": page})
    run = runner(smoke, server(raw))
    on_10 = smoke.check_delegates(run, 10)
    assert "ir.cron.ir_actions_server_id (no delegation on this series; documented for Odoo " \
           "11+)" in on_10.skipped
    on_12 = smoke.check_delegates(run, 12)
    assert ("ir.cron.ir_actions_server_id is missing, but the table says ir.cron delegates "
            "to ir.actions.server on Odoo 11+") in on_12.problems
    assert ("website.page.view_id is a many2many to ir.ui.view, the table says a many2one to "
            "ir.ui.view") in on_12.problems
    no_arch = session(fields={"website.page": {"view_id": m2o("ir.ui.view")}})
    assert smoke.check_delegates(runner(smoke, server(no_arch)), 17).problems == [
        ("website.page does not show ir.ui.view.arch, so it does not delegate to ir.ui.view "
         "through view_id")]


# --- the tier table ---------------------------------------------------------------------

def test_the_tier_table_lists_what_exists_without_asserting(smoke: Any) -> None:
    rows, problems = smoke.tier_models(runner(smoke, server(session())))
    assert problems == []
    by_key = {(row["group"], row["pattern"]): row for row in rows}
    assert by_key[("secrets", "ir.config_parameter")]["found"] == ["ir.config_parameter"]
    assert by_key[("secrets", "certificate.key")] == {
        "group": "secrets", "pattern": "certificate.key", "best_effort": True, "found": []}
    # ir.attachment is the customization tier's exception
    assert "ir.attachment" not in by_key[("customization", "ir.*")]["found"]
    assert "ir.cron" in by_key[("customization", "ir.*")]["found"]
    assert by_key[("delegates", "website.page")]["found"] == ["website.page"]
    assert ("never", "base.module.uninstall") in by_key
    table = smoke.format_table(rows, 17, shown=2)
    lines = table.splitlines()
    assert lines[0].startswith("Tier model names on Odoo 17")
    assert lines[1].split() == ["tier", "pattern", "best-effort", "on", "Odoo", "17"]
    assert any(line.split()[:3] == ["secrets", "certificate.key", "yes"]
               and line.endswith(" -") for line in lines)
    assert any(line.split()[:2] == ["customization", "ir.*"] and ", ..." in line
               for line in lines)


# --- builder: the Studio-style tools ----------------------------------------------------

AUTOMATION_FIELDS = {
    10: ("base.action.rule", {"name": CHAR, "model_id": m2o("ir.model"),
                              "kind": {"type": "selection"}, "filter_domain": CHAR,
                              "server_action_ids": m2m("ir.actions.server")}),
    16: ("base.automation", {"name": CHAR, "model_id": m2o("ir.model"),
                             "trigger": {"type": "selection"}, "filter_domain": CHAR,
                             "state": {"type": "selection"}, "code": {"type": "text"},
                             "action_server_id": m2o("ir.actions.server")}),
    17: ("base.automation", {"name": CHAR, "model_id": m2o("ir.model"),
                             "trigger": {"type": "selection"}, "filter_domain": CHAR,
                             "action_server_ids": o2m("ir.actions.server",
                                                      "base_automation_id")}),
}


@pytest.mark.parametrize("version", sorted(AUTOMATION_FIELDS))
def test_the_builder_checks_on_the_real_tools(smoke: Any, version: int) -> None:
    model, automation_fields = AUTOMATION_FIELDS[version]
    partner = dict(FIELDS["res.partner"])

    def create_field(args: Any, kwargs: Any, ids: Any) -> int:
        values = args[0]
        partner[values["name"]] = {"type": values["ttype"]}
        return 301

    link = next(name for name in smoke.LINK_FIELDS if name in automation_fields)
    raw = session(version=version, fields={"res.partner": partner, model: automation_fields},
                  results={("ir.model", "search"): [55],
                           ("ir.model.fields", "create"): create_field},
                  rows={model: {101: {"id": 101, "name": "odoo-tools smoke test",
                                      link: [101]}}})
    run = runner(smoke, server(raw, policy_profile="builder"))
    checks = smoke.check_builder(run, version, "x_smoke_abc123", True)
    assert checks.problems == []
    assert checks.checked[0] == "odoo_add_field: res.partner.x_smoke_abc123 (char) created"
    if version == 16:
        assert checks.checked[1] == f"odoo_add_automation: {model} 101 created " \
                                    "(inline-server-action)"
    else:
        assert checks.checked[1] == (f"odoo_add_automation: {model} 101 linked to server "
                                     f"action 101 through {link}")
    assert all(note.endswith(": done") for note in checks.notes), checks.notes
    assert ("ir.model.fields", "unlink") in raw.sent() and (model, "unlink") in raw.sent()


def test_the_automation_is_skipped_with_its_reason(smoke: Any) -> None:
    raw = session(results={("ir.module.module", "search_read"): []})
    run = runner(smoke, server(raw, policy_profile="builder"))
    reason = smoke.automation_state(run, 17)
    assert reason == "base_automation is not available on this series"
    checks = smoke.check_builder(run, 17, "x_smoke_abc123", reason)
    assert ("odoo_add_automation on base.automation (base_automation is not available on "
            "this series)") in checks.skipped
    installed = session(results={("ir.module.module", "search_read"): [
        {"name": "base_action_rule", "state": "installed"}]})
    assert smoke.automation_state(runner(smoke, server(installed)), 10) is True


# --- the audit trail ----------------------------------------------------------------------

def test_the_audit_of_a_session_verifies_and_holds_its_refusals(smoke: Any,
                                                                tmp_path: Path) -> None:
    log = AuditLog("file", str(tmp_path))
    srv = server(session(), audit=log, db="sandbox", login="admin")
    log.start(srv.settings, srv.policy)
    checks = smoke.check_standard(runner(smoke, srv), "bot@example.com")
    audit = smoke.check_audit(tmp_path, starts=1, refusals=checks.refusals,
                              secret="the-admin-password")
    assert audit.problems == []
    assert audit.checked[1] == "1 start lines, one per server start"
    # a refusal the audit does not hold, a second start, a leaked secret
    wrong = smoke.check_audit(tmp_path, starts=2, refusals=[("odoo_unlink", "profile:x")],
                              secret="admin")
    assert wrong.problems[1:] == [
        "the audit holds 1 start lines, expected 2",
        "the audit has no refused odoo_unlink call with rule profile:x"]
    assert wrong.problems[0].endswith("holds the sandbox admin password")
    # an edited line breaks the chain
    path = next(tmp_path.glob(smoke.AUDIT_FILES))
    lines = path.read_bytes().splitlines(keepends=True)
    denied = next(n for n, line in enumerate(lines) if b'"decision":"deny"' in line)
    lines[denied] = lines[denied].replace(b'"decision":"deny"', b'"decision":"allow"')
    path.write_bytes(b"".join(lines))
    edited = smoke.check_audit(tmp_path, starts=1, refusals=[], secret="")
    assert edited.problems and edited.problems[0].startswith(f"--verify-audit {path.name}: ")
    assert smoke.check_audit(tmp_path / "empty", starts=1, refusals=[], secret="").problems \
        == [f"no audit file was written in {tmp_path / 'empty'}"]


# --- the fixture that installs the automated actions module -------------------------

def test_the_matrix_runs_the_policy_checks_with_the_automation_module() -> None:
    matrix = (ROOT / ".github/workflows/sandbox-matrix.yml").read_text()
    assert "scripts/sandbox_smoke.py" in matrix and "--install-automation" in matrix

class _Odoo:
    """Just enough of Odoo's XML-RPC to install a module."""

    def __init__(self, modules: dict[str, str]) -> None:
        self.modules = modules
        self.installed: list[int] = []

    def authenticate(self, db: str, login: str, password: str, context: dict) -> Any:
        return 2 if password == "pw" else False

    def execute_kw(self, db: str, uid: int, password: str, model: str, method: str,
                   args: list, kwargs: dict | None = None) -> Any:
        names = sorted(self.modules)
        if method == "search_read":
            name = args[0][0][2]
            return [{"id": names.index(name) + 1, "state": self.modules[name]}] \
                if name in self.modules else []
        self.installed.extend(args[0])
        return {"type": "ir.actions.client", "tag": "reload"}


@pytest.fixture
def odoo_rpc() -> Iterator[tuple[str, _Odoo]]:
    class Handler(SimpleXMLRPCRequestHandler):
        rpc_paths = ("/xmlrpc/2/common", "/xmlrpc/2/object")

        def log_message(self, *args: Any) -> None:
            pass

    rpc = SimpleXMLRPCServer(("127.0.0.1", 0), requestHandler=Handler, allow_none=True,
                             logRequests=False)
    odoo = _Odoo({"base_action_rule": "uninstalled", "base_automation": "installed"})
    rpc.register_instance(odoo)
    threading.Thread(target=rpc.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{rpc.server_address[1]}", odoo
    finally:
        rpc.shutdown()
        rpc.server_close()


def test_the_fixture_installs_the_module_of_the_series(smoke: Any, odoo_rpc: Any) -> None:
    url, odoo = odoo_rpc
    assert smoke.install_automation(url, "db", "admin", "pw", 10) == "base_action_rule installed"
    assert odoo.installed == [1]
    assert smoke.install_automation(url, "db", "admin", "pw", 17) == \
        "base_automation was already installed"
    odoo.modules.pop("base_automation")
    assert smoke.install_automation(url, "db", "admin", "pw", 18) == \
        "base_automation is not available on this series"
    with pytest.raises(SystemExit, match="could not sign in"):
        smoke.install_automation(url, "db", "admin", "wrong", 17)
