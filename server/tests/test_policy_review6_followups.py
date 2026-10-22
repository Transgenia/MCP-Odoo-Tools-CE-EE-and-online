# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Sixth adversarial round: the context-default channel closed by construction, and
three false refusals the round-four/five context checks introduced.

The context-default channel leaked three rounds running because the guard
reimplemented a *subset* of the values-checking machinery for ``default_<field>``,
and the subset kept drifting from the real ``_check_values`` / ``_check_commands``
path. Three concrete drifts:

  * finding 1 (blocker): Layer A ``_default_list_is_link_only`` accepted a list that
    mixes an x2many command tuple with a bare id (``[[4, 4], 99]``) as "link-only",
    while the guard's ``_commands`` returned None for it and the guard then SKIPPED
    the field (fail open). So ``default_user_ids`` / ``default_bank_ids`` /
    ``default_message_follower_ids`` carrying a LINK into a sealed tier reached Odoo
    under ``standard`` -- while the identical value in ``values`` failed closed. The
    fix hands every known-x2many ``default_<field>`` list to the same ``_check_commands``
    a values key takes, so a list the values path refuses cannot pass here, whatever
    its shape. The same fail-open twin in the call-class backstop (``_scan_call_mapping``)
    is closed the same way.
  * finding 2 (regression): round four refused ANY ``default_<x2many>`` list that was
    not link-only, at Layer A, before any metadata. That broke the MRP Mark-as-Done
    backorder wizard, whose action context carries ``default_mrp_production_backorder_line_ids``
    as ``(0, 0, vals)`` lines. Deciding the list exactly as the same list in values
    (a create on a business line model) lets the wizard run, while the sealed-comodel
    cases round four closed stay refused.
  * finding 3 (regression): the create-only structural default rules ran for every
    class, so a pinned ir.attachment search_read whose context carried
    ``default_res_model`` (a readable-but-not-writable parent) was refused on the
    create rule. Defaults fill only records a call creates, so the rules now run only
    for a creating class.

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


# --- finding 1 (blocker): the mixed command/id list fails closed in the context -------------

@pytest.mark.parametrize("context", [
    {"default_user_ids": [[4, 4], 99]},            # one2many to res.users (security): LINK + id
    {"default_user_ids": [[6, 0, [4]], 9]},        # SET then a trailing bare id
    {"default_bank_ids": [[4, 7], 9]},             # res.partner.bank (security)
    {"default_message_follower_ids": [[4, 7], 9]},  # mail.followers (outbound)
])
def test_a_mixed_command_id_list_in_a_context_default_fails_closed(context) -> None:
    raw = ScriptedSession()
    err, reached, text = _create(raw, "res.partner", context)
    assert err is True, f"a mixed command/id list reached Odoo unrefused: {context}: {text[:160]}"
    assert reached is False, f"the create reached Odoo carrying {context}"


def test_the_same_mixed_list_in_values_fails_closed_control() -> None:
    raw = ScriptedSession()
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="create", args=[{"name": "x", "user_ids": [[4, 4], 99]}], kwargs={})
    assert err is True and ("res.partner", "create") not in raw.sent()
    assert "shape" in text  # the values path fails closed with rule shape; so does the default


def test_a_clean_command_default_into_a_tier_is_still_refused_control() -> None:
    raw = ScriptedSession()
    err, reached, _ = _create(raw, "res.partner", {"default_user_ids": [[6, 0, [4]]]})
    assert err is True and reached is False  # a clean SET of res.users is a tier write


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


# --- finding 2 (regression): the MRP backorder wizard runs with its action context ---------

def test_the_mrp_backorder_wizard_runs_with_its_action_context() -> None:
    raw = ScriptedSession(fields=MRP_META)
    context = {"default_mrp_production_ids": [5],
               "default_mrp_production_backorder_line_ids": MRP_LINES}
    err, reached, text = _create(raw, "mrp.production.backorder", context)
    # args=[{"name": "x"}] in _create is a harmless extra value; the line create is the point.
    assert err is False, text
    assert reached is True


def test_the_same_backorder_lines_in_values_run_control() -> None:
    raw = ScriptedSession(fields=MRP_META)
    err, text = call(server(raw, p=policy("standard")), "odoo_execute",
                     model="mrp.production.backorder", method="create",
                     args=[{"mrp_production_ids": [[6, 0, [5]]],
                            "mrp_production_backorder_line_ids": MRP_LINES}])
    assert err is False, text


@pytest.mark.parametrize("context", [
    {"default_bank_ids": [[0, 0, {"acc_number": "ATTACKER"}]]},     # create a bank (security)
    {"default_user_ids": [[0, 0, {"login": "attacker"}]]},         # create a user (security)
    {"default_message_follower_ids": [[0, 0, {"partner_id": 9}]]},  # a follower (outbound)
    {"default_child_ids": [[0, 0, {"signup_token": "FORGED"}]]},    # a nested withheld field
])
def test_relaxing_layer_a_did_not_reopen_the_sealed_create_commands(context) -> None:
    # Round four admitted these only to refuse them structurally at Layer A; the guard now
    # decides the same commands against the comodel, so they stay refused -- at Layer B.
    raw = ScriptedSession()
    err, reached, _ = _create(raw, "res.partner", context)
    assert err is True, f"a sealed create command was admitted: {context}"
    assert reached is False


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
