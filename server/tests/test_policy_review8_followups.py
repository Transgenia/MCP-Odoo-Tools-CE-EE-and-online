# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Eighth round: the two residuals left after the context-default channel was closed by
construction (``test_policy_review7_followups.py``).

  * Residual 1 (major): a PLAIN (scalar) ``default_<field>`` rode a nested create to Odoo
    past the delegation-link (4.4) and ir.attachment create (4.5) rules, because those
    structural checks run only against the model the call names. Odoo applies a context
    default to every record the call creates, the nested lines of other models included, so
    ``default_ir_attachment_id`` or ``default_public`` riding an x2many ``(0, 0, vals)`` on
    a write or create of ``product.template`` / ``res.partner`` reached Odoo. Closed by
    construction: under the sealed profiles, a plain ``default_<field>`` whose field is a
    sensitive delegation link or an ir.attachment visibility/binding field
    (``STRUCTURAL_DEFAULT_FIELDS``, derived from ``DELEGATES`` and ``TIERS``) is refused at
    Layer A on a call that can create, with rule ``context``. ``default_res_model`` and
    ``default_res_id`` stay allowed (activity and composer flows pass them; the nested
    attachment they can still bind is an accepted, documented limit).

  * Residual 2 (minor): a context nested in ``onchange``'s ``fields_spec`` (Odoo 17+) was
    not collected, so a list default hidden there was not refused, contradicting
    docs/policy.md. ``onchange``'s specification is now collected (by name and positionally),
    so the same non-scalar rule refuses it.

The remedy is unchanged: pass the value in the record's values, where it is checked, or use
profile ``full``. A read leaves a plain structural default inert; ``full`` is unchanged.
"""

from __future__ import annotations

from typing import Any

import pytest
from policy_fakes import (
    CHAR,
    ScriptedSession,
    call,
    guarded,
    m2o,
    o2m,
    policy,
    refused,
    server,
)

from odoo_mcp.errors import PolicyDenied
from odoo_mcp.policy.check import (
    _STRUCTURAL_DEFAULT_OPS,
    STRUCTURAL_DEFAULT_FIELDS,
    check_context,
)
from odoo_mcp.policy.model import Policy
from odoo_mcp.policy.tiers import ATTACHMENT_STRUCTURAL_FIELDS, DELEGATES

MARKER = "DO-NOT-ECHO-7F3"  # a value no refusal, result or audit line may carry
DOC_LINE = {"product_document_ids": [[0, 0, {"name": "spec"}]]}  # creates a product.document
ATT_LINE = {"x_attachment_ids": [[0, 0, {"name": "a.txt"}]]}     # creates an ir.attachment
STRUCT_HINT = ("context key '{key}' sets a field that binds or exposes a related record")


def _execute(raw: ScriptedSession, model: str, method: str, *, p: Policy | None = None,
             **arguments: Any) -> tuple[bool, str]:
    """odoo_execute through the full server route (Layer A, then the guard)."""
    return call(server(raw, p=p or policy("standard")), "odoo_execute", model=model,
                method=method, **arguments)


def _stopped_at_layer_a(raw: ScriptedSession, err: bool, text: str, key: str) -> None:
    assert err is True, f"the call ran: {text[:200]}"
    assert "rule context)" in text and "Nothing was sent to Odoo." in text, text
    assert STRUCT_HINT.format(key=key) in text, text
    assert raw.calls == [] and raw.metadata == [], "the call went past Layer A"


# --- residual 1: the verifiers' reproductions ----------------------------------------------

@pytest.mark.parametrize(("model", "method", "arguments", "key", "value"), [
    ("product.template", "write", {"ids": [1], "args": [DOC_LINE]}, "default_ir_attachment_id", 5),
    ("product.template", "create", {"args": [{"name": "T", **DOC_LINE}]},
     "default_ir_attachment_id", 5),
    ("res.partner", "write", {"ids": [3], "args": [ATT_LINE]}, "default_public", True),
    ("res.partner", "create", {"args": [{"name": "P", **ATT_LINE}]}, "default_public", True),
    ("res.partner", "create", {"args": [{"name": "P", **ATT_LINE}]}, "default_res_field", "datas"),
])
def test_a_scalar_structural_default_riding_a_nested_create_stops_at_layer_a(
        model: str, method: str, arguments: dict[str, Any], key: str, value: Any) -> None:
    # The write/create builds a nested product.document / ir.attachment line with
    # (0, 0, vals); Odoo creates it with the call's context, so the scalar default would
    # re-point or expose that nested record. It must stop at Layer A, nothing sent.
    raw = ScriptedSession()
    err, text = _execute(raw, model, method, kwargs={"context": {key: value}}, **arguments)
    _stopped_at_layer_a(raw, err, text, key)


# --- residual 1: every structural field name, on every creating class ----------------------

@pytest.mark.parametrize("name", sorted(STRUCTURAL_DEFAULT_FIELDS))
@pytest.mark.parametrize("method", ["create", "write", "action_confirm"])
@pytest.mark.parametrize("profile", ["readonly", "standard", "builder"])
def test_every_structural_field_is_refused_as_a_default_on_a_creating_call(
        profile: str, method: str, name: str) -> None:
    opened = policy(profile, {"res.partner": {"read": True, "create": True, "write": True,
                                              "call": True}})
    rest: dict[str, Any] = {"create": {"args": [{"name": "x"}]},
                            "write": {"ids": [3], "args": [{"name": "x"}]},
                            "action_confirm": {"ids": [3]}}[method]
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", method, p=opened,
                         kwargs={"context": {f"default_{name}": 5}}, **rest)
    _stopped_at_layer_a(raw, err, text, f"default_{name}")


def test_a_delegation_link_default_of_a_website_page_is_refused() -> None:
    # website.page delegates to ir.ui.view (customization tier) through view_id. Under
    # builder, where the create itself is allowed, the default_view_id is the refusal that
    # fires (under standard the create is already refused by the customization tier).
    raw = ScriptedSession()
    err, text = _execute(raw, "website.page", "create", p=policy("builder"),
                         args=[{"name": "x"}], kwargs={"context": {"default_view_id": 9}})
    _stopped_at_layer_a(raw, err, text, "default_view_id")


def test_the_refusal_names_the_key_and_the_remedy_never_the_value() -> None:
    raw = ScriptedSession()
    hint = ("context key 'default_ir_attachment_id' sets a field that binds or exposes a "
            "related record (a delegation link, or an attachment's visibility or binding), and "
            "Odoo applies a context default to every record the call creates, including nested "
            "records of other models, so it cannot be checked against the model this call "
            "names; pass the value in the record's values, where it is checked, or use profile "
            "'full' (the user sets it in the plugin option 'Permission profile')")
    err, text = _execute(raw, "product.document", "create",
                         args=[{"name": MARKER}],
                         kwargs={"context": {"default_ir_attachment_id": 5}})
    assert (err, text) == (True, refused("call", "product.document", "context", hint, layer="A"))
    assert raw.calls == [] and raw.metadata == []


def test_the_guard_refuses_a_scalar_structural_default_on_its_own() -> None:
    # Layer A skipped: Layer B (the guarded session) refuses the same default on a create.
    raw = ScriptedSession()
    g, _scope = guarded("odoo_execute",
                        {"model": "product.document", "method": "create"},
                        p=policy("standard"), session=raw, layer_a=False)
    with pytest.raises(PolicyDenied) as info:
        g.execute("product.document", "create", [{"name": "x"}],
                  {"context": {"default_ir_attachment_id": 5}})
    assert (info.value.rule, info.value.layer) == ("context", "B")
    assert "sets a field that binds or exposes a related record" in str(info.value)
    assert raw.calls == [] and raw.metadata == []


# --- residual 1: what stays allowed --------------------------------------------------------

def test_a_read_with_a_scalar_structural_default_still_runs() -> None:
    # A read creates nothing, so the default is inert: a search_read of a delegating child
    # carrying its link-field default is not refused (design 4.11).
    raw = ScriptedSession()
    err, text = _execute(raw, "product.document", "search_read",
                         kwargs={"domain": [["name", "!=", False]], "fields": ["name"],
                                 "context": {"default_ir_attachment_id": 5}})
    assert err is False, text
    assert ("product.document", "search_read") in raw.sent()


def test_default_res_model_and_res_id_stay_allowed_for_the_activity_flow() -> None:
    # Scheduling an activity passes default_res_model / default_res_id to bind it to a
    # record. Both stay allowed; the activity create runs under standard.
    fields = {"mail.activity": {"summary": CHAR, "res_model": CHAR,
                                "res_id": {"type": "integer"}},
              "mail.activity.type": {"name": CHAR}}
    raw = ScriptedSession(fields=fields, results={("mail.activity", "create"): 101})
    err, text = _execute(raw, "mail.activity", "create", args=[{"summary": "Call back"}],
                         kwargs={"context": {"default_res_model": "res.partner",
                                             "default_res_id": 3}})
    assert err is False, text
    assert ("mail.activity", "create") in raw.sent()


@pytest.mark.parametrize("name", ["move_type", "journal_id", "product_tmpl_id", "name"])
def test_a_plain_non_structural_default_still_runs_on_a_create(name: str) -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "create", args=[{"name": "x"}],
                         kwargs={"context": {f"default_{name}": "v"}})
    assert err is False, text
    assert ("res.partner", "create") in raw.sent()


def test_full_forwards_a_scalar_structural_default_unchanged() -> None:
    raw = ScriptedSession()
    context = {"default_ir_attachment_id": 5}
    err, text = _execute(raw, "product.document", "create", p=Policy(profile_name="full"),
                         args=[{"name": "x"}], kwargs={"context": context})
    assert err is False, text
    _args, kwargs, _ids = raw.call("product.document", "create")
    assert kwargs["context"] == context  # sent as given


# --- residual 1: the set is derived from the policy's own data ------------------------------

def test_structural_default_fields_are_derived_from_delegates_and_the_attachment_fields() -> None:
    # (a) the link field of every delegation whose parent is sensitive (all current rows:
    # ir.ui.view and ir.actions.server are tiered, ir.attachment is named by 4.5).
    links = {link for _parent, link in DELEGATES.values()}
    assert links <= STRUCTURAL_DEFAULT_FIELDS
    # (b) the ir.attachment structural fields except res_model and res_id.
    assert "public" in STRUCTURAL_DEFAULT_FIELDS and "res_field" in STRUCTURAL_DEFAULT_FIELDS
    assert (ATTACHMENT_STRUCTURAL_FIELDS - {"res_model", "res_id"}) <= STRUCTURAL_DEFAULT_FIELDS
    # res_model and res_id are kept out on purpose.
    assert "res_model" not in STRUCTURAL_DEFAULT_FIELDS
    assert "res_id" not in STRUCTURAL_DEFAULT_FIELDS
    # the gate is the creating classes only; a read is inert.
    assert _STRUCTURAL_DEFAULT_OPS == {"create", "write", "call"}
    assert "read" not in _STRUCTURAL_DEFAULT_OPS and "inspect" not in _STRUCTURAL_DEFAULT_OPS


@pytest.mark.parametrize("name", sorted(STRUCTURAL_DEFAULT_FIELDS))
def test_check_context_leaves_a_structural_default_alone_on_a_read(name: str) -> None:
    # Called with the read op (creating=False): no refusal (the default fills nothing).
    check_context(Policy(profile_name="standard"), "product.document",
                  {f"default_{name}": 5}, op="read")


# --- residual 2: a context nested in onchange's fields_spec ---------------------------------

SEALED = [[0, 0, {"login": "attacker"}]]  # a create command Odoo would apply to res.users


def test_onchange_fields_spec_nested_context_default_list_is_refused_by_name() -> None:
    raw = ScriptedSession()
    spec = {"name": {}, "child_ids": {"fields": {"name": {}},
                                      "context": {"default_user_ids": SEALED}}}
    err, text = _execute(raw, "res.partner", "onchange", ids=[3],
                         kwargs={"values": {"name": "x"}, "field_names": ["name"],
                                 "fields_spec": spec})
    assert err is True and raw.calls == [], text
    assert "rule context)" in text and "holds a list or an object" in text, text


def test_onchange_fields_spec_nested_context_default_list_is_refused_positionally() -> None:
    raw = ScriptedSession()
    spec = {"child_ids": {"fields": {"name": {}}, "context": {"default_user_ids": SEALED}}}
    err, text = _execute(raw, "res.partner", "onchange", ids=[3],
                         args=[{"name": "x"}, ["name"], spec])
    assert err is True and raw.calls == [], text
    assert "rule context)" in text and "holds a list or an object" in text, text


def test_a_scalar_structural_default_in_an_onchange_spec_context_is_refused() -> None:
    raw = ScriptedSession()
    spec = {"product_document_ids": {"fields": {"name": {}},
                                     "context": {"default_ir_attachment_id": 5}}}
    err, text = _execute(raw, "product.template", "onchange", ids=[1],
                         args=[{"name": "x"}, ["name"], spec])
    assert err is True and raw.calls == [], text
    assert "sets a field that binds or exposes a related record" in text, text


def test_the_guard_refuses_an_onchange_spec_context_on_its_own() -> None:
    raw = ScriptedSession()
    g, _scope = guarded("odoo_execute", {"model": "res.partner", "method": "onchange",
                                         "ids": [3]},
                        p=policy("standard"), session=raw, layer_a=False)
    spec = {"child_ids": {"fields": {"name": {}}, "context": {"default_user_ids": SEALED}}}
    with pytest.raises(PolicyDenied) as info:
        g.execute("res.partner", "onchange", [{"name": "x"}, ["name"], spec], {}, ids=[3])
    assert (info.value.rule, info.value.layer) == ("context", "B")
    assert raw.calls == [] and raw.metadata == []


# --- residual 2: what stays working --------------------------------------------------------

def test_onchange_with_the_pre17_flat_fields_spec_still_runs() -> None:
    # The Odoo 10-16 fourth argument (field_onchange) is a flat {dotted path: marker} map
    # with no nested context; it must not fail closed. Passed positionally and by the old
    # keyword name (open_keywords lets the pre-17 names pass).
    raw = ScriptedSession(results={("res.partner", "onchange"): {"value": {}}})
    err, text = _execute(raw, "res.partner", "onchange", ids=[3],
                         args=[{"name": "x"}, "name",
                               {"name": "1", "child_ids": "", "child_ids.name": "1"}])
    assert err is False, text
    assert ("res.partner", "onchange") in raw.sent()


def test_onchange_with_a_safe_nested_spec_context_runs() -> None:
    raw = ScriptedSession(results={("res.partner", "onchange"): {"value": {}}})
    spec = {"child_ids": {"fields": {"name": {}}, "context": {"lang": "es_MX"}}}
    err, text = _execute(raw, "res.partner", "onchange", ids=[3],
                         args=[{"name": "x"}, ["name"], spec])
    assert err is False, text
    assert ("res.partner", "onchange") in raw.sent()


def test_onchange_values_are_not_expanded_as_writes() -> None:
    # onchange simulates: its values are the record's existing lines (replace/clear commands),
    # which must not be checked as writes of the comodel. A quotation preview with lines runs.
    fields = {"sale.order": {"name": CHAR, "partner_id": m2o("res.partner"),
                             "order_line": o2m("sale.order.line", "order_id")},
              "sale.order.line": {"name": CHAR, "order_id": m2o("sale.order")}}
    raw = ScriptedSession(fields=fields,
                          results={("sale.order", "onchange"): {"value": {"name": "x"}}})
    err, text = _execute(raw, "sale.order", "onchange", ids=[],
                         args=[{"partner_id": 3, "order_line": [[6, False, [12, 13]]]},
                               ["partner_id"], {"partner_id": {}, "order_line": {}}])
    assert err is False, text
    assert ("sale.order", "onchange") in raw.sent()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
