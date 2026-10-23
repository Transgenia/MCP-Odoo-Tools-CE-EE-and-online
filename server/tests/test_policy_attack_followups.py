# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Second-round (adversarial) review fixes, each proven here.

A first review round reported zero security findings; a later pass found a real
bypass (BaseModel.update classified as a plain call, fixed in 87ef352). This
file holds the regression tests for the same class of defect found afterwards:

  * untiered bulk engines reachable as plain models through odoo_execute
    (base_import.import, base.language.*): now in the customization tier, so the
    generic door is closed while the import tools keep theirs (decide_internal);
  * value- or domain-bearing methods left in the "call" class (search_fetch,
    fetch, read_progress_bar, search_panel_*), so their domains escaped the 4.11
    and 6.6 checks and their results escaped redaction: now reads;
  * the ir.attachment value rules bypassed by writing through a delegating child
    (product.document): now keyed off the delegation parents too;
  * redaction gated on the read class, so onchange leaked a withheld value, and
    nested model-specific withholds dropped at depth: redaction is a backstop on
    every result but inspect, and resolves the nested model on demand.
"""

from __future__ import annotations

import pytest
from policy_fakes import CHAR, ScriptedSession, call, m2o, o2m, policy, server

from odoo_mcp.policy.classify import method_class
from odoo_mcp.policy.model import Policy

# --- Finding 1: base_import.import / base.language.* are untiered engines -------------


def test_base_import_import_is_closed_to_the_generic_execute_under_standard() -> None:
    p = policy("standard")
    # the generic door (odoo_execute) is shut: base_import.import is customization
    assert not p.decide("create", "base_import.import").allowed
    assert not p.decide("call", "base_import.import", "execute_import").allowed
    assert not p.decide("call", "base.language.install", "lang_install").allowed
    assert not p.decide("call", "base.language.import", "import_lang").allowed
    # ... while the import tools reach it through registry.Internal (decide_internal),
    # which the tiers do not gate, so odoo_import / odoo_import_preview still work.
    assert p.decide_internal("create", "base_import.import").allowed
    assert p.decide_internal("call", "base_import.import", "execute_import").allowed


def _import_session() -> ScriptedSession:
    return ScriptedSession(fields={"base_import.import": {
        "res_model": CHAR, "file": CHAR, "file_type": CHAR, "file_name": CHAR}})


def test_execute_import_pointed_at_res_users_is_refused_end_to_end() -> None:
    raw = _import_session()
    err, _text = call(server(raw, p=policy("standard")), "odoo_execute",
                      model="base_import.import", method="execute_import", ids=[55],
                      args=[["login", "password"], ["login", "password"], {"has_headers": True}])
    assert err is True
    assert ("base_import.import", "execute_import") not in raw.sent()


def test_creating_an_import_record_on_a_business_model_name_is_refused() -> None:
    raw = _import_session()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute",
                  model="base_import.import", method="create",
                  args=[{"res_model": "res.users", "file": "x", "file_type": "text/csv"}])
    assert err is True
    assert raw.sent() == []


def test_the_sanctioned_load_engine_on_res_users_is_still_refused() -> None:
    # control: the classified engine load() on a security model is refused too, which
    # is exactly what made base_import.import a second, unguarded door to it.
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="res.users",
                  method="load", args=[["login"], [["mallory"]]])
    assert err is True
    assert raw.sent() == []


# --- Findings 2 & 3: read-shaped methods were "call" ---------------------------------


@pytest.mark.parametrize("method", ["search_fetch", "fetch", "read_progress_bar",
                                    "search_panel_select_range",
                                    "search_panel_select_multi_range"])
def test_the_fallen_through_readers_are_now_reads(method: str) -> None:
    assert method_class(method) == "read"


def test_search_fetch_withheld_oracle_is_refused_like_search_read() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                  method="search_fetch", args=[[["signup_token", "=like", "A%"]], ["id"]])
    assert err is True and raw.sent() == []


def test_search_fetch_domain_into_a_secrets_model_is_refused() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="payment.transaction",
                  method="search_fetch",
                  args=[[["provider_id.stripe_secret_key", "=like", "sk_%"]], ["id"]])
    assert err is True and raw.sent() == []


def test_fetch_of_a_withheld_field_is_refused() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                  method="fetch", ids=[3], args=[["signup_token"]])
    assert err is True and raw.sent() == []


def test_read_progress_bar_group_by_a_withheld_field_is_refused() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="sale.order",
                  method="read_progress_bar", args=[[], "access_token", {}])
    assert err is True and raw.sent() == []


def test_search_panel_enumerating_a_secrets_tier_comodel_is_refused() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="payment.transaction",
                  method="search_panel_select_multi_range", args=["provider_id"])
    assert err is True
    assert ("payment.transaction", "search_panel_select_multi_range") not in raw.sent()


def test_search_panel_on_a_readable_comodel_is_allowed() -> None:
    # partner_id -> res.partner (readable), so the panel read runs: the fix refuses
    # only a hop into a sealed model, not every search_panel call.
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_execute", model="payment.transaction",
                  method="search_panel_select_multi_range", args=["partner_id"])
    assert err is False
    assert ("payment.transaction", "search_panel_select_multi_range") in raw.sent()


# --- reads-1: a call-class result leaked a withheld value ----------------------------


def test_onchange_result_is_redacted_like_copy_data() -> None:
    secret = "PAC-PASSWORD-DO-NOT-LEAK-onchange"
    raw = ScriptedSession(results={("res.company", "onchange"): {
        "value": {"name": "Acme", "l10n_mx_edi_pac_password": secret}}})
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="res.company",
                     method="onchange", args=[[1], {}, [], {}])
    assert err is False, text
    assert secret not in text
    assert "res.company.l10n_mx_edi_pac_password" in text  # policy_withheld_fields


def test_a_plain_call_result_is_a_backstop_for_withheld_names() -> None:
    # a method Odoo may add later, class "call": its result is still redacted.
    secret = "SIGNUP-TOKEN-from-a-call-method"
    raw = ScriptedSession(results={("res.partner", "some_future_reader"): [
        {"id": 1, "name": "Acme", "signup_token": secret}]})
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="res.partner",
                     method="some_future_reader", args=[])
    assert err is False, text
    assert secret not in text


# --- reads-2: model-specific withhold dropped at depth -------------------------------

_DEPT = {"hr.department": {"name": CHAR, "member_ids": o2m("hr.employee", "department_id")}}


def test_nested_copy_data_honours_a_model_specific_withhold() -> None:
    priv = "PRIVATE-EMAIL-ceo-DO-NOT-LEAK"
    raw = ScriptedSession(fields=_DEPT, results={("hr.department", "copy_data"): [
        {"name": "Board", "member_ids": [[0, 0, {"name": "CEO", "private_email": priv}]]}]})
    p = policy("standard", fields={"withhold": ["hr.employee.private_email"]})
    err, text = call(server(raw, p=p), "odoo_execute", model="hr.department", method="copy_data")
    assert err is False, text
    assert priv not in text


def test_top_level_copy_data_also_honours_it() -> None:
    priv = "PRIVATE-EMAIL-ceo-top-level"
    raw = ScriptedSession(results={("hr.employee", "copy_data"): [
        {"name": "CEO", "private_email": priv}]})
    p = policy("standard", fields={"withhold": ["hr.employee.private_email"]})
    err, text = call(server(raw, p=p), "odoo_execute", model="hr.employee", method="copy_data")
    assert err is False, text
    assert priv not in text


def test_a_default_credential_name_is_redacted_at_depth() -> None:
    tok = "SIGNUP-TOKEN-nested-DO-NOT-LEAK"
    fields = {"my.parent": {"name": CHAR, "line_ids": o2m("my.child", "parent_id")},
              "my.child": {"name": CHAR, "signup_token": CHAR}}
    raw = ScriptedSession(fields=fields, results={("my.parent", "copy_data"): [
        {"name": "P", "line_ids": [[0, 0, {"name": "C", "signup_token": tok}]]}]})
    err, text = call(server(raw, p=policy("standard")), "odoo_execute", model="my.parent",
                     method="copy_data")
    assert err is False, text
    assert tok not in text


# --- Finding 4: ir.attachment value rules bypassed via a delegate --------------------

_PRODUCT_DOCUMENT = {"product.document": {
    "name": CHAR, "ir_attachment_id": m2o("ir.attachment"),
    "public": {"type": "boolean"}, "datas": {"type": "binary"}, "res_field": CHAR}}


def test_a_public_attachment_cannot_be_created_through_a_delegate() -> None:
    raw = ScriptedSession(fields=_PRODUCT_DOCUMENT)
    err, _ = call(server(raw, p=policy("standard")), "odoo_create", model="product.document",
                  values={"name": "x", "public": True, "datas": "Qk9PTQ=="})
    assert err is True and raw.sent() == []


def test_an_existing_delegate_attachment_cannot_be_flipped_public() -> None:
    raw = ScriptedSession(fields=_PRODUCT_DOCUMENT)
    err, _ = call(server(raw, p=policy("standard")), "odoo_write", model="product.document",
                  ids=[1], values={"public": True})
    assert err is True and raw.sent() == []


def test_a_private_delegate_document_still_writes() -> None:
    # control: the rule blocks public/res_field, not every write through the delegate.
    raw = ScriptedSession(fields=_PRODUCT_DOCUMENT)
    err, _ = call(server(raw, p=policy("standard")), "odoo_create", model="product.document",
                  values={"name": "x", "datas": "Qk9PTQ=="})
    assert err is False
    assert ("product.document", "create") in raw.sent()


def test_the_direct_public_attachment_create_is_still_refused() -> None:
    raw = ScriptedSession()
    err, _ = call(server(raw, p=policy("standard")), "odoo_create", model="ir.attachment",
                  values={"name": "x", "public": True})
    assert err is True and raw.sent() == []


# --- inspect results are never redacted (the fields_get definitions stay) ------------


def test_fields_get_keeps_the_definition_of_a_withheld_field() -> None:
    # redaction is a result backstop, but fields_get returns DEFINITIONS keyed by
    # field name: a withheld field's definition must still be listed.
    raw = ScriptedSession()
    err, text = call(server(raw, p=policy("standard")), "odoo_fields_get", model="res.company")
    assert err is False, text
    assert "l10n_mx_edi_pac_password" in text
    assert "policy_withheld_fields" not in text


def test_full_profile_leaves_the_new_readers_untouched() -> None:
    # under full the rules are off: a search_fetch domain on a withheld field runs.
    raw = ScriptedSession()
    err, _ = call(server(raw, p=Policy(profile_name="full")), "odoo_execute",
                  model="res.partner", method="search_fetch",
                  args=[[["signup_token", "=like", "A%"]], ["id"]])
    assert err is False
    assert ("res.partner", "search_fetch") in raw.sent()
