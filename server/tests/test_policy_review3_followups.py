# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Third adversarial round: the call-class backstop resolves paths and values with field
metadata, so it closes the remaining read and write holes without refusing legitimate
business flows.

Each test here pins one finding of that round:

  * a dotted string or a true-leaf domain handed to a value-returning ``call``
    (``mapped``/``filtered``/``sorted``) no longer hops a read into a sealed tier model;
  * ``read_progress_bar``'s bucket field is a checked grouping oracle;
  * a module-specific ``call`` cannot set a withheld field named as a values key;
  * and the backstop no longer refuses an internal note, a customer reply or activity
    feedback whose free text or file name merely reads like a credential.

Plus the regressions the tighter checks had introduced: validation-wizard context keys,
user-assignment many2many links, harmless payment-token relations, and the
``web_name_search`` signature.
"""

from __future__ import annotations

import pytest
from policy_fakes import CHAR, ScriptedSession, call, m2m, m2o, policy, server

from odoo_mcp.policy.loader import load_bytes
from odoo_mcp.policy.model import Policy
from odoo_mcp.registry import registry

# Models the base fakes do not carry.
EXTRA = {
    "project.task": {"name": CHAR, "project_id": m2o("project.project"),
                     "user_ids": m2m("res.users"), "tag_ids": m2m("project.tags")},
    "project.project": {"name": CHAR},
    "project.tags": {"name": CHAR},
    "helpdesk.team": {"name": CHAR, "member_ids": m2m("res.users")},
    "account.payment": {"name": CHAR, "amount": {"type": "monetary"},
                        "suitable_payment_token_ids": m2m("payment.token")},
    "payment.token": {"name": CHAR},
    "mail.activity": {"summary": CHAR, "feedback": {"type": "html"},
                      "user_id": m2o("res.users")},
    "product.product": {"name": CHAR, "qty_available": {"type": "float"}},
    "stock.picking": {"name": CHAR},
    "stock.backorder.confirmation": {"name": CHAR},
    "mrp.production": {"name": CHAR},
}
NOTE = {"subtype_xmlid": "mail.mt_note", "message_type": "comment"}
PDF = "JVBERi0xLjQK"


def raw(**kw):
    return ScriptedSession(fields=EXTRA, **kw)


# --- finding 1 / 9: the dotted-path read-closure hole in the call-class backstop ----------

@pytest.mark.parametrize("method", ["mapped", "filtered", "sorted", "a_new_reader"])
def test_a_call_class_dotted_path_into_a_secrets_model_is_refused(method: str) -> None:
    secret = "PROVIDER-CONFIG-DO-NOT-LEAK"
    raw_s = raw(results={("payment.transaction", method): [secret]})
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute",
                     model="payment.transaction", method=method, ids=[1, 2],
                     args=["provider_id.name"])
    assert err is True
    assert ("payment.transaction", method) not in raw_s.sent()
    assert secret not in text


def test_a_true_leaf_domain_does_not_evade_the_backstop() -> None:
    # (1, '=', 1) is a valid Odoo true leaf; the domain is still a domain, so its
    # ('provider_id.name') leaf is analysed and the hop into the secrets tier refused.
    raw_s = raw()
    err, _ = call(server(raw_s, p=policy("standard")), "odoo_execute",
                  model="payment.transaction", method="count_in_a_new_way",
                  args=[[[1, "=", 1], ["provider_id.name", "!=", False]]])
    assert err is True
    assert ("payment.transaction", "count_in_a_new_way") not in raw_s.sent()


def test_a_benign_dotted_path_into_an_allowed_model_runs() -> None:
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute",
                     model="payment.transaction", method="mapped", ids=[1],
                     args=["partner_id.name"])
    assert err is False, text
    assert ("payment.transaction", "mapped") in raw_s.sent()


# --- finding 2: read_progress_bar's bucket field ------------------------------------------

def test_read_progress_bar_bucket_field_oracle_is_refused() -> None:
    leaked = {"Acme": {"TOKEN-abc-DO-NOT-LEAK": 1}}
    raw_s = raw(results={("res.partner", "read_progress_bar"): leaked})
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="read_progress_bar",
                     args=[[], ["company_id"], {"field": "signup_token", "colors": {}}])
    assert err is True
    assert ("res.partner", "read_progress_bar") not in raw_s.sent()
    assert "DO-NOT-LEAK" not in text


def test_read_progress_bar_benign_bucket_field_runs() -> None:
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="read_progress_bar",
                     args=[[], ["company_id"], {"field": "active", "colors": {}}])
    assert err is False, text
    assert ("res.partner", "read_progress_bar") in raw_s.sent()


# --- finding 3: a withheld field named as a call-class values key --------------------------

def test_a_call_class_verb_cannot_set_a_withheld_field_via_a_vals_key() -> None:
    raw_s = raw()
    err, _ = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                  method="apply_settings", ids=[3],
                  args=[{"signup_token": "KNOWN-ATTACKER-TOKEN"}])
    assert err is True
    assert ("res.partner", "apply_settings") not in raw_s.sent()


def test_a_call_class_verb_cannot_ride_x2many_commands_into_a_tier() -> None:
    raw_s = raw()
    err, _ = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                  method="apply_settings", ids=[3],
                  args=[{"user_ids": [[4, 2]]}])  # a link to res.users (security)
    assert err is True
    assert ("res.partner", "apply_settings") not in raw_s.sent()


# --- finding 4: the backstop leaves free text and file names alone -------------------------

@pytest.mark.parametrize("body", ["Pass", "Secret", "Token", "password"])
def test_an_internal_note_with_a_credential_like_body_runs(body: str) -> None:
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="crm.lead",
                     method="message_post", ids=[1], kwargs={"body": body, **NOTE})
    assert err is False, text
    assert ("crm.lead", "message_post") in raw_s.sent()


@pytest.mark.parametrize("filename", ["Boarding_Pass.pdf", "password_policy.pdf",
                                      "Credentials_SAT.pdf", "token_list.csv"])
def test_an_internal_note_with_a_credential_like_attachment_name_runs(filename: str) -> None:
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="message_post", ids=[3],
                     kwargs={"body": "<p>See file</p>", **NOTE,
                             "attachments": [[filename, PDF]], "subject": "Password"})
    assert err is False, text
    assert ("res.partner", "message_post") in raw_s.sent()


def test_activity_feedback_that_reads_like_a_credential_runs() -> None:
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="mail.activity",
                     method="action_feedback", ids=[3], kwargs={"feedback": "Pass"})
    assert err is False, text
    assert ("mail.activity", "action_feedback") in raw_s.sent()


def test_the_hardened_example_customer_reply_with_a_vat_pdf_runs() -> None:
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "docs" / "policy-examples" / \
        "production-hardened.json"
    hardened = load_bytes(path.read_bytes(), path=str(path), profile="standard",
                          readonly=False, tool_names=[t.name for t in registry.all()])
    assert not hardened.locked, hardened.error
    raw_s = raw()
    err, text = call(server(raw_s, p=hardened), "odoo_execute", model="res.partner",
                     method="message_post", ids=[3],
                     kwargs={"body": "<p>Our VAT certificate</p>", "message_type": "comment",
                             "subtype_xmlid": "mail.mt_comment", "partner_ids": [3],
                             "attachments": [["VAT.pdf", PDF]]})
    assert err is False, text
    assert ("res.partner", "message_post") in raw_s.sent()


# --- finding 5: validation-wizard context keys --------------------------------------------

@pytest.mark.parametrize(("model", "method", "ids", "context"), [
    ("stock.backorder.confirmation", "process", [2], {"button_validate_picking_ids": [1]}),
    ("stock.picking", "button_validate", [1],
     {"skip_backorder": True, "picking_ids_not_to_backorder": [1]}),
    ("stock.picking", "button_validate", [1], {"skip_immediate": True}),
    ("mrp.production", "button_mark_done", [5],
     {"skip_backorder": True, "mo_ids_to_backorder": []}),
])
def test_validation_wizards_run_under_standard(model, method, ids, context) -> None:
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model=model,
                     method=method, ids=ids, kwargs={"context": context})
    assert err is False, text
    assert (model, method) in raw_s.sent()


def test_default_field_accepts_a_list_value() -> None:
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute",
                     model="stock.backorder.confirmation", method="create",
                     args=[{"name": "x"}], kwargs={"context": {"default_pick_ids": [[4, 1]]}})
    assert err is False, text


@pytest.mark.parametrize("context", [{"warehouse": 1}, {"location": 8}])
def test_stock_on_hand_per_warehouse_runs(context) -> None:
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="product.product",
                     method="read", ids=[1], kwargs={"fields": ["qty_available"],
                                                     "context": context})
    assert err is False, text


# --- finding 6: user-assignment many2many links -------------------------------------------

@pytest.mark.parametrize("command", [[[4, 2]], [[6, 0, [2, 6]]], [2]])
def test_assigning_a_user_to_a_task_runs(command) -> None:
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_write", model="project.task",
                     ids=[5], values={"user_ids": command})
    assert err is False, text
    assert ("project.task", "write") in raw_s.sent()


def test_creating_and_importing_an_assigned_task_runs() -> None:
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_create", model="project.task",
                     values={"name": "Rollout", "project_id": 1, "user_ids": [[6, 0, [2]]]})
    assert err is False, text
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_import", model="project.task",
                     fields=["name", "user_ids"], rows=[["Rollout", "Mitchell Admin"]])
    assert err is False, text
    assert ("project.task", "load") in raw_s.sent()


def test_adding_a_helpdesk_team_member_runs() -> None:
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_write", model="helpdesk.team",
                     ids=[1], values={"member_ids": [[4, 6]]})
    assert err is False, text
    assert ("helpdesk.team", "write") in raw_s.sent()


@pytest.mark.parametrize(("model", "field"), [("res.company", "user_ids"),
                                              ("res.users", "groups_id")])
def test_a_privilege_user_link_is_still_refused(model: str, field: str) -> None:
    # A company's users (allowed-companies inverse) and a user's groups DO carry rights,
    # so they stay writes on the security tier and are refused outside 'full'.
    raw_s = raw()
    err, _ = call(server(raw_s, p=policy("standard")), "odoo_write", model=model,
                  ids=[1], values={field: [[4, 2]]})
    assert err is True
    assert (model, "write") not in raw_s.sent()


# --- finding 7: harmless token relations and counts ---------------------------------------

@pytest.mark.parametrize(("model", "name"), [
    ("payment.transaction", "token_id"),
    ("res.partner", "payment_token_count"),
    ("account.payment", "suitable_payment_token_ids"),
    ("account.payment", "payment_token_id"),
])
def test_token_relations_and_counts_are_not_withheld(model: str, name: str) -> None:
    assert not Policy().field_withheld(model, name)


@pytest.mark.parametrize("name", ["access_token", "refresh_token", "signup_token"])
def test_token_value_fields_stay_withheld(name: str) -> None:
    assert Policy().field_withheld("res.partner", name)


# --- finding 8: web_name_search signature -------------------------------------------------

def test_web_name_search_positional_specification_runs() -> None:
    raw_s = raw()
    err, text = call(server(raw_s, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="web_name_search", args=["Acme", {"display_name": {}}])
    assert err is False, text
    assert ("res.partner", "web_name_search") in raw_s.sent()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
