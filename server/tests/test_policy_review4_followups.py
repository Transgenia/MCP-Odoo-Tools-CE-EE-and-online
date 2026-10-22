# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Fourth adversarial round: the context-default channel, the grouped-term oracle, and
the false refusals the round-three checks had introduced.

Each test pins one finding of that round:

  * a ``default_<x2many>`` context key can no longer carry a create/write/delete command,
    or nested values, into a sensitive tier (the same payload in ``values`` is refused).
    Since round seven every list or object in a ``default_<field>`` is refused at Layer A
    (``test_policy_review7_followups.py``), so the tests below pin that, and the wizard
    and business-link flows pass their lists in values;
  * the call-class backstop strips a ``:function`` aggregate suffix, so a withheld field
    carried as a grouped term is refused;
  * ``onchange`` (a write-nothing simulation) runs with the record's existing lines;
  * an internal note's ``(name, content, info)`` attachment runs when the file name reads
    like a credential;
  * invoice posting runs with the web client's ``validate_analytic`` context key;
  * ``read_progress_bar``'s value-keyed result is not over-redacted;
  * the ``search_panel_*`` readers accept the trailing options a series adds; and
  * the ``ir.attachment`` pin covers ``search_fetch``, ``read_progress_bar`` and the
    ``search_panel_*`` readers.
"""

from __future__ import annotations

import json

import pytest
from policy_fakes import CHAR, ScriptedSession, call, m2o, o2m, policy, server

from odoo_mcp.policy.model import Policy

# Models the base fakes do not carry.
EXTRA = {
    "stock.backorder.confirmation": {"name": CHAR, "pick_ids": o2m("stock.picking", "backorder_id")},
    "stock.picking": {"name": CHAR},
    "quality.check": {"name": CHAR, "team_id": m2o("quality.alert.team"),
                      "quality_state": {"type": "selection"}},
    "quality.alert.team": {"name": CHAR},
}
NOTE = {"subtype_xmlid": "mail.mt_note", "message_type": "comment"}


def raw(**kw):
    return ScriptedSession(fields=EXTRA, **kw)


# --- findings 1 / 3 / 10 (blockers): default_<x2many> context smuggling --------------------

def _create(raw_s, values):
    err, _text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                      method="create", args=[values])
    return err, ("res.partner", "create") in raw_s.sent()


@pytest.mark.parametrize("values", [
    {"name": "x", "bank_ids": [[0, 0, {"acc_number": "A"}]]},
    {"name": "x", "user_ids": [[0, 0, {"login": "a"}]]},
    {"name": "x", "message_follower_ids": [[0, 0, {"partner_id": 9}]]},
    {"name": "x", "child_ids": [[0, 0, {"signup_token": "T"}]]},
])
def test_the_explicit_values_route_is_sealed(values: dict) -> None:
    err, sent = _create(raw(), values)
    assert err is True and sent is False


@pytest.mark.parametrize("context", [
    {"default_bank_ids": [[1, 5, {"acc_number": "ATTACKER-CLABE"}]]},   # write a vendor bank
    {"default_bank_ids": [[0, 0, {"acc_number": "ATTACKER-CLABE"}]]},   # create a bank (security)
    {"default_user_ids": [[0, 0, {"login": "attacker"}]]},             # create a user (security)
    {"default_message_follower_ids": [[0, 0, {"partner_id": 9}]]},     # a follower (outbound)
    {"default_child_ids": [[0, 0, {"signup_token": "FORGED"}]]},       # a withheld field
])
def test_a_context_default_command_is_refused_at_layer_a(context) -> None:
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="create", args=[{"name": "x"}], kwargs={"context": context})
    assert err is True, f"the policy allowed a sealed write via {context}"
    assert "rule context" in text and "Nothing was sent to Odoo." in text, text
    assert raw_s.calls == [], f"the call went past Layer A carrying {context}"


def test_a_link_only_wizard_default_is_refused_and_its_values_form_runs() -> None:
    # default_pick_ids: [(4, id)] is a list, refused at Layer A whatever it links; the
    # wizard created with its pickings in values runs, the link decided against the comodel.
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute",
                     model="stock.backorder.confirmation", method="create",
                     args=[{"name": "x"}], kwargs={"context": {"default_pick_ids": [[4, 1]]}})
    assert err is True and "rule context" in text and raw_s.calls == []
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute",
                     model="stock.backorder.confirmation", method="create",
                     args=[{"pick_ids": [[4, 1]]}])
    assert err is False, text
    assert ("stock.backorder.confirmation", "create") in raw_s.sent()


def test_a_context_default_link_into_a_tier_is_refused_before_any_lookup() -> None:
    # default_user_ids: [(4, 2)] would re-parent a user (security tier). It is refused at
    # Layer A as a list, before the comodel is looked up: no fields_get, nothing sent.
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="create", args=[{"name": "x"}],
                     kwargs={"context": {"default_user_ids": [[4, 2]]}})
    assert err is True and "rule context" in text
    assert raw_s.calls == [] and raw_s.metadata == []


def test_a_benign_many2many_link_runs_in_values_not_in_the_context() -> None:
    # default_category_id: a SET of a business comodel (res.partner.category) is still a
    # list in the context, so it is refused there; in values it is checked and runs.
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="create", args=[{"name": "x"}],
                     kwargs={"context": {"default_category_id": [[6, 0, [1, 2]]]}})
    assert err is True and "rule context" in text and raw_s.calls == []
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="create", args=[{"name": "x", "category_id": [[6, 0, [1, 2]]]}])
    assert err is False, text
    assert ("res.partner", "create") in raw_s.sent()


# --- finding 2 (major): the field:function term form in the call-class backstop ------------

def test_a_bare_withheld_term_is_refused_baseline() -> None:
    raw_s = ScriptedSession(results={("res.partner", "pivot"): {}})
    err, _ = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                  method="pivot", args=["signup_token"])
    assert err is True
    assert ("res.partner", "pivot") not in raw_s.sent()


@pytest.mark.parametrize("term", ["signup_token:count", "signup_token:month",
                                  "name:max(signup_token)"])
def test_a_withheld_field_carried_as_a_grouped_term_is_refused(term: str) -> None:
    raw_s = ScriptedSession(results={("res.partner", "pivot"): {"TOKEN-A": 3}})
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="pivot", args=[term])
    assert err is True, f"the backstop passed a withheld-field grouped term {term!r}"
    assert "TOKEN-A" not in text
    assert ("res.partner", "pivot") not in raw_s.sent()


def test_a_benign_grouped_term_runs() -> None:
    raw_s = ScriptedSession(results={("res.partner", "pivot"): {}})
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="pivot", args=["country_id:count"])
    assert err is False, text
    assert ("res.partner", "pivot") in raw_s.sent()


# --- finding 4 (major): onchange, a write-nothing simulation -------------------------------

ONCHANGE_RESULT = {"value": {"amount_total": 115.0}, "warning": False}


@pytest.mark.parametrize("values", [
    {"partner_id": 3, "order_line": [[6, False, [12, 13]]]},   # set existing lines
    {"partner_id": 3, "order_line": [12, 13]},                 # a bare id list
    {"order_line": [[5], [0, 0, {"product_id": 5}]]},          # clear then add
    {"order_line": [[2, 12], [4, 13]]},                        # remove and link
])
def test_onchange_preview_of_a_quotation_with_lines_runs(values: dict) -> None:
    raw_s = ScriptedSession(results={("sale.order", "onchange"): ONCHANGE_RESULT})
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="sale.order",
                     method="onchange", ids=[],
                     args=[values, ["partner_id"], {"partner_id": {}, "order_line": {}}])
    assert err is False, text
    assert ("sale.order", "onchange") in raw_s.sent()


def test_onchange_of_a_contact_form_with_chatter_fields_runs() -> None:
    raw_s = ScriptedSession(results={("res.partner", "onchange"): ONCHANGE_RESULT})
    values = {"name": "Acme", "child_ids": [[6, False, [8]]],
              "message_follower_ids": [[6, False, [1]]]}
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="onchange", ids=[3],
                     args=[values, "name", {"name": "1", "child_ids": "", "message_follower_ids": ""}])
    assert err is False, text
    assert ("res.partner", "onchange") in raw_s.sent()


def test_the_same_commands_on_a_real_write_are_still_refused() -> None:
    raw_s = ScriptedSession()
    err, _ = call(server(raw_s, p=policy("standard")), "odoo_write", model="sale.order",
                  ids=[1], values={"order_line": [[6, False, [12, 13]]]})
    assert err is True
    assert ("sale.order", "write") not in raw_s.sent()


# --- finding 5 (major): the (name, content, info) attachment tuple -------------------------

@pytest.mark.parametrize("filename", ["password_policy.pdf", "token_list.csv",
                                      "Credentials_SAT.pdf", "client_secret.json"])
@pytest.mark.parametrize("info", [{}, None])
def test_an_internal_note_with_a_three_element_attachment_runs(filename: str, info) -> None:
    raw_s = ScriptedSession()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="message_post", ids=[3],
                     kwargs={"body": "<p>See file</p>", **NOTE,
                             "attachments": [[filename, "plain text", info]]})
    assert err is False, text
    assert ("res.partner", "message_post") in raw_s.sent()


def test_a_real_domain_shaped_argument_is_still_analysed() -> None:
    # a genuine domain (middle element a recognised operator) still routes through the
    # read-path analysis, so a hop into a secrets-tier comodel is refused.
    raw_s = ScriptedSession()
    err, _ = call(server(raw_s, p=policy("standard")), "odoo_execute", model="payment.transaction",
                  method="count_in_a_new_way",
                  args=[[["provider_id.stripe_secret_key", "=like", "sk_%"]]])
    assert err is True
    assert ("payment.transaction", "count_in_a_new_way") not in raw_s.sent()


# --- finding 6 (major): the invoice-post validate_analytic context key ---------------------

def test_invoice_post_with_validate_analytic_runs() -> None:
    raw_s = ScriptedSession(results={("account.move", "action_post"): True})
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="account.move",
                     method="action_post", ids=[7],
                     kwargs={"context": {"validate_analytic": True}})
    assert err is False, text
    assert ("account.move", "action_post") in raw_s.sent()


# --- finding 7 (minor): read_progress_bar result redaction ---------------------------------

@pytest.mark.parametrize("stage", ["Pass", "Secret", "Token", "Credentials"])
def test_a_progress_bar_column_named_like_a_credential_is_kept(stage: str) -> None:
    counts = {"New": {"planned": 2, "overdue": 1}, stage: {"planned": 4, "overdue": 0}}
    raw_s = raw(results={("crm.lead", "read_progress_bar"): counts})
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="crm.lead",
                     method="read_progress_bar",
                     kwargs={"domain": [], "group_by": "stage_id",
                             "progress_bar": {"field": "name", "colors": {}}})
    assert err is False, text
    assert json.loads(text)["result"] == counts


def test_a_progress_bar_bucket_value_that_reads_like_a_credential_is_kept() -> None:
    counts = {"Line 1": {"pass": 7, "fail": 1}, "Line 2": {"pass": 3, "fail": 0}}
    raw_s = raw(results={("quality.check", "read_progress_bar"): counts})
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="quality.check",
                     method="read_progress_bar",
                     kwargs={"domain": [], "group_by": "team_id",
                             "progress_bar": {"field": "quality_state",
                                              "colors": {"pass": "success"}}})
    assert err is False, text
    assert json.loads(text)["result"] == counts


# --- finding 8 (minor): the search_panel / read_progress_bar web-client kwargs -------------

RANGE_KW = {"category_domain": [], "enable_counters": False, "expand": False,
            "filter_domain": [], "limit": 200, "search_domain": []}
MULTI_KW = {"category_domain": [], "comodel_domain": [], "enable_counters": False,
            "expand": False, "filter_domain": [], "limit": 200, "search_domain": []}


def test_search_panel_category_with_hierarchize_runs() -> None:
    raw_s = ScriptedSession(results={("res.partner", "search_panel_select_range"): {"values": []}})
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="search_panel_select_range", args=["parent_id"],
                     kwargs={**RANGE_KW, "hierarchize": True})
    assert err is False, text
    assert ("res.partner", "search_panel_select_range") in raw_s.sent()


@pytest.mark.parametrize("extra", [{"group_domain": {}}, {"group_by": "parent_id",
                                                          "group_domain": {}}])
def test_search_panel_multi_range_with_group_options_runs(extra: dict) -> None:
    raw_s = ScriptedSession(
        results={("res.partner", "search_panel_select_multi_range"): {"values": []}})
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="search_panel_select_multi_range", args=["category_id"],
                     kwargs={**MULTI_KW, **extra})
    assert err is False, text
    assert ("res.partner", "search_panel_select_multi_range") in raw_s.sent()


def test_read_progress_bar_without_a_sum_field_runs() -> None:
    raw_s = ScriptedSession(results={("res.partner", "read_progress_bar"): {}})
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="read_progress_bar",
                     kwargs={"domain": [], "group_by": "country_id",
                             "progress_bar": {"field": "active", "colors": {"True": "success"},
                                              "sum_field": False}})
    assert err is False, text
    assert ("res.partner", "read_progress_bar") in raw_s.sent()


# --- finding 10 (major): the ir.attachment pin for the reader class ------------------------

SEALED = [["res_field", "!=", False], ["res_model", "=", "certificate.key"]]


def test_search_read_on_a_sealed_attachment_field_is_pinned_control() -> None:
    raw_s = ScriptedSession(results={("ir.attachment", "search_read"): [{"id": 5}]})
    err, _ = call(server(raw_s, p=policy("standard")), "odoo_execute", model="ir.attachment",
                  method="search_read", args=[SEALED, ["id"]])
    assert err is True
    assert ("ir.attachment", "search_read") not in raw_s.sent()


@pytest.mark.parametrize(("method", "args"), [
    ("search_fetch", [SEALED, ["id"]]),
    ("read_progress_bar", [[["res_field", "!=", False]], "res_model", {"field": "res_model"}]),
    ("search_panel_select_range", ["res_id"]),
    ("search_panel_select_multi_range", ["res_id"]),
])
def test_a_reader_on_ir_attachment_must_also_be_pinned(method: str, args: list) -> None:
    raw_s = ScriptedSession(results={("ir.attachment", method): [5]})
    err, _ = call(server(raw_s, p=policy("standard")), "odoo_execute", model="ir.attachment",
                  method=method, args=args)
    assert err is True, f"{method} on ir.attachment bypassed the 4.5 pin"
    assert ("ir.attachment", method) not in raw_s.sent()


def test_a_pinned_search_fetch_on_ir_attachment_runs() -> None:
    # naming a readable parent and no res_field leaf: the search runs, with res_field=False
    # prepended by the guard.
    raw_s = ScriptedSession(results={("ir.attachment", "search_fetch"): [6]})
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="ir.attachment",
                     method="search_fetch", args=[[["res_model", "=", "res.partner"]], ["id"]])
    assert err is False, text
    assert ("ir.attachment", "search_fetch") in raw_s.sent()


# --- the full profile leaves all of this untouched -----------------------------------------

def test_full_profile_leaves_the_context_channel_untouched() -> None:
    raw_s = raw()
    err, _ = call(server(raw_s, p=Policy(profile_name="full")), "odoo_execute",
                  model="res.partner", method="create", args=[{"name": "x"}],
                  kwargs={"context": {"default_bank_ids": [[0, 0, {"acc_number": "A"}]]}})
    assert err is False
    assert ("res.partner", "create") in raw_s.sent()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
