# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Regression tests for the 1.5.0 review of the permission policy.

One section per finding, each the reviewer's reproduction kept as a test:
``update()`` is a write and is checked as one; ``copy_data`` is a read, so it
needs ``read`` and its rows are redacted; profile ``full`` keeps the two
argument checks NEVER and a policy file depend on, and the docs say so;
redaction decides each field name once per call; and the docs agree with the
code (one CHANGELOG heading per kind, plugin files named from the plugin root,
the Studio page, the reason ``odoo_report`` fails, the ``--check-policy``
digest and the Read-only setting).
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from policy_fakes import ScriptedSession, call, guarded, policy, refused, server

from odoo_mcp.policy import model as policy_model
from odoo_mcp.policy import texts
from odoo_mcp.policy.cli import check_policy_main
from odoo_mcp.policy.loader import load_policy
from odoo_mcp.policy.model import MEMO_LIMIT, Policy
from odoo_mcp.registry import registry

ROOT = Path(__file__).resolve().parents[2]
ESCALATE = {"user_ids": [[1, 4, {"groups_id": [[4, 1]]}]]}


def _flat(text: str) -> str:
    """``text`` with its line breaks and indents as single spaces."""
    return " ".join(text.split())


def relational(method: str, model: str, op: str, comodel: str, field: str, command: int,
               rule: str) -> str:
    return refused(op, comodel, "relational",
                   f"this {method} on '{model}' also {op}s '{comodel}' through field '{field}' "
                   f"(command {command}), and the policy refuses '{op}' on '{comodel}' ({rule})")


# --- update() writes the records it is given -----------------------------------------------

@pytest.mark.parametrize("form", [{"ids": [7], "kwargs": {"values": ESCALATE}},
                                  {"args": [[7], ESCALATE]}], ids=["ids", "positional"])
def test_update_is_checked_like_write(form: dict[str, Any]) -> None:
    # A res.users write nested in res.partner values (adding a group: an escalation)
    # is refused through update exactly as through write, and never reaches Odoo.
    raw = ScriptedSession()
    srv = server(raw, audit_dir="off")  # the default profile, standard
    error, text = call(srv, "odoo_execute", model="res.partner", method="update", **form)
    assert error is True
    assert text == relational("update", "res.partner", "write", "res.users", "user_ids", 1,
                              "tier:security")
    error, text = call(srv, "odoo_execute", model="res.partner", method="write", ids=[7],
                       kwargs={"vals": ESCALATE})
    assert error is True
    assert text == relational("write", "res.partner", "write", "res.users", "user_ids", 1,
                              "tier:security")
    assert raw.sent() == []


def test_update_cannot_change_the_email_of_a_login_contact() -> None:
    raw = ScriptedSession()
    error, text = call(server(raw, audit_dir="off"), "odoo_execute", model="res.partner",
                       method="update", ids=[7], kwargs={"values": {"email": "x@example.com"}})
    assert error is True
    assert text == refused("write", "res.partner", "identity",
                           texts.IDENTITY_HINT.format(id=7))
    assert raw.sent() == [("res.partner", "read")]  # the guard's own read of user_ids


def test_update_needs_write_and_refuses_withheld_keys_before_odoo() -> None:
    raw = ScriptedSession()
    no_write = policy(models={"res.partner": {"write": False}})
    error, text = call(server(raw, p=no_write, audit_dir="off"), "odoo_execute",
                       model="res.partner", method="update", ids=[8],
                       kwargs={"values": {"comment": "VIP"}})
    assert error is True
    assert "refuses 'write' on 'res.partner' (profile 'standard', rule file:res.partner)" in text
    error, text = call(server(raw, audit_dir="off"), "odoo_execute", model="res.partner",
                       method="update", ids=[8], kwargs={"values": {"signup_token": "x"}})
    assert error is True
    assert text == refused("write", "res.partner", "field",
                           texts.FIELD_HINT.format(field="signup_token", model="res.partner"),
                           layer="A")
    assert raw.sent() == [] and raw.metadata == []


def test_update_of_plain_values_is_sent() -> None:
    raw = ScriptedSession()
    error, text = call(server(raw, audit_dir="off"), "odoo_execute", model="res.partner",
                       method="update", ids=[8],
                       kwargs={"values": {"comment": "VIP", "email": "new@example.com"}})
    assert error is False, text
    assert raw.sent() == [("res.partner", "read"), ("res.partner", "update")]


# --- copy_data reads the records it is given -------------------------------------------------

def test_copy_data_does_not_return_a_withheld_credential() -> None:
    raw = ScriptedSession(results={("res.company", "copy_data"): [
        {"name": "Acme", "l10n_mx_edi_pac_password": "PAC-SECRET"}]})
    error, text = call(server(raw, audit_dir="off"), "odoo_execute", model="res.company",
                       method="copy_data", ids=[1])
    assert error is False, text
    assert "PAC-SECRET" not in text
    payload = json.loads(text)
    assert payload["result"] == [{"name": "Acme"}]
    assert payload["policy_withheld_fields"] == ["res.company.l10n_mx_edi_pac_password"]


def test_copy_data_redacts_the_lines_it_copies() -> None:
    # copy_data returns the copied one2many lines as (0, 0, values) commands.
    lines = [[0, 0, {"name": "L1", "x_api_token": "LINE-SECRET"}],
             [1, 5, {"price_unit": 3, "x_api_token": "LINE-SECRET"}], [6, 0, [1, 2]]]
    raw = ScriptedSession(results={("sale.order", "copy_data"): [
        {"name": "S1", "order_line": lines, "tag_ids": [[6, 0, [1]]]}]})
    error, text = call(server(raw, audit_dir="off"), "odoo_execute", model="sale.order",
                       method="copy_data", ids=[1])
    assert error is False, text
    assert "LINE-SECRET" not in text
    payload = json.loads(text)
    assert payload["result"] == [{"name": "S1", "order_line": [
        [0, 0, {"name": "L1"}], [1, 5, {"price_unit": 3}], [6, 0, [1, 2]]],
        "tag_ids": [[6, 0, [1]]]}]
    assert payload["policy_withheld_fields"] == ["sale.order.order_line.x_api_token"]


def test_copy_data_needs_read_and_full_returns_every_field() -> None:
    raw = ScriptedSession(results={("res.company", "copy_data"): [
        {"name": "Acme", "l10n_mx_edi_pac_password": "PAC"}]})
    no_hr = policy(models={"hr.*": {"read": False}})
    error, text = call(server(raw, p=no_hr, audit_dir="off"), "odoo_execute",
                       model="hr.employee", method="copy_data", ids=[1])
    assert error is True
    assert "refuses 'read' on 'hr.employee' (profile 'standard', rule file:hr.*)" in text
    assert raw.sent() == []
    error, text = call(server(raw, policy_profile="full", audit_dir="off"), "odoo_execute",
                       model="res.company", method="copy_data", ids=[1])
    payload = json.loads(text)
    assert error is False and payload["result"] == [{"name": "Acme",
                                                    "l10n_mx_edi_pac_password": "PAC"}]
    assert "policy_withheld_fields" not in payload


# --- profile full keeps the checks NEVER depends on, and says so -----------------------------

def test_full_refuses_an_unreadable_shape_and_sends_the_named_form() -> None:
    raw = ScriptedSession()
    srv = server(raw, policy_profile="full", audit_dir="off")
    error, text = call(srv, "odoo_execute", model="sale.order", method="read_group",
                       args=[[], ["amount_total:sum"], ["partner_id"], 0, 10])
    assert error is True
    assert "(profile 'full', rule shape). Nothing was sent to Odoo." in text
    assert "pass the arguments by name" in text and raw.sent() == []
    error, text = call(srv, "odoo_execute", model="sale.order", method="read_group",
                       args=[[], ["amount_total:sum"], ["partner_id"]],
                       kwargs={"offset": 0, "limit": 10})
    assert error is False, text
    assert raw.sent() == [("sale.order", "read_group")]


def test_full_looks_up_a_dotted_path_and_refuses_when_it_cannot() -> None:
    raw = ScriptedSession(failing={"sale.order"})  # fields_get of sale.order fails
    srv = server(raw, policy_profile="full", audit_dir="off")
    error, text = call(srv, "odoo_search_read", model="sale.order",
                       domain=[["partner_id.name", "=", "x"]], fields=["name"])
    assert error is True and "(profile 'full', rule unverified)" in text
    assert raw.sent() == []
    # a plain field name needs no lookup, so the same failure does not stop it
    error, text = call(srv, "odoo_search_read", model="sale.order",
                       domain=[["name", "=", "x"]], fields=["name"])
    assert error is False, text
    assert raw.sent() == [("sale.order", "search_read")]


def test_the_docs_say_what_full_keeps() -> None:
    doc = (ROOT / "docs" / "policy.md").read_text(encoding="utf-8")
    profiles = doc.split("\n## Profiles\n", 1)[1].split("\n## ", 1)[0]
    assert ("| argument shapes and related-model lookups (rules `shape` and `unverified`) "
            "| on | on | on | on |") in profiles
    full = _flat(profiles.split("- **`full` is the 1.4 behaviour**", 1)[1].split("\n\n", 1)[0])
    assert "(rule `shape`)" in full and "(rule `unverified`)" in full
    assert "Pass the arguments by name" in full
    built_in = _flat(doc.split("\n## Built-in rules\n", 1)[1].split("\n### ", 1)[0])
    assert "Two parts stay on in every profile" in built_in
    readme = _flat((ROOT / "README.md").read_text(encoding="utf-8"))
    assert "`full` still refuses a call whose arguments it cannot read with certainty" in readme
    changelog = _flat((ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
                      .split("\n## [1.5.0]", 1)[1].split("\n## [", 1)[0])
    assert "`full` still refuses a call whose arguments the policy cannot read" in changelog


# --- redaction decides each field name once ---------------------------------------------------

def test_redaction_decides_each_field_name_once(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    real = policy_model._credential_like
    monkeypatch.setattr(policy_model, "_credential_like",
                        lambda name: asked.append(name) or real(name))
    n, f = 2000, 40
    fields = {f"f{i}": {"type": "char"} for i in range(f)}
    rows = [{"id": i, "signup_token": "T", **{f"f{j}": "x" for j in range(f)}}
            for i in range(n)]
    raw = ScriptedSession(fields={"res.partner": fields},
                          results={("res.partner", "search_read"): rows})
    error, text = call(server(raw, audit_dir="off"), "odoo_search_read", model="res.partner",
                       fields=[], limit=n)
    assert error is False
    payload = json.loads(text)
    assert len(payload["records"]) == n
    assert all("signup_token" not in row and len(row) == f + 1 for row in payload["records"])
    assert payload["policy_withheld_fields"] == ["res.partner.signup_token"]
    # once per distinct name (42 here), not once per key of every row (84,000)
    assert len(asked) <= 2 * (f + 2), len(asked)


def test_the_memo_is_per_policy_and_bounded() -> None:
    standard, full = Policy(), Policy(profile_name="full")
    for _ in range(2):
        assert standard.field_withheld("res.company", "l10n_mx_edi_pac_password")
        assert not full.field_withheld("res.company", "l10n_mx_edi_pac_password")
        assert standard.field_withheld_everywhere("signup_token")
        assert not full.field_withheld_everywhere("signup_token")
    for i in range(MEMO_LIMIT + 10):
        standard.field_withheld("res.partner", f"x_field_{i}")
        standard.field_withheld_everywhere(f"x_field_{i}")
    assert len(standard._withheld_memo) <= MEMO_LIMIT
    assert len(standard._everywhere_memo) <= MEMO_LIMIT
    assert standard.field_withheld("res.partner", "signup_token")
    assert not standard.field_withheld("res.partner", "payment_token_id")


def test_redacted_rows_are_copies_and_nested_rows_are_still_redacted() -> None:
    row = {"id": 3, "name": "Acme", "signup_token": "T", "category_id": [1, 2],
           "parent_id": [9, "Parent"], "child_ids": [{"id": 4, "name": "Kid",
                                                     "signup_token": "T2"}]}
    raw = ScriptedSession(results={("res.partner", "search_read"): [row]})
    error, text = call(server(raw, audit_dir="off"), "odoo_search_read", model="res.partner")
    payload = json.loads(text)
    assert error is False and payload["records"] == [
        {"id": 3, "name": "Acme", "category_id": [1, 2], "parent_id": [9, "Parent"],
         "child_ids": [{"id": 4, "name": "Kid"}]}]
    assert payload["policy_withheld_fields"] == ["res.partner.child_ids.signup_token",
                                                 "res.partner.signup_token"]
    # what the session returned is left as it was: the tool gets copies
    assert row["signup_token"] == "T" and row["child_ids"][0]["signup_token"] == "T2"
    # the records of unfolded groups (web_read_group) are rows of the model too
    groups = {"length": 1, "groups": [{"stage_id": [1, "New"], "__count": 1, "__records": [
        {"id": 3, "name": "A", "signup_token": "T"}]}]}
    raw = ScriptedSession(results={("res.partner", "web_read_group"): groups})
    error, text = call(server(raw, audit_dir="off"), "odoo_execute", model="res.partner",
                       method="web_read_group",
                       kwargs={"domain": [], "groupby": ["stage_id"], "aggregates": ["__count"]})
    payload = json.loads(text)
    assert error is False, text
    assert payload["result"]["groups"][0] == {"stage_id": [1, "New"], "__count": 1,
                                              "__records": [{"id": 3, "name": "A"}]}
    assert payload["policy_withheld_fields"] == ["res.partner.signup_token"]


def test_only_a_tool_with_internal_calls_keeps_the_rows_it_read() -> None:
    raw = ScriptedSession()
    session, scope = guarded("odoo_read", {"model": "res.partner", "ids": [3],
                                           "fields": ["name"]}, session=raw)
    assert session.execute("res.partner", "read", [[3]], {"fields": ["name"]}) == [
        {"id": 3, "name": "Acme"}]
    assert scope.records == {}
    # odoo_record_documents reads its rows back in its internal predicates
    session, scope = guarded("odoo_record_documents", {"model": "account.move", "res_id": 7},
                             session=raw)
    session.execute("account.move", "read", [[7]],
                    {"fields": ["message_main_attachment_id", "invoice_pdf_report_id"]})
    assert scope.records["account.move"][7]["message_main_attachment_id"] == [10, "scan.png"]


# --- the docs agree with the code ---------------------------------------------------------------

def test_no_release_repeats_a_changelog_heading_kind() -> None:
    # Keep a Changelog: one heading per kind in a release ("Changed (secure
    # defaults)" is a Changed heading); the GitHub release notes are cut from here.
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    for section in text.split("\n## [")[1:]:
        kinds = [heading.split()[0] for heading in re.findall(r"^### (.+)$", section,
                                                              re.MULTILINE)]
        assert len(kinds) == len(set(kinds)), (section.split("]", 1)[0], kinds)


_PLUGIN_FILE = re.compile(r"server/run_stdio\.py|scripts/[A-Za-z0-9_]+\.py|"
                          r"docs/policy-examples/[A-Za-z0-9_.-]+")


def test_skills_and_commands_name_plugin_files_from_the_plugin_root() -> None:
    # They run in the user's project folder, where a relative path fails.
    pages = [*ROOT.glob("skills/*/SKILL.md"), *ROOT.glob("commands/*.md"),
             *ROOT.glob("agents/*.md")]
    found = 0
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for match in _PLUGIN_FILE.finditer(text):
            found += 1
            assert text[:match.start()].endswith("${CLAUDE_PLUGIN_ROOT}/"), (
                page.relative_to(ROOT).as_posix(), match.group(0))
    assert found >= 3  # the setup skill's policy check among them


def test_the_studio_parity_page_names_the_profile_its_tools_need() -> None:
    text = (ROOT / "docs" / "odoo-studio-parity.md").read_text(encoding="utf-8")
    section = text.split("\n## Permission profile\n", 1)[1].split("\n## ", 1)[0]
    for name in ("`standard`", "`builder`", "odoo_add_field", "odoo_add_automation",
                 "ir.ui.view", "(policy.md)"):
        assert name in section, name
    assert "\u2014" not in section and "\u2013" not in section
    # what the page says is what the policy does
    standard, builder = Policy(), Policy(profile_name="builder")
    for tool in ("odoo_add_field", "odoo_add_automation"):
        assert not standard.tool_visible(registry.get(tool))
        assert builder.tool_visible(registry.get(tool))
    assert standard.decide("create", "ir.ui.view").rule == "tier:customization"
    assert builder.decide("create", "ir.ui.view").allowed


def test_the_odoo_report_reason_is_the_same_everywhere() -> None:
    # The tool relied on the private _render_qweb_pdf, which Odoo refuses over RPC
    # on every version: not "reports cannot be rendered on 14+" (it never worked on
    # 10-13 either), nor "Odoo renders no report over RPC on any version".
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    row = next(line for line in readme.splitlines() if line.startswith("| Deprecated |"))
    for text in (registry.get("odoo_report").description, row):
        assert "_render_qweb_pdf" in text and "every version" in text, text
    surfaces = {
        "README.md": readme,
        "docs/compat-matrix.md": (ROOT / "docs" / "compat-matrix.md").read_text(encoding="utf-8"),
        "skills/odoo-mcp-tools/SKILL.md": (ROOT / "skills" / "odoo-mcp-tools" / "SKILL.md"
                                           ).read_text(encoding="utf-8"),
        "odoo_report": registry.get("odoo_report").description,
        "odoo_record_documents": registry.get("odoo_record_documents").description,
    }
    wrong = re.compile(r"render(?:ed)? (?:reports )?over RPC on 14\+|PDFs on (?:Odoo )?14\+|"
                       r"does not render reports over RPC on any version")
    for name, text in surfaces.items():
        assert not wrong.search(_flat(text)), name


def test_check_policy_reports_the_digest_with_read_only_off() -> None:
    path = ROOT / "docs" / "policy-examples" / "sales-team.json"
    names = [tool.name for tool in registry.all()]
    digests = {readonly: load_policy(SimpleNamespace(policy_profile="standard",
                                                     policy_file=str(path),
                                                     readonly=readonly), names).digest
               for readonly in (False, True)}
    assert digests[False] != digests[True]
    out = io.StringIO()
    code = check_policy_main(str(path), profile=None, explain=[], as_json=False,
                             tools=registry.all(), out=out)
    lines = out.getvalue().splitlines()
    assert code == 0 and f"digest: {digests[False]}" in lines
    doc = (ROOT / "docs" / "policy.md").read_text(encoding="utf-8")
    section = _flat(doc.split("\n## Checking a file offline: `--check-policy`\n", 1)[1]
                    .split("\n## ", 1)[0])
    assert "with Read-only mode off" in section and "`ODOO_READONLY=1`" in section


def test_the_readonly_setting_says_the_write_tools_are_hidden() -> None:
    # The behaviour itself: test_readonly_group.test_readonly_hides_the_write_tools...
    lines = (ROOT / "server" / "src" / "odoo_mcp" / "config.py").read_text(
        encoding="utf-8").splitlines()
    index = next(i for i, line in enumerate(lines) if line.strip() == "readonly: bool = False")
    comment = []
    while lines[index - 1].strip().startswith("#"):
        index -= 1
        comment.insert(0, lines[index].strip().lstrip("#").strip())
    text = " ".join(comment)
    assert "hides every non-read-only tool from tools/list" in text, text
