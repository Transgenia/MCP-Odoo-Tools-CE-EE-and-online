# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Sixth adversarial round: the context-default channel, and three false refusals the
round-four/five context checks introduced.

The context part of findings 1 and 2 is superseded by round seven
(``test_policy_review7_followups.py``): a ``default_<field>`` holding a list or an object
is refused at Layer A whatever it holds, because Odoo applies a context default to every
record the call creates, nested lines and other models' records included, and no check
against one model can follow that. What stays pinned here:

  * finding 1 (blocker): a list that mixes an x2many command tuple with a bare id
    (``[[4, 4], 99]``) slipped past the guard's command expansion through a context
    default. That form now stops at Layer A (round seven keeps the reproductions); the
    same list in ``values``, and in a call-class vals dict (the backstop,
    ``_scan_call_mapping``), still fails closed with rule ``shape``.
  * finding 2 (regression): the MRP Mark-as-Done backorder wizard. Its action context
    carries the lines as ``default_mrp_production_backorder_line_ids``, which is refused
    at Layer A with the remedy; the wizard runs with the same lines in values, where they
    are decided against the comodel (a create on a business line model).
  * finding 3 (regression): the create-only structural rules over the plain defaults ran
    for every class, so a pinned ir.attachment search_read whose context carried
    ``default_res_model`` (a readable-but-not-writable parent) was refused on the create
    rule. They now run only for a creating class.

Plus F1: the Odoo web client puts ``uid`` in every call's context; it was the one
key not in the allowlist, so ``account.move.action_post`` / ``sale.order.action_confirm``
replayed with the real web context were refused on ``uid`` alone.
"""

from __future__ import annotations

import pytest
from policy_fakes import ScriptedSession, call, policy, server

# The MRP Mark-as-Done backorder wizard metadata (the field is on the transient).
MRP_META = {
    "mrp.production": {"name": {"type": "char"}},
    "mrp.production.backorder": {
        "mrp_production_ids": {"type": "many2many", "relation": "mrp.production"},
        "mrp_production_backorder_line_ids": {
            "type": "one2many", "relation": "mrp.production.backorder.line",
            "relation_field": "mrp_production_backorder_id"}},
    "mrp.production.backorder.line": {
        "mrp_production_id": {"type": "many2one", "relation": "mrp.production"},
        "to_backorder": {"type": "boolean"}},
}
MRP_LINES = [[0, 0, {"mrp_production_id": 5, "to_backorder": True}]]
WEB_USER_CONTEXT = {"lang": "es_MX", "tz": "America/Mexico_City", "uid": 2,
                    "allowed_company_ids": [1]}


def _create(raw, model, context, *, p=None):
    err, text = call(server(raw, p=p or policy("standard")), "odoo_execute",
                     model=model, method="create", args=[{"name": "x"}],
                     kwargs={"context": context})
    return err, (model, "create") in raw.sent(), text


# --- finding 1 (blocker): the mixed command/id list fails closed ----------------------------
# The context form of these lists stops at Layer A since round seven
# (test_policy_review7_followups.py keeps the reproductions); the values form fails closed.

def test_the_same_mixed_list_in_values_fails_closed_control() -> None:
    raw = ScriptedSession()
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="create", args=[{"name": "x", "user_ids": [[4, 4], 99]}], kwargs={})
    assert err is True and ("res.partner", "create") not in raw.sent()
    assert "shape" in text  # the values path fails closed with rule shape; so does the default


def test_a_clean_command_default_into_a_tier_stops_at_layer_a_control() -> None:
    # A clean SET of res.users is a list too: refused at Layer A, never decided per command.
    raw = ScriptedSession()
    err, reached, text = _create(raw, "res.partner", {"default_user_ids": [[6, 0, [4]]]})
    assert err is True and reached is False
    assert "rule context" in text and "Nothing was sent to Odoo." in text
    assert raw.calls == [] and raw.metadata == []


# --- finding 1 twin: the call-class backstop fails closed the same way ----------------------

@pytest.mark.parametrize("vals", [
    {"user_ids": [[4, 4], 99]},       # security comodel, mixed
    {"category_id": [[4, 1], 9]},     # business comodel, but still a mixed/malformed list
])
def test_a_mixed_list_in_a_call_class_vals_dict_fails_closed(vals) -> None:
    # A module-specific writer reached by odoo_execute (action_apply(vals)): the backstop
    # hands a known-x2many key to _check_commands, which fails closed on a mixed list, so
    # a LINK smuggled next to a bare id cannot slip past as a plain nested value.
    raw = ScriptedSession()
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="action_apply", args=[vals])
    assert err is True, f"a mixed list in a call-class vals dict reached Odoo: {vals}: {text[:160]}"
    assert ("res.partner", "action_apply") not in raw.sent()


def test_a_clean_link_in_a_call_class_vals_dict_still_runs_control() -> None:
    # A clean (4, id) link to a business comodel through the backstop is a read of it and runs.
    raw = ScriptedSession()
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="action_apply", args=[{"category_id": [[4, 1]]}])
    assert err is False, text
    assert ("res.partner", "action_apply") in raw.sent()


# --- finding 2 (regression): the MRP backorder wizard takes its lines in values -------------

def test_the_mrp_backorder_wizard_runs_with_its_lines_in_values() -> None:
    # The flow the action context drove, with the lines and the productions in values:
    # each line is a create on a business line model, decided against the comodel. The
    # action's plain context keys ride along.
    raw = ScriptedSession(fields=MRP_META)
    err, text = call(server(raw, p=policy("standard")), "odoo_execute",
                     model="mrp.production.backorder", method="create",
                     args=[{"mrp_production_ids": [[6, 0, [5]]],
                            "mrp_production_backorder_line_ids": MRP_LINES}],
                     kwargs={"context": {"active_model": "mrp.production", "active_id": 5,
                                         "active_ids": [5]}})
    assert err is False, text
    assert ("mrp.production.backorder", "create") in raw.sent()


def test_the_mrp_backorder_action_context_is_refused_at_layer_a_with_the_remedy() -> None:
    raw = ScriptedSession(fields=MRP_META)
    context = {"default_mrp_production_ids": [5],
               "default_mrp_production_backorder_line_ids": MRP_LINES}
    err, reached, text = _create(raw, "mrp.production.backorder", context)
    assert err is True and reached is False
    assert "rule context" in text and "Nothing was sent to Odoo." in text
    assert "context key 'default_mrp_production_ids' holds a list or an object" in text
    assert "pass those values in the record's values, where they are checked" in text
    assert raw.calls == []


# --- finding 3 (regression): the create-only default rules skip a read --------------------

ATT_DOMAIN = [["res_model", "=", "res.partner.bank"], ["res_id", "=", 4]]


def test_reading_a_bank_accounts_attachments_with_the_parent_default_runs() -> None:
    # res.partner.bank is readable (not writable) under standard; a search_read pinned to
    # it, with default_res_model naming it, creates nothing, so the create rule must not fire.
    raw = ScriptedSession()
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="ir.attachment",
                     method="search_read",
                     kwargs={"domain": ATT_DOMAIN, "fields": ["name"],
                             "context": {"default_res_model": "res.partner.bank",
                                         "default_res_id": 4}})
    assert err is False, text
    assert ("ir.attachment", "search_read") in raw.sent()


def test_a_read_of_a_delegating_child_with_its_link_field_default_runs() -> None:
    # product.document delegates to ir.attachment through ir_attachment_id; setting that link
    # on CREATE is refused (4.4), but a read does not create, so the default is inert.
    raw = ScriptedSession()
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="product.document",
                     method="search_read",
                     kwargs={"domain": [["name", "!=", False]], "fields": ["name"],
                             "context": {"default_ir_attachment_id": 5}})
    assert err is False, text
    assert ("product.document", "search_read") in raw.sent()


def test_the_create_form_of_the_same_delegation_link_is_still_refused_control() -> None:
    raw = ScriptedSession()
    err, reached, _ = _create(raw, "product.document", {"default_ir_attachment_id": 5})
    assert err is True and reached is False


# --- F1: uid is a safe context key ---------------------------------------------------------

def test_invoice_post_with_the_web_client_context_runs() -> None:
    raw = ScriptedSession(results={("account.move", "action_post"): True})
    context = {**WEB_USER_CONTEXT, "default_move_type": "out_invoice", "validate_analytic": True}
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="account.move",
                     method="action_post", ids=[7], kwargs={"context": context})
    assert err is False, text
    assert ("account.move", "action_post") in raw.sent()


def test_sale_confirmation_with_the_web_client_context_runs() -> None:
    raw = ScriptedSession(results={("sale.order", "action_confirm"): True})
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="sale.order",
                     method="action_confirm", ids=[1], kwargs={"context": dict(WEB_USER_CONTEXT)})
    assert err is False, text
    assert ("sale.order", "action_confirm") in raw.sent()


def test_uid_alone_lets_a_plain_read_run() -> None:
    raw = ScriptedSession()
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="search_read",
                     kwargs={"domain": [], "fields": ["name"], "context": {"uid": 2}})
    assert err is False, text
    assert ("res.partner", "search_read") in raw.sent()
