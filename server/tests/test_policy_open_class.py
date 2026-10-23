# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The open class: public ORM readers that were classed ``call``, and the backstop
for the readers that necessarily stay ``call``.

A full inventory of the methods an RPC client can reach through ``execute_kw``
(BaseModel, Model, the web helpers and the common mixins) found three
value-returning, domain-taking readers still in the ``call`` class, so the guard
parsed none of their arguments: ``web_name_search`` (16+), ``read_grouping_sets``
and ``formatted_read_grouping_sets`` (18+ pivot read_group) and
``filtered_domain`` (every series). Their domains and groupby terms are oracles
over a withheld field (design 4.11) and their dotted leaves hop into sealed
comodels (design 6.6). This file:

  * proves each is now a read and each oracle is refused before Odoo, while a
    benign call of the same method still runs (not a blanket refusal);
  * proves the defence in depth for the methods that MUST stay ``call`` (the
    business verbs, and any method no inventory lists): a withheld-field string
    argument, or a domain-shaped argument reaching a tier model, is refused, and
    the result is still redacted -- while an ordinary business verb passes.
"""

from __future__ import annotations

import json

import pytest
from policy_fakes import ScriptedSession, call, policy, server

from odoo_mcp.policy.classify import method_class
from odoo_mcp.policy.model import Policy

# --- Part 1: the three gaps are reads, and their oracles are refused -----------------------

@pytest.mark.parametrize("method", ["web_name_search", "read_grouping_sets",
                                    "formatted_read_grouping_sets", "filtered_domain"])
def test_the_open_class_readers_are_now_reads(method: str) -> None:
    assert method_class(method) == "read"


def test_web_name_search_domain_oracle_on_its_own_model_is_refused() -> None:
    # web_name_search(name, specification, domain=...): the domain is third, so it is
    # passed by name here (a positional domain would be read as the specification).
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                  method="web_name_search", args=[""],
                  kwargs={"domain": [["signup_token", "=like", "A%"]]})
    assert err is True
    assert ("res.partner", "web_name_search") not in raw.sent()


def test_web_name_search_dotted_leaf_into_a_secrets_comodel_is_refused() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="payment.transaction",
                  method="web_name_search", args=[""],
                  kwargs={"domain": [["provider_id.stripe_secret_key", "=like", "sk_%"]]})
    assert err is True
    assert ("payment.transaction", "web_name_search") not in raw.sent()


def test_web_name_search_benign_still_runs() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                  method="web_name_search", args=["Acme"],
                  kwargs={"domain": [["name", "ilike", "Acme"]]})
    assert err is False
    assert ("res.partner", "web_name_search") in raw.sent()


def test_web_name_search_positional_specification_runs() -> None:
    # The web module binds the specification as the SECOND argument, so a positional
    # call of the web client's own signature -- (name, specification[, domain, ...]) --
    # reads the specification, not a domain, and runs (design finding).
    raw = ScriptedSession()
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="web_name_search", args=["Acme", {"display_name": {}}])
    assert err is False, text
    assert ("res.partner", "web_name_search") in raw.sent()


def test_web_name_search_specification_oracle_by_name_is_refused() -> None:
    # the specification (17/18+) is read by name and reads field values, so a withheld
    # key in it is refused the way web_read's specification is.
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                  method="web_name_search", args=["Acme"],
                  kwargs={"specification": {"signup_token": {}}})
    assert err is True
    assert ("res.partner", "web_name_search") not in raw.sent()


@pytest.mark.parametrize("method", ["read_grouping_sets", "formatted_read_grouping_sets"])
def test_read_grouping_sets_domain_oracle_is_refused(method: str) -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="sale.order",
                  method=method,
                  args=[[["access_token", "=like", "A%"]], [["partner_id"]], ["__count"]])
    assert err is True
    assert ("sale.order", method) not in raw.sent()


@pytest.mark.parametrize("method", ["read_grouping_sets", "formatted_read_grouping_sets"])
def test_read_grouping_sets_group_oracle_in_any_set_is_refused(method: str) -> None:
    # grouping by a withheld field leaks it the way read_progress_bar's group_by does,
    # and it is refused whichever grouping set hides it.
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="sale.order",
                  method=method, args=[[], [["partner_id"], ["access_token"]], ["__count"]])
    assert err is True
    assert ("sale.order", method) not in raw.sent()


def test_read_grouping_sets_benign_grouping_runs() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="sale.order",
                  method="read_grouping_sets",
                  args=[[], [["partner_id"], ["state"]], ["__count"]])
    assert err is False
    assert ("sale.order", "read_grouping_sets") in raw.sent()


def test_filtered_domain_oracle_over_held_records_is_refused() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                  method="filtered_domain", ids=[3, 7, 8],
                  args=[[["signup_token", "=like", "A%"]]])
    assert err is True
    assert ("res.partner", "filtered_domain") not in raw.sent()


def test_filtered_domain_benign_filter_runs() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                  method="filtered_domain", ids=[3, 7, 8], args=[[["name", "=", "Acme"]]])
    assert err is False
    assert ("res.partner", "filtered_domain") in raw.sent()


def test_full_profile_leaves_the_new_readers_untouched() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=Policy(profile_name="full")), "odoo_execute",
                  model="res.partner", method="web_name_search",
                  args=[""], kwargs={"domain": [["signup_token", "=like", "A%"]]})
    assert err is False
    assert ("res.partner", "web_name_search") in raw.sent()


# --- Part 2: the backstop for the methods that stay "call" ---------------------------------

def test_an_unlisted_reader_cannot_use_a_withheld_field_list() -> None:
    # a method no inventory classifies, carrying a field list that names a credential.
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                  method="read_some_new_way", args=[["signup_token"]])
    assert err is True
    assert ("res.partner", "read_some_new_way") not in raw.sent()


def test_an_unlisted_reader_cannot_group_by_a_withheld_field() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="sale.order",
                  method="pivot_in_a_new_way", kwargs={"groupby": "access_token"})
    assert err is True
    assert ("sale.order", "pivot_in_a_new_way") not in raw.sent()


def test_an_unlisted_reader_cannot_filter_on_a_withheld_leaf() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="sale.order",
                  method="count_in_a_new_way", args=[[["access_token", "=like", "A%"]]])
    assert err is True
    assert ("sale.order", "count_in_a_new_way") not in raw.sent()


def test_an_unlisted_reader_cannot_hop_a_domain_into_a_secrets_comodel() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="payment.transaction",
                  method="count_in_a_new_way",
                  args=[[["provider_id.stripe_secret_key", "=like", "sk_%"]]])
    assert err is True
    assert ("payment.transaction", "count_in_a_new_way") not in raw.sent()


def test_a_withheld_name_nested_deep_in_the_arguments_is_refused() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                  method="do_a_thing", kwargs={"options": {"fields": ["name", "signup_token"]}})
    assert err is True
    assert ("res.partner", "do_a_thing") not in raw.sent()


@pytest.mark.parametrize(("model", "method", "extra"), [
    ("sale.order", "action_confirm", {"ids": [1]}),
    ("account.move", "action_post", {"ids": [7]}),
    ("sale.order", "button_cancel", {"ids": [1], "kwargs": {"context": {"lang": "en_US"}}}),
])
def test_business_verbs_still_run_under_standard(model: str, method: str, extra: dict) -> None:
    raw = ScriptedSession()
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model=model,
                     method=method, **extra)
    assert err is False, text
    assert (model, method) in raw.sent()


def test_a_business_verb_with_a_plain_string_argument_runs() -> None:
    # 'draft' is not a field name, so a business verb that takes it as a plain argument
    # is not refused: only an argument that is, or names through a path, a withheld field
    # now stops a call.
    raw = ScriptedSession()
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="sale.order",
                     method="action_set_state", args=["draft"])
    assert err is False, text
    assert ("sale.order", "action_set_state") in raw.sent()


def test_a_domain_value_is_not_mistaken_for_a_field_name() -> None:
    # the value a domain term compares against ('signup_token' here as a literal) is not
    # a field reference, so a search for records whose name equals it is allowed.
    raw = ScriptedSession()
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="find_in_a_new_way", args=[[["name", "=", "signup_token"]]])
    assert err is False, text
    assert ("res.partner", "find_in_a_new_way") in raw.sent()


def test_full_profile_leaves_a_call_class_reader_untouched() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=Policy(profile_name="full")), "odoo_execute",
                  model="res.partner", method="read_some_new_way", args=[["signup_token"]])
    assert err is False
    assert ("res.partner", "read_some_new_way") in raw.sent()


def test_a_call_class_result_is_redacted_at_any_depth() -> None:
    # 2(a): the result backstop covers a dict, a list of dicts, and nested dicts.
    secret = "PAC-PASSWORD-nested-DO-NOT-LEAK"
    raw = ScriptedSession(results={("res.company", "summarise"): {
        "label": "Acme", "rows": [{"name": "A", "l10n_mx_edi_pac_password": secret}]}})
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="res.company",
                     method="summarise")
    assert err is False, text
    assert secret not in text
    payload = json.loads(text)
    assert payload["result"]["rows"] == [{"name": "A"}]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
