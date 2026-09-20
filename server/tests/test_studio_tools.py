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
    def __init__(self, fields_get_result: dict | None = None, version: int = 17) -> None:
        self.calls: list[tuple] = []
        self._fg = fields_get_result or {}
        self._version = version
        self.invalidated: list[str] = []

    def facts(self) -> EnvFacts:
        return EnvFacts(version=self._version, edition="community", deployment="onprem")

    def fields_get(self, model: str, attributes=None) -> dict:
        return self._fg

    def invalidate_fields(self, model: str) -> None:
        self.invalidated.append(model)

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
    "for rec in records:\n    rec.priority += 'x'",
    "for rec in records:\n    del rec.priority",
    "for rec in records:\n    del rec['priority']",
])
def test_safe_eval_rejects_forbidden(bad: str) -> None:
    with pytest.raises(CompatError):
        validate_safe_eval(bad)


def test_safe_eval_allows_subscript_store_on_locals() -> None:
    # STORE_SUBSCR is a safe opcode server-side: building a plain dict is fine.
    validate_safe_eval("vals = {}\nvals['priority'] = '3'\nrecords.write(vals)")


def test_safe_eval_allows_plain_code() -> None:
    validate_safe_eval(
        "for rec in records:\n    rec.write({'priority': '3'})\n"
        "action = {'type': 'ir.actions.act_window_close'}"
    )


# --- odoo_add_automation ----------------------------------------------------

def test_automation_inline_v16plus() -> None:
    fake = FakeSession({"trigger": {}, "state": {}, "code": {}, "filter_domain": {}})
    res = odoo_add_automation(
        _ctx(fake),
        {"model": "crm.lead", "name": "Tag",
         "code": "for rec in records:\n    rec.write({'priority': '3'})"},
    )
    assert res["mode"] == "inline-server-action"
    vals = next(c for c in fake.calls if c[0] == "base.automation")[2][0]
    assert vals["state"] == "code"
    assert "write({'priority'" in vals["code"]
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


def test_automation_rejects_store_attr_before_rpc() -> None:
    fake = FakeSession({"trigger": {}, "state": {}, "code": {}})
    with pytest.raises(CompatError):
        odoo_add_automation(
            _ctx(fake),
            {"model": "crm.lead", "name": "x",
             "code": "for rec in records:\n    rec.priority = '3'"},
        )
    assert not any(c[1] == "create" for c in fake.calls)


def test_add_field_one2many_requires_relation_field() -> None:
    with pytest.raises(CompatError):
        odoo_add_field(
            _ctx(FakeSession()),
            {"model": "res.partner", "name": "orders", "label": "Orders",
             "field_type": "one2many", "relation": "sale.order"},
        )


@pytest.mark.parametrize("bad_sel", [
    [["a"]],
    [["a", "A", "extra"]],
    [[1, 2]],
    [["", "A"]],
    [[["a", "A"], ["a", "dup"]][0], ["a", "dup"]],
])
def test_add_field_selection_rejects_malformed(bad_sel) -> None:
    with pytest.raises(CompatError):
        odoo_add_field(
            _ctx(FakeSession()),
            {"model": "res.partner", "name": "tier", "label": "Tier",
             "field_type": "selection", "selection": bad_sel},
        )


def test_add_field_selection_accepts_numeric_values() -> None:
    # Integer JSON values are coerced to strings (Odoo stores them as char).
    fake = FakeSession()
    odoo_add_field(
        _ctx(fake),
        {"model": "res.partner", "name": "tier", "label": "Tier",
         "field_type": "selection", "selection": [[1, "One"], [2, "Two"]]},
    )
    vals = next(c for c in fake.calls if c[0] == "ir.model.fields")[2][0]
    assert vals["selection"] == repr([("1", "One"), ("2", "Two")])


def test_add_field_monetary_accepts_currency_field() -> None:
    fake = FakeSession()
    odoo_add_field(
        _ctx(fake),
        {"model": "res.partner", "name": "limit", "label": "Limit",
         "field_type": "monetary", "currency_field": "x_currency_id"},
    )
    vals = next(c for c in fake.calls if c[0] == "ir.model.fields")[2][0]
    assert vals["currency_field"] == "x_currency_id"


def test_add_field_invalidates_schema_cache() -> None:
    fake = FakeSession()
    odoo_add_field(
        _ctx(fake),
        {"model": "res.partner", "name": "loyalty", "label": "Loyalty",
         "field_type": "integer"},
    )
    assert fake.invalidated == ["res.partner"]


def test_add_field_resolves_relation_model() -> None:
    fake = FakeSession(version=18)
    odoo_add_field(
        _ctx(fake),
        {"model": "res.partner", "name": "pkg", "label": "Pkg",
         "field_type": "many2one", "relation": "stock.package"},
    )
    vals = next(c for c in fake.calls if c[0] == "ir.model.fields")[2][0]
    assert vals["relation"] == "stock.quant.package"


def test_automation_v10_uses_legacy_model() -> None:
    seen: list[str] = []

    class V10Session(FakeSession):
        def __init__(self) -> None:
            super().__init__({"trigger": {}, "server_action_ids": {}}, version=10)

        def fields_get(self, model: str, attributes=None) -> dict:
            seen.append(model)
            return self._fg

    fake = V10Session()
    res = odoo_add_automation(
        _ctx(fake),
        {"model": "crm.lead", "name": "Tag", "code": "pass"},
    )
    assert seen == ["base.action.rule"]
    assert res["mode"] == "linked-server-action"
    base_vals = next(c for c in fake.calls if c[0] == "base.action.rule")[2][0]
    assert base_vals["server_action_ids"] == [(6, 0, [555])]


def test_automation_linked_failure_cleans_orphan() -> None:
    class FailSecond(FakeSession):
        def execute(self, model, method, args=None, kwargs=None):
            self.calls.append((model, method, args, kwargs))
            if model == "ir.model" and method == "search":
                return [42]
            if model == "ir.actions.server" and method == "create":
                return 555
            if model == "base.automation" and method == "create":
                from odoo_mcp.errors import OdooFault

                raise OdooFault("boom")
            return None

    fake = FailSecond({"trigger": {}, "action_server_id": {}})
    with pytest.raises(CompatError, match="was removed"):
        odoo_add_automation(_ctx(fake), {"model": "crm.lead", "name": "Tag", "code": "pass"})
    unlinks = [c for c in fake.calls if c[0] == "ir.actions.server" and c[1] == "unlink"]
    assert unlinks and unlinks[0][2] == [[555]]


def test_automation_linked_failure_reports_remaining_orphan() -> None:
    class FailBoth(FakeSession):
        def execute(self, model, method, args=None, kwargs=None):
            self.calls.append((model, method, args, kwargs))
            if model == "ir.model" and method == "search":
                return [42]
            if model == "ir.actions.server" and method == "create":
                return 555
            if model == "ir.actions.server" and method == "unlink":
                from odoo_mcp.errors import OdooFault

                raise OdooFault("no unlink permission")
            if model == "base.automation" and method == "create":
                from odoo_mcp.errors import OdooFault

                raise OdooFault("boom")
            return None

    fake = FailBoth({"trigger": {}, "action_server_id": {}})
    with pytest.raises(CompatError, match="could NOT be removed.*555"):
        odoo_add_automation(_ctx(fake), {"model": "crm.lead", "name": "Tag", "code": "pass"})


def test_automation_missing_link_raises_before_create() -> None:
    fake = FakeSession({"trigger": {}})
    with pytest.raises(CompatError):
        odoo_add_automation(_ctx(fake), {"model": "crm.lead", "name": "Tag", "code": "pass"})
    assert not any(c[0] == "ir.actions.server" and c[1] == "create" for c in fake.calls)
