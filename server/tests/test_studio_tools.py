# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Tests for the Studio-style tools (custom fields, automations, safe_eval guard)."""

from __future__ import annotations

import pytest

from odoo_mcp.compat import EnvFacts
from odoo_mcp.errors import CompatError
from odoo_mcp.registry import ToolContext
from odoo_mcp.tools.studio import odoo_add_automation, odoo_add_field, validate_safe_eval


class FakeSession:
    def __init__(self, fields_get_result: dict | None = None) -> None:
        self.calls: list[tuple] = []
        self._fg = fields_get_result or {}

    def facts(self) -> EnvFacts:
        return EnvFacts(version=17, edition="community", deployment="onprem")

    def fields_get(self, model: str, attributes=None) -> dict:
        return self._fg

    def execute(self, model, method, args=None, kwargs=None):
        self.calls.append((model, method, args, kwargs))
        if model == "ir.model" and method == "search":
            return [42]
        if method == "create":
            # return a deterministic id based on the model
            return {"ir.model.fields": 999, "ir.actions.server": 555,
                    "base.automation": 777}.get(model, 1)
        return None


def _ctx(fake: FakeSession) -> ToolContext:
    return ToolContext(session=fake, manager=None)


# --- odoo_add_field ---------------------------------------------------------

def test_add_field_forces_x_prefix_and_manual_state() -> None:
    fake = FakeSession()
    res = odoo_add_field(
        _ctx(fake),
        {"model": "res.partner", "name": "loyalty", "label": "Loyalty", "field_type": "integer"},
    )
    assert res["field"] == "x_loyalty"
    assert res["field_id"] == 999
    create = next(c for c in fake.calls if c[0] == "ir.model.fields" and c[1] == "create")
    vals = create[2][0]
    assert vals["name"] == "x_loyalty"
    assert vals["ttype"] == "integer"
    assert vals["state"] == "manual"
    assert vals["model_id"] == 42
    assert vals["model"] == "res.partner"


def test_add_field_many2one_requires_relation() -> None:
    with pytest.raises(CompatError):
        odoo_add_field(
            _ctx(FakeSession()),
            {"model": "res.partner", "name": "mgr", "label": "Mgr", "field_type": "many2one"},
        )


def test_add_field_selection_serialised() -> None:
    fake = FakeSession()
    odoo_add_field(
        _ctx(fake),
        {
            "model": "res.partner", "name": "tier", "label": "Tier", "field_type": "selection",
            "selection": [["a", "A"], ["b", "B"]],
        },
    )
    vals = next(c for c in fake.calls if c[0] == "ir.model.fields")[2][0]
    assert vals["selection"] == repr([("a", "A"), ("b", "B")])


# --- safe_eval guard --------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "import os",
    "def f():\n    pass",
    "class C:\n    pass",
    "return 1",
    "x = obj._secret",
    "for rec in records:\n    rec.priority = '3'",
    "rec.priority='3'",
])
def test_safe_eval_rejects_forbidden(bad: str) -> None:
    with pytest.raises(CompatError):
        validate_safe_eval(bad)


def test_safe_eval_allows_plain_code() -> None:
    validate_safe_eval("for rec in records:\n    rec.write({'priority': '3'})\naction = {'type': 'ir.actions.act_window_close'}")


# --- odoo_add_automation ----------------------------------------------------

def test_automation_inline_v16plus() -> None:
    fake = FakeSession({"trigger": {}, "state": {}, "code": {}, "filter_domain": {}})
    res = odoo_add_automation(
        _ctx(fake),
        {"model": "crm.lead", "name": "Tag", "code": "for rec in records:\n    rec.write({'priority': '3'})"},
    )
    assert res["mode"] == "inline-server-action"
    vals = next(c for c in fake.calls if c[0] == "base.automation")[2][0]
    assert vals["state"] == "code"
    assert "rec.write" in vals["code"]
    assert vals["trigger"] == "on_create_or_write"


def test_automation_linked_older() -> None:
    fake = FakeSession({"trigger": {}, "action_server_id": {}})
    res = odoo_add_automation(
        _ctx(fake),
        {"model": "crm.lead", "name": "Tag", "code": "pass"},
    )
    assert res["mode"] == "linked-server-action"
    assert res["server_action_id"] == 555
    base_vals = next(c for c in fake.calls if c[0] == "base.automation")[2][0]
    assert base_vals["action_server_id"] == 555


def test_automation_rejects_bad_code_before_rpc() -> None:
    fake = FakeSession({"state": {}, "code": {}})
    with pytest.raises(CompatError):
        odoo_add_automation(_ctx(fake), {"model": "crm.lead", "name": "x", "code": "import os"})
    # nothing should have been created
    assert not any(c[1] == "create" for c in fake.calls)


# --- Codex PR5 hardening ----------------------------------------------------

def test_add_field_one2many_requires_relation_field() -> None:
    with pytest.raises(CompatError):
        odoo_add_field(
            _ctx(FakeSession()),
            {"model": "res.partner", "name": "orders", "label": "Orders",
             "field_type": "one2many", "relation": "sale.order"},
        )


def test_add_field_selection_entry_must_be_pair() -> None:
    with pytest.raises(CompatError):
        odoo_add_field(
            _ctx(FakeSession()),
            {"model": "res.partner", "name": "tier", "label": "Tier",
             "field_type": "selection", "selection": [["a"]]},
        )


def test_add_field_monetary_accepts_currency_field() -> None:
    fake = FakeSession()
    res = odoo_add_field(
        _ctx(fake),
        {"model": "res.partner", "name": "credit", "label": "Credit",
         "field_type": "monetary", "currency_field": "x_currency_id"},
    )
    assert res["field_id"] == 999
    vals = next(c for c in fake.calls if c[0] == "ir.model.fields")[2][0]
    assert vals["currency_field"] == "x_currency_id"


def test_automation_linked_determines_link_before_create() -> None:
    # No link field in the automation schema -> must fail BEFORE creating
    # the server action (no orphan ir.actions.server record).
    fake = FakeSession({"trigger": {}})
    with pytest.raises(CompatError):
        odoo_add_automation(_ctx(fake), {"model": "crm.lead", "name": "x", "code": "pass"})
    assert not any(c[0] == "ir.actions.server" and c[1] == "create" for c in fake.calls)
