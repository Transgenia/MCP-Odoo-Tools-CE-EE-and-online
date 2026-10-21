# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Regression tests for the 1.5.0 review of the permission policy.

One section per finding, each the reviewer's reproduction kept as a test:
``update()`` is a write and is checked as one; ``copy_data`` is a read, so it
needs ``read`` and its rows are redacted; and redaction decides each field name
once per call.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from policy_fakes import ScriptedSession, call, guarded, policy, refused, server

from odoo_mcp.policy import model as policy_model
from odoo_mcp.policy import texts
from odoo_mcp.policy.model import MEMO_LIMIT, Policy

ESCALATE = {"user_ids": [[1, 4, {"groups_id": [[4, 1]]}]]}


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
