# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Layer B, the guarded session (design 6.5, 6.6, 4.4 to 4.7 and 4.11; tests 9.4).

Each test builds the guarded session a call gets (``policy_fakes.guarded``: Layer
A first) or runs the call through ``McpServer.call_tool``, over a scripted raw
session that records what reaches it. A refused call must never reach it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fake_odoo_http import FakeOdoo
from policy_fakes import (
    KEY,
    NO_WORKAROUND,
    REASON,
    SEP,
    B,
    Manager,
    ScriptedSession,
    call,
    guarded,
    policy,
    refused,
    server,
)

from odoo_mcp.config import Settings
from odoo_mcp.errors import PolicyDenied, PolicyEnvelopeError, PolicyError
from odoo_mcp.policy import texts
from odoo_mcp.policy.check import CallScope
from odoo_mcp.policy.guard import (
    GuardedSession,
    ManagerView,
    TransportView,
)
from odoo_mcp.policy.model import Policy
from odoo_mcp.server import McpServer
from odoo_mcp.transport.fallback import READ_METHODS

SECURITY_HINT = ("users, groups, access rules, modules, API keys, bank accounts, chatter history "
                 "and fiscal sequences are read-only outside profile 'full' unless the policy "
                 "file names the model exactly, with a reason")
SECRETS_HINT = ("this model holds credentials or acts as one; only an entry naming it exactly, "
                "with a reason, in the policy file opens it")
CUSTOMIZATION_HINT = ("fields, views, automations and other ir.* records need profile 'builder', "
                      "or an entry naming the model exactly, with a reason")
OUTBOUND_HINT = ("this model sends e-mail, SMS, letters or share links, or decides what is sent; "
                 "only an entry naming it exactly, with a reason, opens it")
UNLINK_HINT = ("profile 'standard' does not delete: archive instead (odoo_write {\"active\": "
               "false}) where the model has an active field, or ask the user to allow unlink")


def relational(method: str, model: str, op: str, comodel: str, field: str, command: int,
               rule: str, hint: str = "", *, profile: str = "standard") -> str:
    return refused(op, comodel, "relational",
                   f"this {method} on '{model}' also {op}s '{comodel}' through field '{field}' "
                   f"(command {command}), and the policy refuses '{op}' on '{comodel}' ({rule})",
                   profile=profile)


def path_text(method: str, model: str, op: str, comodel: str, path: str, rule: str, *,
              profile: str = "standard") -> str:
    return refused(op, comodel, "relational",
                   f"this {method} on '{model}' also {op}s '{comodel}' through '{path}', and the "
                   f"policy refuses '{op}' on '{comodel}' ({rule})", profile=profile)


def field_text(op: str, model: str, name: str, *, by_file: bool = False,
               profile: str = "standard") -> str:
    if by_file:
        hint = (f"field '{name}' of '{model}' is withheld by the policy file (fields.withhold) "
                "and is not read, written, filtered, grouped or sorted on through these tools; "
                "read other fields")
    else:
        hint = (f"field '{name}' of '{model}' looks like a credential or token and is not read, "
                "written, filtered, grouped or sorted on through these tools; read other fields, "
                "or release it with fields.allow in the policy file")
    return refused(op, model, "field", hint, profile=profile)


def envelope_text(tool: str, model: str, method: str) -> str:
    return (f"internal error: {tool} tried {model}.{method}, which its permission mapping does "
            "not declare. The call was stopped before it reached Odoo. This is a bug in "
            "odoo-tools; please report it to dev@transgenia.org.")


def raises(fn: Any, *args: Any, **kwargs: Any) -> PolicyError:
    with pytest.raises(PolicyError) as info:
        fn(*args, **kwargs)
    return info.value


# --- the views: what a handler can reach -----------------------------------------------

def test_the_session_exposes_no_secret_and_no_transport_call() -> None:
    raw = ScriptedSession()
    g, _scope = guarded("odoo_search_read", {"model": "res.partner"}, session=raw)
    for reach in (lambda: g.transport.execute_kw, lambda: g.creds.secret,
                  lambda: g.schema, lambda: g.execute_kw, lambda: g.anything_else):
        with pytest.raises(AttributeError):
            reach()
    assert getattr(g.transport, "execute_kw", None) is None
    assert (g.creds.url, g.creds.db, g.creds.login, g.creds.secret_kind) == (
        "https://odoo.example", "db", "bot@example.com", "api_key")  # no user:pass@ either
    assert (g.transport.active, g.transport.series, g.transport.json2_available,
            g.transport.transport_notice, g.transport.secret_kind) == (
        "json2", (17, 0), True, None, "api_key")
    shown = [getattr(g.creds, name) for name in type(g.creds).__slots__]
    assert KEY not in repr(shown) and "pw" not in repr(shown)
    assert not hasattr(g.creds, "__dict__")  # slots: nothing else can be hung on it
    assert g.uid == 2 and g.facts().version == 17 and g.module_installed("sale")


def test_a_view_of_a_transport_without_an_attribute_behaves_like_the_transport() -> None:
    view = TransportView(object())
    assert getattr(view, "series", "default") == "default"  # tools use getattr(..., default)


def test_the_manager_view_hands_out_no_session() -> None:
    view = ManagerView(Manager(ScriptedSession()))
    assert view.connections() == [] and view.tool_calls_snapshot() == {}
    for name in ("default", "get", "session", "_sessions"):
        with pytest.raises(AttributeError):
            getattr(view, name)


def test_the_guard_needs_the_scope_of_layer_a() -> None:
    with pytest.raises(TypeError):
        GuardedSession(ScriptedSession(), CallScope("odoo_search"))


def test_the_server_hands_the_handler_a_guarded_session_and_a_manager_view(
        monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    def spy(ctx: Any, args: dict[str, Any]) -> Any:
        seen.append((ctx.session, ctx.manager))
        return {"ok": True}

    from odoo_mcp.registry import registry

    monkeypatch.setattr(registry.get("odoo_search"), "handler", spy)
    raw = ScriptedSession()
    assert call(server(raw), "odoo_search", model="res.partner") == (False, '{"ok": true}')
    (session, manager), = seen
    assert isinstance(session, GuardedSession) and isinstance(manager, ManagerView)


# --- the envelope -------------------------------------------------------------------------

def test_a_call_the_mapping_does_not_declare_is_stopped_before_the_transport() -> None:
    raw = ScriptedSession()
    g, _scope = guarded("odoo_read", {"model": "res.partner", "ids": [1]}, session=raw)
    error = raises(g.execute, "res.partner", "unlink", [[1]])
    assert isinstance(error, PolicyEnvelopeError) and (error.rule, error.layer) == (
        "envelope", "B")
    assert str(error) == envelope_text("odoo_read", "res.partner", "unlink")
    for model, method in [("res.users", "read"), ("res.partner", "write"),
                          ("res.partner", "action_confirm"), ("sale.order", "search")]:
        assert str(raises(g.execute, model, method, [[1]])) == envelope_text(
            "odoo_read", model, method)
    assert str(raises(g.fields_get, "res.users")) == envelope_text(
        "odoo_read", "res.users", "fields_get")
    assert raw.calls == [] and raw.metadata == []


def test_a_declared_touch_covers_its_aliases_and_field_metadata() -> None:
    raw = ScriptedSession(version=17)
    g, _scope = guarded("odoo_search_read", {"model": "account.invoice"}, session=raw)
    assert g.execute("account.move", "search_read", [[]], {"fields": ["name"]}) == []
    assert g.fields_get("account.move", ["type"]) == raw.fields["account.move"]
    assert raw.sent() == [("account.move", "search_read")]


def test_the_names_are_checked_for_every_transport() -> None:
    g, _scope = guarded("odoo_execute", {"model": "res.partner", "method": "action_x"},
                        session=ScriptedSession())
    assert "rule invalid-name" in str(raises(g.execute, "res.partner", "_private", []))
    assert "rule invalid-name" in str(raises(g.execute, "Res.Partner", "read", [[1]]))
    assert "Res.Partner" not in str(raises(g.execute, "Res.Partner", "read", [[1]]))


# --- Layer B stands alone ----------------------------------------------------------------

def test_layer_b_decides_again_even_when_layer_a_was_skipped() -> None:
    raw = ScriptedSession()
    g, _scope = guarded("odoo_write", {"model": "res.users", "ids": [2], "values": {"name": "x"}},
                        session=raw, layer_a=False)
    error = raises(g.execute, "res.users", "write", [[2], {"name": "x"}])
    assert str(error) == refused("write", "res.users", "tier:security", SECURITY_HINT)
    assert (error.rule, error.layer) == ("tier:security", "B")
    g, _scope = guarded("odoo_search_read", {"model": "ir.config_parameter"}, session=raw,
                        layer_a=False)
    assert str(raises(g.execute, "ir.config_parameter", "search_read", [[]])) == refused(
        "read", "ir.config_parameter", "tier:secrets", SECRETS_HINT)
    assert raw.calls == []


def test_an_outbound_method_is_decided_again_on_the_actual_arguments() -> None:
    raw = ScriptedSession()
    arguments = {"model": "crm.lead", "method": "message_post", "ids": [3],
                 "kwargs": {"body": "x", "subtype_xmlid": "mail.mt_note"}}
    g, _scope = guarded("odoo_execute", arguments, session=raw)
    assert g.execute("crm.lead", "message_post", [], {"body": "x",
                                                      "subtype_xmlid": "mail.mt_note"},
                     ids=[3]) is None
    error = raises(g.execute, "crm.lead", "message_post", [], {"body": "x", "partner_ids": [9]},
                   ids=[3])
    assert error.rule == "outbound-method"
    assert raw.sent() == [("crm.lead", "message_post")]


# --- x2many commands (design 6.6) --------------------------------------------------------

def effects(tool: str, arguments: dict[str, Any], *, p: Policy | None = None) -> list[str]:
    """What the guard decided for a call that went through: the scope's effective list."""
    raw = ScriptedSession()
    g, scope = guarded(tool, arguments, p=p, session=raw)
    method = "create" if tool == "odoo_create" else "write"
    args: list[Any] = ([arguments["values"]] if tool == "odoo_create"
                       else [arguments["ids"], arguments["values"]])
    g.execute(arguments["model"], method, args)
    assert raw.sent() == [(arguments["model"], method)]
    return scope.effective


FULL = Policy(profile_name="full")


@pytest.mark.parametrize(("value", "in_write", "in_create"), [
    ([[0, 0, {"name": "x"}]], "create", "create"),
    ([[1, 5, {"name": "x"}]], "write", "write"),
    ([[2, 5]], "unlink", "unlink"),
    ([[2, 5, 0]], "unlink", "unlink"),
    ([[3, 5]], "unlink", "write"),  # a write removes the line, and the inverse may cascade
    ([[4, 5]], "write", "write"),  # re-parents the line
    ([[5]], "unlink", "write"),
    ([[5, 0, 0]], "unlink", "write"),
    ([[6, 0, [5, 6]]], "unlink", "write"),
    ([5, 6], "unlink", "write"),  # a bare id list sets the lines
])
def test_one2many_commands(value: Any, in_write: str, in_create: str) -> None:
    write = effects("odoo_write", {"model": "sale.order", "ids": [1],
                                   "values": {"order_line": value}}, p=FULL)
    assert write == ["write:sale.order", f"{in_write}:sale.order.line"]
    create = effects("odoo_create", {"model": "sale.order", "values": {"order_line": value}},
                     p=FULL)
    assert create == ["create:sale.order", f"{in_create}:sale.order.line"]


@pytest.mark.parametrize("value", [
    [[3, 5]], [[4, 5]], [[5]], [[6, 0, [5, 6]]], [5, 6],
])
def test_many2many_links_read_the_comodel(value: Any) -> None:
    for tool, arguments in [
        ("odoo_write", {"model": "sale.order", "ids": [1], "values": {"tag_ids": value}}),
        ("odoo_create", {"model": "sale.order", "values": {"tag_ids": value}}),
    ]:
        assert effects(tool, arguments)[-1] == "read:crm.tag"


def test_many2many_create_write_and_delete_commands_act_on_the_comodel() -> None:
    for command, op in [([0, 0, {"name": "x"}], "create"), ([1, 5, {"name": "x"}], "write"),
                        ([2, 5], "unlink")]:
        assert effects("odoo_write", {"model": "sale.order", "ids": [1],
                                      "values": {"tag_ids": [command]}}, p=FULL)[-1] == (
            f"{op}:crm.tag")


def test_false_clears_an_x2many_in_a_write_and_nothing_in_a_create() -> None:
    assert effects("odoo_write", {"model": "sale.order", "ids": [1],
                                  "values": {"order_line": False}}, p=FULL)[-1] == (
        "unlink:sale.order.line")
    assert effects("odoo_write", {"model": "sale.order", "ids": [1],
                                  "values": {"tag_ids": None}})[-1] == "read:crm.tag"
    assert effects("odoo_create", {"model": "sale.order",
                                   "values": {"order_line": False}}) == ["create:sale.order"]
    # a plain False (archiving) is not a command
    assert effects("odoo_write", {"model": "res.partner", "ids": [8],
                                  "values": {"active": False}}) == ["write:res.partner"]


def test_a_many2many_link_to_a_security_model_is_a_write_there() -> None:
    raw = ScriptedSession()
    arguments = {"model": "res.company", "ids": [1], "values": {"user_ids": [[4, 2]]}}
    error, text = call(server(raw), "odoo_write", **arguments)
    assert error is True
    assert text == relational("write", "res.company", "write", "res.users", "user_ids", 4,
                              "tier:security")
    assert raw.sent() == []


def test_commands_are_refused_where_the_comodel_is_refused() -> None:
    raw = ScriptedSession()
    srv = server(raw)
    cases = [
        ({"model": "res.partner", "ids": [8],
          "values": {"user_ids": [[1, 4, {"groups_id": [[4, 1]]}]]}},
         relational("write", "res.partner", "write", "res.users", "user_ids", 1,
                    "tier:security")),
        ({"model": "res.partner", "ids": [8],
          "values": {"bank_ids": [[1, 3, {"acc_number": "ATTACKER"}]]}},
         relational("write", "res.partner", "write", "res.partner.bank", "bank_ids", 1,
                    "tier:security")),
        ({"model": "sale.order", "ids": [1], "values": {"order_line": [[5]]}},
         relational("write", "sale.order", "unlink", "sale.order.line", "order_line", 5,
                    "profile:standard")),
        ({"model": "res.partner", "ids": [8],
          "values": {"message_follower_ids": [[0, 0, {"partner_id": 9}]]}},
         relational("write", "res.partner", "create", "mail.followers",
                    "message_follower_ids", 0, "tier:outbound")),
        ({"model": "res.users", "ids": [2],
          "values": {"api_key_ids": [[0, 0, {"name": "x"}]]}}, None),
    ]
    for arguments, expected in cases:
        error, text = call(srv, "odoo_write", **arguments)
        assert error is True
        if expected is not None:
            assert text == expected
    assert raw.sent() == []
    # NEVER holds through commands under profile full too
    error, text = call(server(raw, policy_profile="full"), "odoo_write", model="res.users",
                       ids=[2], values={"api_key_ids": [[0, 0, {"name": "x"}]]})
    assert error is True and "rule relational" in text and "(never:api-keys)" in text
    assert raw.sent() == []


def test_nested_commands_are_followed_to_the_models_they_reach() -> None:
    raw = ScriptedSession()
    values = {"child_ids": [[0, 0, {"name": "x", "user_ids": [[0, 0, {"login": "x"}]]}]]}
    error, text = call(server(raw), "odoo_write", model="res.partner", ids=[8], values=values)
    assert error is True and text == relational("write", "res.partner", "create", "res.users",
                                                "user_ids", 0, "tier:security")
    assert raw.sent() == []


def test_the_command_depth_is_limited() -> None:
    def nested(depth: int) -> dict[str, Any]:
        values: dict[str, Any] = {"name": "leaf"}
        for _ in range(depth):
            values = {"name": "x", "child_ids": [[0, 0, values]]}
        return values

    raw = ScriptedSession()
    g, _scope = guarded("odoo_write", {"model": "res.partner", "ids": [8], "values": {}},
                        session=raw)
    g.execute("res.partner", "write", [[8], nested(4)])
    error = raises(g.execute, "res.partner", "write", [[8], nested(5)])
    assert error.rule == "shape" and "nest too deeply" in str(error)
    assert raw.sent() == [("res.partner", "write")]


@pytest.mark.parametrize(("values", "detail"), [
    ({"x_unknown_ids": [[0, 0, {"name": "x"}]]},
     "field 'x_unknown_ids' is unknown to fields_get and carries a list"),
    ({"order_line": [[9, 1]]}, "the value of field 'order_line' is not a list of x2many commands"),
    ({"order_line": [1, [4, 2]]},
     "the value of field 'order_line' is not a list of x2many commands"),
    ({"order_line": [[1, 5]]}, "the value of field 'order_line' is not a list of x2many commands"),
    ({"order_line": [[6, 0, ["x"]]]},
     "the value of field 'order_line' is not a list of x2many commands"),
])
def test_commands_that_cannot_be_read_are_refused(values: dict[str, Any], detail: str) -> None:
    raw = ScriptedSession()
    error, text = call(server(raw), "odoo_write", model="sale.order", ids=[1], values=values)
    assert error is True
    assert text == refused("write", "sale.order", "shape",
                           f"the arguments of this odoo_write call cannot be checked ({detail}); "
                           "correct them")
    assert raw.sent() == []


def test_nested_values_are_named_on_the_model_they_belong_to() -> None:
    raw = ScriptedSession()
    error, text = call(server(raw), "odoo_write", model="sale.order", ids=[1],
                       values={"order_line": [[0, 0, {"bad key": 1}]]})
    assert error is True and text == refused(
        "create", "sale.order.line", "shape", "the arguments of this odoo_write call cannot be "
        "checked (a values key is not a field name); correct them")
    assert raw.sent() == []


def test_other_values_for_an_x2many_are_left_to_odoo_which_refuses_them() -> None:
    # Odoo reads an x2many value only from a list, a tuple, False or None, and refuses
    # anything else ("Wrong value"), so the guard has nothing to expand.
    assert effects("odoo_write", {"model": "sale.order", "ids": [1],
                                  "values": {"order_line": "[(5,)]"}}) == ["write:sale.order"]


def test_known_non_relational_list_values_are_left_to_odoo() -> None:
    assert effects("odoo_write", {"model": "res.partner", "ids": [8],
                                  "values": {"properties": [{"name": "a", "value": 1}]}}) == [
        "write:res.partner"]


# --- paths (design 6.6) ---------------------------------------------------------------------

def test_every_model_a_domain_path_reaches_must_allow_read() -> None:
    raw = ScriptedSession()
    domain = [["partner_id.country_id.code", "=", "MX"]]
    g, scope = guarded("odoo_search_read", {"model": "sale.order", "domain": domain},
                       session=raw)
    assert g.execute("sale.order", "search_read", [domain], {}) == []
    assert scope.effective == ["read:sale.order", "read:res.partner", "read:res.country"]
    assert [model for model, _attributes in raw.metadata] == ["sale.order", "res.partner"]


def test_a_single_segment_needs_no_field_metadata() -> None:
    raw = ScriptedSession()
    assert call(server(raw), "odoo_search_read", model="sale.order",
                domain=[["name", "=", "x"]], fields=["name"], order="name desc")[0] is False
    assert raw.metadata == []


@pytest.mark.parametrize(("tool", "arguments", "method", "shown"), [
    ("odoo_search_read", {"model": "payment.transaction",
                          "domain": [["provider_id.name", "=", "x"]]},
     "search_read", "provider_id.name"),
    ("odoo_search_count", {"model": "payment.transaction",
                           "domain": [["provider_id", "any", [["name", "=", "x"]]]]},
     "search_count", "provider_id.name"),
    ("odoo_search_read", {"model": "payment.transaction", "order": "provider_id.name desc"},
     "search_read", "provider_id.name"),
    ("odoo_read_group", {"model": "payment.transaction", "fields": ["amount:sum"],
                         "groupby": ["provider_id.name"]}, "read_group", "provider_id.name"),
    ("odoo_execute", {"model": "payment.transaction", "method": "web_read", "ids": [1],
                      "kwargs": {"specification": {"provider_id": {"fields": {"name": {}}}}}},
     "web_read", "provider_id.name"),
])
def test_a_path_that_reaches_a_secrets_model_is_refused(tool: str, arguments: dict[str, Any],
                                                        method: str, shown: str) -> None:
    raw = ScriptedSession()
    error, text = call(server(raw), tool, **arguments)
    assert error is True
    assert text == path_text(method, "payment.transaction", "read", "payment.provider", shown,
                             "tier:secrets")
    assert raw.sent() == []


def test_export_paths_are_followed_segment_by_segment() -> None:
    raw = ScriptedSession()
    srv = server(raw)
    error, text = call(srv, "odoo_execute", model="payment.transaction", method="export_data",
                       ids=[1], kwargs={"fields_to_export": ["reference", "provider_id/name"]})
    assert error is True and text == path_text(
        "export_data", "payment.transaction", "read", "payment.provider", "provider_id.name",
        "tier:secrets")
    # a withheld name is refused by Layer A already, before any session exists
    error, text = call(srv, "odoo_execute", model="payment.transaction", method="export_data",
                       ids=[1], kwargs={"fields_to_export": ["provider_id/stripe_secret_key"]})
    assert error is True and "rule field" in text and "Nothing was sent to Odoo" in text
    # and a model whose methods are closed (outbound) exports nothing through odoo_execute
    error, text = call(srv, "odoo_execute", model="mail.template", method="export_data",
                       ids=[1], kwargs={"fields_to_export": ["mail_server_id/smtp_host"]})
    assert error is True and "rule tier:outbound" in text
    assert raw.sent() == []


def test_a_web_read_specification_is_walked_at_every_depth() -> None:
    raw = ScriptedSession()
    spec = {"partner_id": {"fields": {"country_id": {"fields": {"name": {}}}}}}
    g, scope = guarded("odoo_execute", {"model": "sale.order", "method": "web_read", "ids": [1],
                                        "kwargs": {"specification": spec}}, session=raw)
    g.execute("sale.order", "web_read", [], {"specification": spec}, ids=[1])
    assert scope.effective == ["read:sale.order", "call:sale.order:web_read", "read:res.partner",
                               "read:res.country"]


@pytest.mark.parametrize(("model", "columns", "expected"), [
    ("res.partner", ["name", "country_id"], ["read:res.country"]),
    ("res.partner", ["name", "category_id/id"], ["read:res.partner.category"]),
    ("res.partner", ["name", "parent_id/.id"], ["read:res.partner"]),
    ("sale.order", ["name", "order_line/product_id"],
     ["create:sale.order.line", "write:sale.order.line", "read:product.product"]),
    ("sale.order", ["name", "order_line/id", "order_line/name"],
     ["create:sale.order.line", "write:sale.order.line"]),
])
def test_import_columns_reach_the_models_they_name(model: str, columns: list[str],
                                                   expected: list[str]) -> None:
    raw = ScriptedSession()
    g, scope = guarded("odoo_import", {"model": model, "fields": columns,
                                       "rows": [["a", "b"]]}, session=raw)
    g.execute(model, "load", [columns, [["a", "b"]]], transports=("json2",))
    assert scope.effective == [f"create:{model}", f"write:{model}", *expected]
    assert raw.sent() == [(model, "load")]


@pytest.mark.parametrize(("columns", "op", "comodel", "shown"), [
    (["name", "bank_ids/acc_number"], "create", "res.partner.bank", "bank_ids/acc_number"),
    (["name", "user_ids/groups_id"], "create", "res.users", "user_ids/groups_id"),
    (["name", "user_ids/id"], "create", "res.users", "user_ids"),
])
def test_import_columns_that_reach_a_closed_model_are_refused(columns: list[str], op: str,
                                                              comodel: str, shown: str) -> None:
    raw = ScriptedSession()
    error, text = call(server(raw), "odoo_import", model="res.partner", fields=columns,
                       rows=[["a", "b"]])
    assert error is True
    assert text == path_text("load", "res.partner", op, comodel, shown, "tier:security")
    assert raw.sent() == []


# --- withheld fields (design 4.11) --------------------------------------------------------

VAT = {"withhold": ["res.partner.vat"]}


@pytest.mark.parametrize(("tool", "arguments", "op", "shown"), [
    ("odoo_search_read", {"model": "sale.order", "domain": [["partner_id.vat", "=", "x"]]},
     "read", "partner_id.vat"),
    ("odoo_search_read", {"model": "sale.order",
                          "domain": [["partner_id", "any", [["vat", "=", "x"]]]]},
     "read", "partner_id.vat"),
    ("odoo_search_read", {"model": "sale.order", "order": "partner_id.vat"}, "read",
     "partner_id.vat"),
    ("odoo_read_group", {"model": "sale.order", "fields": ["amount_total:sum"],
                         "groupby": ["partner_id.vat"]}, "read", "partner_id.vat"),
    ("odoo_execute", {"model": "sale.order", "method": "web_read", "ids": [1],
                      "kwargs": {"specification": {"partner_id": {"fields": {"vat": {}}}}}},
     "read", "partner_id.vat"),
    ("odoo_execute", {"model": "sale.order", "method": "export_data", "ids": [1],
                      "kwargs": {"fields_to_export": ["partner_id/vat"]}}, "read",
     "partner_id.vat"),
    ("odoo_import", {"model": "sale.order", "fields": ["name", "partner_id/vat"],
                     "rows": [["a", "b"]]}, "create", "partner_id/vat"),
])
def test_a_field_the_file_withholds_is_refused_on_the_model_a_path_reaches(
        tool: str, arguments: dict[str, Any], op: str, shown: str) -> None:
    # Layer A cannot tell which model a later segment belongs to; Layer B can.
    raw = ScriptedSession()
    error, text = call(server(raw, p=policy(fields=VAT)), tool, **arguments)
    assert error is True
    assert text == field_text(op, "sale.order", shown, by_file=True)
    assert raw.sent() == []


def test_withheld_keys_of_nested_command_values_are_refused() -> None:
    raw = ScriptedSession()
    srv = server(raw, p=policy(fields=VAT))
    error, text = call(srv, "odoo_write", model="res.partner", ids=[8],
                       values={"child_ids": [[1, 3, {"vat": "X"}]]})
    assert error is True and text == field_text("write", "res.partner", "vat", by_file=True)
    error, text = call(srv, "odoo_write", model="res.partner", ids=[8],
                       values={"child_ids": [[0, 0, {"name": "x", "signup_token": "t"}]]})
    assert error is True and text == field_text("create", "res.partner", "signup_token")
    assert raw.sent() == []


def test_reads_lose_their_withheld_fields_and_the_result_names_them() -> None:
    rows = [{"id": 3, "name": "Acme", "signup_token": "TOKEN-DO-NOT-LEAK", "vat": "X",
             "payment_token_id": False}]
    raw = ScriptedSession(results={("res.partner", "search_read"): rows})
    payload = json.loads(call(server(raw), "odoo_search_read", model="res.partner")[1])
    assert payload["records"] == [{"id": 3, "name": "Acme", "vat": "X",
                                   "payment_token_id": False}]
    assert payload["policy_withheld_fields"] == ["res.partner.signup_token"]
    # the file's withholds apply in profile full too; the built-in list does not
    for profile, kept in [("standard", ["id", "name", "payment_token_id"]),
                          ("full", ["id", "name", "signup_token", "payment_token_id"])]:
        payload = json.loads(call(server(raw, p=policy(profile, fields={"withhold": ["*.vat"]})),
                                  "odoo_search_read", model="res.partner")[1])
        assert list(payload["records"][0]) == kept
        assert "res.partner.vat" in payload["policy_withheld_fields"]
    # a released field is returned
    released = policy(fields={"allow": [{"field": "res.partner.signup_token",
                                         "reason": REASON}]})
    payload = json.loads(call(server(raw, p=released), "odoo_search_read",
                              model="res.partner")[1])
    assert payload["records"][0]["signup_token"] == "TOKEN-DO-NOT-LEAK"
    assert "policy_withheld_fields" not in payload


def test_nothing_is_withheld_without_a_reason_to() -> None:
    raw = ScriptedSession(results={("res.partner", "search_read"): [{"id": 3, "name": "A"}]})
    payload = json.loads(call(server(raw), "odoo_search_read", model="res.partner")[1])
    assert payload == {"model": "res.partner", "records": [{"id": 3, "name": "A"}]}


def test_nested_rows_are_redacted_on_the_model_they_belong_to() -> None:
    spec = {"partner_id": {"fields": {"display_name": {}}}}
    rows = [{"id": 1, "name": "S1", "partner_id": {"id": 3, "display_name": "Acme",
                                                   "signup_token": "T", "vat": "X"}}]
    raw = ScriptedSession(results={("sale.order", "web_read"): rows})
    error, text = call(server(raw, p=policy(fields=VAT)), "odoo_execute", model="sale.order",
                       method="web_read", ids=[1], kwargs={"specification": spec})
    assert error is False
    payload = json.loads(text)
    assert payload["result"] == [{"id": 1, "name": "S1",
                                  "partner_id": {"id": 3, "display_name": "Acme"}}]
    assert payload["policy_withheld_fields"] == ["sale.order.partner_id.signup_token",
                                                 "sale.order.partner_id.vat"]


@pytest.mark.parametrize(("method", "result", "redacted"), [
    ("web_search_read", {"length": 1, "records": [{"id": 3, "signup_token": "T"}]},
     {"length": 1, "records": [{"id": 3}]}),
    ("default_get", {"name": "x", "signup_token": "T"}, {"name": "x"}),
    ("read_group", [{"name": "x", "__count": 2, "signup_token": "T"}],
     [{"name": "x", "__count": 2}]),
])
def test_every_read_class_result_is_redacted(method: str, result: Any, redacted: Any) -> None:
    raw = ScriptedSession(results={("res.partner", method): result})
    arguments: dict[str, Any] = {"model": "res.partner", "method": method}
    if method == "read_group":
        arguments["kwargs"] = {"domain": [], "fields": ["name"], "groupby": ["name"]}
    payload = json.loads(call(server(raw), "odoo_execute", **arguments)[1])
    assert payload["result"] == redacted
    assert payload["policy_withheld_fields"] == ["res.partner.signup_token"]


def test_the_code_of_automations_is_withheld_except_under_builder() -> None:
    rows = [{"id": 1, "name": "Flag", "code": "env['x'].search([])"}]
    raw = ScriptedSession(results={("ir.actions.server", "search_read"): rows})
    standard = json.loads(call(server(raw), "odoo_search_read", model="ir.actions.server")[1])
    assert standard["records"] == [{"id": 1, "name": "Flag"}]
    assert standard["policy_withheld_fields"] == ["ir.actions.server.code"]
    builder = json.loads(call(server(raw, policy_profile="builder"), "odoo_search_read",
                              model="ir.actions.server")[1])
    assert builder["records"] == rows and "policy_withheld_fields" not in builder


def test_a_csv_export_builds_its_columns_from_the_redacted_rows() -> None:
    rows = [{"id": 3, "name": "Acme", "signup_token": "TOKEN-DO-NOT-LEAK"}]
    raw = ScriptedSession(results={("res.partner", "search_read"): rows})
    payload = json.loads(call(server(raw), "odoo_export_records_csv", model="res.partner")[1])
    assert payload["columns"] == ["id", "name"] and "TOKEN" not in payload["csv"]
    assert payload["policy_withheld_fields"] == ["res.partner.signup_token"]


# --- ir.attachment, a pointer model (design 4.5) ------------------------------------------

ATTACHMENT_FIELD = ("attachment {id} stores a field of a record, or belongs to a model the "
                    "policy does not let you {op}; use odoo_record_documents for a record's files")
ATTACHMENT_CREATE = ("an attachment created or changed through these tools cannot be public and "
                     "cannot store a field of a record (res_field); use odoo_record_documents for "
                     "a record's files")
PIN_HINT = ("generic access to ir.attachment must name the parent model: add [\"res_model\", "
            "\"=\", \"<model>\"] to the domain and do not filter on res_field, or use "
            "odoo_record_documents")
NO_FIELD = ["res_field", "=", False]


@pytest.mark.parametrize(("tool", "arguments", "where"), [
    ("odoo_search_read", {"model": "ir.attachment",
                          "domain": [["res_model", "=", "res.partner"], ["res_id", "=", 3]]},
     ("args", 0)),
    ("odoo_search_count", {"model": "ir.attachment",
                           "domain": ["&", ["res_model", "in", ["sale.order", False]],
                                      ["name", "ilike", "pdf"]]}, ("args", 0)),
    ("odoo_execute", {"model": "ir.attachment", "method": "search_read",
                      "kwargs": {"domain": [["res_model", "=", "res.partner"]]}},
     ("kwargs", "domain")),
    ("odoo_execute", {"model": "ir.attachment", "method": "name_search",
                      "args": ["scan", [["res_model", "=", "res.partner"]]]}, ("args", 1)),
])
def test_an_attachment_search_never_sees_the_field_attachments(
        tool: str, arguments: dict[str, Any], where: tuple[str, Any]) -> None:
    raw = ScriptedSession()
    assert call(server(raw), tool, **arguments)[0] is False
    method = arguments.get("method") or {"odoo_search_read": "search_read",
                                         "odoo_search_count": "search_count"}[tool]
    args, kwargs, _ids = raw.call("ir.attachment", method)
    sent = args[where[1]] if where[0] == "args" else kwargs[where[1]]
    original = (arguments.get("domain") or arguments.get("kwargs", {}).get("domain")
                or arguments["args"][1])
    assert sent == [NO_FIELD, *original]


def test_layer_b_pins_an_attachment_search_on_its_own() -> None:
    raw = ScriptedSession()
    g, _scope = guarded("odoo_search_read", {"model": "ir.attachment", "domain": []},
                        session=raw, layer_a=False)
    error = raises(g.execute, "ir.attachment", "search_read", [[["name", "=", "x"]]])
    assert str(error) == refused("read", "ir.attachment", "attachment-pin", PIN_HINT)
    error = raises(g.execute, "ir.attachment", "search_read",
                   [[["res_model", "=", "certificate.key"]]])
    assert str(error) == refused("read", "certificate.key", "tier:secrets", SECRETS_HINT)
    assert raw.sent() == []


@pytest.mark.parametrize(("attachment", "allowed"), [
    (5, False),  # the field attachment of a certificate key
    (6, True),  # a partner's file
    (7, False),  # a file of a secrets model
    (8, True),  # an orphan file
    (99, False),  # unknown: cannot be verified
])
def test_an_attachment_named_by_id_is_checked_against_its_parent(attachment: int,
                                                                 allowed: bool) -> None:
    raw = ScriptedSession()
    error, text = call(server(raw), "odoo_read", model="ir.attachment", ids=[attachment],
                       fields=["name"])
    pre_read = raw.calls[0]
    assert pre_read == ("ir.attachment", "read", [[attachment]],
                        {"fields": ["res_model", "res_field"]}, None)
    if allowed:
        assert error is False and raw.sent() == [("ir.attachment", "read")] * 2
    else:
        assert error is True and text == refused(
            "read", "ir.attachment", "attachment-field",
            ATTACHMENT_FIELD.format(id=attachment, op="read"))
        assert raw.sent() == [("ir.attachment", "read")]


def test_changing_an_attachment_needs_write_on_its_parent() -> None:
    raw = ScriptedSession()
    opened = policy(models={"ir.attachment": {"unlink": True}})
    for tool, arguments, attachment in [
        ("odoo_write", {"model": "ir.attachment", "ids": [7], "values": {"name": "x"}}, 7),
        ("odoo_unlink", {"model": "ir.attachment", "ids": [5]}, 5),
        ("odoo_execute", {"model": "ir.attachment", "method": "copy", "ids": [5]}, 5),
        ("odoo_execute", {"model": "ir.attachment", "method": "generate_access_token",
                          "ids": [5]}, 5),
    ]:
        error, text = call(server(raw, p=opened), tool, **arguments)
        assert error is True and text == refused(
            "write", "ir.attachment", "attachment-field",
            ATTACHMENT_FIELD.format(id=attachment, op="write")), tool
    assert set(raw.sent()) == {("ir.attachment", "read")}  # the pre-reads only
    assert call(server(raw, p=opened), "odoo_write", model="ir.attachment", ids=[6],
                values={"name": "x"})[0] is False


def test_a_method_on_attachments_must_name_its_records_in_ids() -> None:
    raw = ScriptedSession()
    error, text = call(server(raw), "odoo_execute", model="ir.attachment",
                       method="generate_access_token", args=[[6]])
    assert error is True and "rule shape" in text and "in 'ids'" in text
    assert raw.sent() == []


@pytest.mark.parametrize(("values", "expected"), [
    ({"name": "x", "public": True}, ("create", "attachment-field", ATTACHMENT_CREATE)),
    ({"name": "x", "res_field": "datas"}, ("create", "attachment-field", ATTACHMENT_CREATE)),
    ({"name": "x", "res_model": "certificate.key", "res_id": 1}, None),
])
def test_a_new_attachment_is_never_public_nor_a_field_of_a_record(
        values: dict[str, Any], expected: tuple[str, str, str] | None) -> None:
    raw = ScriptedSession()
    error, text = call(server(raw), "odoo_create", model="ir.attachment", values=values)
    assert error is True
    if expected is None:
        assert text == refused("write", "certificate.key", "tier:secrets", SECRETS_HINT)
    else:
        op, rule, hint = expected
        assert text == refused(op, "ir.attachment", rule, hint)
    assert raw.sent() == []
    ok = call(server(raw), "odoo_create", model="ir.attachment",
              values={"name": "x", "res_model": "res.partner", "res_id": 3})
    assert ok[0] is False and raw.sent() == [("ir.attachment", "create")]


def test_an_existing_attachment_linked_through_a_command_is_checked() -> None:
    raw = ScriptedSession()
    error, text = call(server(raw), "odoo_write", model="res.partner", ids=[8],
                       values={"x_attachment_ids": [[4, 5]]})
    assert error is True and text == refused(
        "write", "ir.attachment", "attachment-field", ATTACHMENT_FIELD.format(id=5, op="write"))
    assert raw.sent() == [("ir.attachment", "read")]


def test_profile_full_turns_the_attachment_rules_off() -> None:
    raw = ScriptedSession()
    srv = server(raw, policy_profile="full")
    assert call(srv, "odoo_read", model="ir.attachment", ids=[5], fields=["datas"])[0] is False
    assert call(srv, "odoo_search_read", model="ir.attachment", domain=[])[0] is False
    assert raw.sent() == [("ir.attachment", "read"), ("ir.attachment", "search_read")]
    assert raw.call("ir.attachment", "search_read")[0] == [[]]


# --- the identity rule (design 4.6) -------------------------------------------------------

IDENTITY = ("contact {id} is the login identity of an Odoo user (its e-mail receives "
            "password-reset links), so changing its e-mail counts as a change to res.users; "
            "change it in Odoo's user settings")
IDENTITY_IMPORT = ("an import that updates existing contacts (an 'id' or '.id' column) cannot "
                   "set their 'email': a contact's e-mail can be the login identity of an Odoo "
                   "user (it receives password-reset links); change e-mails with odoo_write, "
                   "which checks each contact")


def test_the_email_of_a_user_contact_cannot_change_through_res_partner() -> None:
    raw = ScriptedSession()
    srv = server(raw)
    error, text = call(srv, "odoo_write", model="res.partner", ids=[8, 7],
                       values={"email": "new@attacker.example"})
    assert error is True and text == refused("write", "res.partner", "identity",
                                             IDENTITY.format(id=7))
    assert raw.calls == [("res.partner", "read", [[8, 7]],
                          {"fields": ["user_ids"], "context": {"active_test": False}}, None)]
    assert "attacker" not in text
    assert call(srv, "odoo_write", model="res.partner", ids=[8],
                values={"email": "new@example.com"})[0] is False
    assert raw.sent()[-1] == ("res.partner", "write")
    error, text = call(srv, "odoo_write", model="res.partner", ids=[8],
                       values={"child_ids": [[1, 7, {"email": "x@attacker.example"}]]})
    assert error is True and text == refused("write", "res.partner", "identity",
                                             IDENTITY.format(id=7))


def test_the_identity_rule_steps_aside_when_users_may_change() -> None:
    raw = ScriptedSession()
    opened = policy(models={"res.users": {"write": True, "reason": REASON}})
    assert call(server(raw, p=opened), "odoo_write", model="res.partner", ids=[7],
                values={"email": "new@example.com"})[0] is False
    assert raw.sent() == [("res.partner", "write")]  # no pre-read needed
    assert call(server(raw, policy_profile="full"), "odoo_write", model="res.partner", ids=[7],
                values={"email": "new@example.com"})[0] is False


@pytest.mark.parametrize(("columns", "refused_import"), [
    (["id", "email"], True),
    ([".id", "email"], True),
    (["child_ids/id", "child_ids/email"], True),
    (["name", "email"], False),  # creates contacts only
    (["id", "name"], False),
    (["parent_id/id", "email"], False),  # a link: the parent is not updated
])
def test_an_import_that_updates_contacts_cannot_set_their_email(columns: list[str],
                                                                refused_import: bool) -> None:
    raw = ScriptedSession()
    error, text = call(server(raw), "odoo_import", model="res.partner", fields=columns,
                       rows=[["a", "b"]])
    assert error is refused_import
    if refused_import:
        assert text == refused("write", "res.partner", "identity", IDENTITY_IMPORT)
        assert raw.sent() == []
    else:
        assert raw.sent() == [("res.partner", "load")]


def test_the_import_preview_checks_its_columns_before_its_wizard() -> None:
    raw = ScriptedSession(version=18)
    error, text = call(server(raw), "odoo_import_preview", model="res.partner",
                       fields=["id", "email"], rows=[["__import__.a", "a@example.com"]])
    assert error is True and text == refused("write", "res.partner", "identity", IDENTITY_IMPORT)
    assert raw.sent() == []
    error, text = call(server(raw), "odoo_import_preview", model="res.partner",
                       fields=["name", "bank_ids/acc_number"], rows=[["a", "b"]])
    assert error is True and text == path_text("load", "res.partner", "create",
                                               "res.partner.bank", "bank_ids/acc_number",
                                               "tier:security")
    assert raw.sent() == []


# --- the delegation link (design 4.4) -----------------------------------------------------

def delegation_text(op: str, model: str, field: str, parent: str, *,
                    profile: str = "standard") -> str:
    return refused(op, model, "delegation-link",
                   f"'{field}' would link {model} to an existing {parent} record and expose or "
                   f"change it through {model}; create the {model} with its own content instead",
                   profile=profile)


def test_the_link_field_of_a_delegating_model_cannot_be_set() -> None:
    raw = ScriptedSession()
    cases = [
        (server(raw, policy_profile="builder"), "odoo_create",
         {"model": "website.page", "values": {"name": "x", "view_id": 5}},
         delegation_text("create", "website.page", "view_id", "ir.ui.view", profile="builder")),
        (server(raw), "odoo_create",
         {"model": "product.document", "values": {"name": "x", "ir_attachment_id": 5}},
         delegation_text("create", "product.document", "ir_attachment_id", "ir.attachment")),
        (server(raw), "odoo_write",
         {"model": "product.template", "ids": [1],
          "values": {"product_document_ids": [[0, 0, {"ir_attachment_id": 5}]]}},
         delegation_text("create", "product.document", "ir_attachment_id", "ir.attachment")),
        (server(raw), "odoo_import",
         {"model": "product.document", "fields": ["name", "ir_attachment_id/id"],
          "rows": [["x", "base.attachment"]]},
         delegation_text("create", "product.document", "ir_attachment_id", "ir.attachment")),
    ]
    for srv, tool, arguments, expected in cases:
        error, text = call(srv, tool, **arguments)
        assert (error, text) == (True, expected), tool
    assert raw.sent() == []
    assert call(server(raw, policy_profile="full"), "odoo_create", model="product.document",
                values={"name": "x", "ir_attachment_id": 5})[0] is False


# --- context keys -------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["tracking_disable", "mail_notrack", "mail_create_nolog",
                                 "install_mode", "default_signup_token"])
def test_context_keys_outside_the_safe_list_are_refused(key: str) -> None:
    raw = ScriptedSession()
    g, _scope = guarded("odoo_search_read", {"model": "res.partner"}, session=raw)
    error = raises(g.execute, "res.partner", "search_read", [[]], {"context": {key: True}})
    assert str(error) == refused(
        "read", "res.partner", "context",
        f"context key '{key}' is not allowed through these tools (allowed: "
        f"{texts.CONTEXT_ALLOWED})")
    spec = {"partner_id": {"fields": {"name": {}}, "context": {key: True}}}
    g, _scope = guarded("odoo_execute", {"model": "sale.order", "method": "web_read",
                                         "ids": [1], "kwargs": {"specification": {}}},
                        session=raw)
    assert raises(g.execute, "sale.order", "web_read", [], {"specification": spec},
                  ids=[1]).rule == "context"
    assert raw.sent() == []


def test_safe_context_keys_and_plain_defaults_pass() -> None:
    raw = ScriptedSession()
    g, _scope = guarded("odoo_search_read", {"model": "res.partner"}, session=raw)
    context = {"lang": "es_MX", "tz": "UTC", "active_test": False, "default_name": "x",
               "read_group_expand": True}
    g.execute("res.partner", "search_read", [[]], {"context": context})
    assert raises(g.execute, "res.partner", "search_read", [[]],
                  {"context": {"default_name": {"nested": 1}}}).rule == "context"
    assert raises(g.execute, "res.partner", "search_read", [[]],
                  {"context": "lang=es"}).rule == "shape"
    full, _scope = guarded("odoo_search_read", {"model": "res.partner"}, session=raw,
                           p=Policy(profile_name="full"))
    full.execute("res.partner", "search_read", [[]], {"context": {"tracking_disable": True}})
    assert raw.sent() == [("res.partner", "search_read")] * 2


# --- failing closed -------------------------------------------------------------------------

UNVERIFIED = ("could not verify the related models of this call (fields_get failed); check "
              "that the Odoo user can read the field definitions of these models, then retry")


def test_a_path_whose_metadata_cannot_be_read_is_refused() -> None:
    raw = ScriptedSession(failing={"sale.order"})
    error, text = call(server(raw), "odoo_search_read", model="sale.order",
                       domain=[["partner_id.name", "=", "x"]])
    assert error is True and text == refused("read", "sale.order", "unverified", UNVERIFIED)
    error, text = call(server(raw), "odoo_write", model="sale.order", ids=[1],
                       values={"order_line": [[5]]})
    assert error is True and text == refused("write", "sale.order", "unverified", UNVERIFIED)
    assert raw.sent() == []


def test_a_bug_in_the_guard_refuses_the_call_without_echoing_anything(
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise KeyError("SECRET-MARKER-9")

    monkeypatch.setattr(GuardedSession, "_check_path", broken)
    raw = ScriptedSession()
    error, text = call(server(raw), "odoo_search_read", model="sale.order",
                       domain=[["name", "=", "x"]])
    assert error is True and text == (
        "internal error: the odoo-tools permission policy could not check a call of "
        "odoo_search_read (KeyError), so it was stopped before it reached Odoo (fail closed). "
        "This is a bug in odoo-tools; please report it to dev@transgenia.org.")
    assert raw.sent() == []
    assert "SECRET-MARKER-9" not in caplog.text


def test_a_predicate_that_cannot_read_the_call_does_not_hold() -> None:
    raw = ScriptedSession()
    g, _scope = guarded("odoo_version", {}, session=raw)
    error = raises(g.execute, "res.users", "has_group", "base.group_system")
    assert isinstance(error, PolicyEnvelopeError)
    assert raw.sent() == []


# --- name_get and api_doc ---------------------------------------------------------------------

def test_name_get_is_a_read_of_display_names() -> None:
    raw = ScriptedSession()
    g, scope = guarded("odoo_online_profile", {}, session=raw)
    assert g.name_get("res.company", [1]) == [[1, "res.company 1"]]
    assert scope.effective == ["read:res.company"]
    closed = policy(models={"res.company": {"read": False}})
    g, _scope = guarded("odoo_online_profile", {}, session=raw, p=closed)
    assert raises(g.name_get, "res.company", [1]).rule == "file:res.company"
    assert raw.sent() == [("res.company", "name_get")]


def test_api_doc_is_an_inspection_of_the_declared_model() -> None:
    raw = ScriptedSession()
    g, scope = guarded("odoo_api_catalog", {"model": "res.partner"}, session=raw)
    assert g.api_doc("res.partner") == {"model": "res.partner", "methods": {}}
    assert scope.effective == ["inspect:res.partner"]
    assert isinstance(raises(g.api_doc, "res.users"), PolicyEnvelopeError)


# --- live-shaped cases, against a scripted Odoo over JSON-2 ------------------------------------

@pytest.fixture
def fake() -> Any:
    odoo = FakeOdoo()
    try:
        yield odoo
    finally:
        odoo.close()


def _odoo(fake: FakeOdoo, **settings: Any) -> McpServer:
    def orm(model: str, method: str, body: dict[str, Any]) -> Any:
        if method == "search_count":
            return 0
        if method == "fields_get":
            return ScriptedSession().fields.get(model, {})
        if method in ("search_read", "read", "web_read"):
            return []
        return True

    fake.serve_version()
    fake.serve_json2(orm)
    return McpServer(Settings(url=fake.url, db="db", login="admin", api_key=KEY, timeout=5,
                              **settings))


def _changes(fake: FakeOdoo) -> list[str]:
    """The /json/2 calls that are not reads (the sign-in and the probes are reads)."""
    return [r["path"] for r in fake.calls("/json/2/") if r["path"].rsplit("/", 1)[1]
            not in READ_METHODS]


LIVE_SHAPED = [
    ("odoo_write", {"model": "res.partner", "ids": [8],
                    "values": {"user_ids": [[1, 4, {"groups_id": [[4, 1]]}]]}},
     relational("write", "res.partner", "write", "res.users", "user_ids", 1, "tier:security")),
    ("odoo_write", {"model": "res.partner", "ids": [8],
                    "values": {"bank_ids": [[1, 3, {"acc_number": "MX00 ATTACKER"}]]}},
     relational("write", "res.partner", "write", "res.partner.bank", "bank_ids", 1,
                "tier:security")),
    ("odoo_write", {"model": "sale.order", "ids": [1], "values": {"order_line": [[5]]}},
     relational("write", "sale.order", "unlink", "sale.order.line", "order_line", 5,
                "profile:standard")),
    ("odoo_execute", {"model": "payment.transaction", "method": "web_read", "ids": [1],
                      "kwargs": {"specification": {"provider_id": {"fields": {"name": {}}}}}},
     path_text("web_read", "payment.transaction", "read", "payment.provider",
               "provider_id.name", "tier:secrets")),
    ("odoo_execute", {"model": "payment.transaction", "method": "export_data", "ids": [1],
                      "kwargs": {"fields_to_export": ["provider_id/name"]}},
     path_text("export_data", "payment.transaction", "read", "payment.provider",
               "provider_id.name", "tier:secrets")),
    ("odoo_execute", {"model": "mail.template", "method": "export_data", "ids": [1],
                      "kwargs": {"fields_to_export": ["mail_server_id/smtp_pass"]}}, "outbound"),
    ("odoo_write", {"model": "website.page", "ids": [1], "values": {"arch": "<t/>"}}, None),
]


@pytest.mark.parametrize(("tool", "arguments", "expected"), LIVE_SHAPED)
def test_live_shaped_cases_never_reach_odoo(fake: FakeOdoo, tool: str,
                                            arguments: dict[str, Any],
                                            expected: str | None) -> None:
    error, text = call(_odoo(fake), tool, **arguments)
    assert error is True
    if expected is None:
        assert "rule tier:customization, through ir.ui.view" in text
    elif expected == "outbound":
        assert "rule tier:outbound" in text
    else:
        assert text == expected
    assert _changes(fake) == []
    assert not [r for r in fake.calls("/json/2/") if r["path"].endswith(
        ("/web_read", "/export_data"))]


def test_a_certificate_key_attachment_is_refused_by_id_against_odoo(fake: FakeOdoo) -> None:
    def orm(model: str, method: str, body: dict[str, Any]) -> Any:
        if method == "search_count":
            return 0
        if (model, method) == ("ir.attachment", "read") and body.get("fields") == [
                "res_model", "res_field"]:
            return [{"id": 5, "res_model": "certificate.key", "res_field": "content"}]
        raise AssertionError(f"{model}.{method} reached Odoo")

    fake.serve_version()
    fake.serve_json2(orm)
    srv = McpServer(Settings(url=fake.url, db="db", login="admin", api_key=KEY, timeout=5))
    error, text = call(srv, "odoo_read", model="ir.attachment", ids=[5], fields=["datas"])
    assert error is True and text == refused("read", "ir.attachment", "attachment-field",
                                             ATTACHMENT_FIELD.format(id=5, op="read"))
    error, text = call(srv, "odoo_search_read", model="ir.attachment",
                       domain=[["res_model", "=", "certificate.key"]])
    assert error is True and "rule tier:secrets" in text and "Nothing was sent" in text
    assert KEY not in text


def test_a_refusal_after_sign_in_is_counted_and_says_layer_b(fake: FakeOdoo) -> None:
    manager_calls: list[str] = []
    srv = _odoo(fake)
    original = srv.manager.record_tool_call

    def counting(name: str) -> None:
        manager_calls.append(name)
        original(name)

    srv.manager.record_tool_call = counting  # type: ignore[method-assign]
    error, text = call(srv, *LIVE_SHAPED[0][:1], **LIVE_SHAPED[0][1])
    assert error is True and B in text and manager_calls == ["odoo_write"]


def test_the_refusal_texts_carry_no_value_of_the_call() -> None:
    raw = ScriptedSession()
    error, text = call(server(raw), "odoo_write", model="res.partner", ids=[8],
                       values={"bank_ids": [[0, 0, {"acc_number": "SECRET-MARKER-7"}]]})
    assert error is True and "SECRET-MARKER-7" not in text
    assert text.endswith(f"; {NO_WORKAROUND}") and SEP in text
    assert issubclass(PolicyDenied, PolicyError) and issubclass(PolicyEnvelopeError, PolicyError)


def test_allowed_calls_reach_odoo_as_the_tool_sent_them(fake: FakeOdoo) -> None:
    received: list[tuple[str, str, dict[str, Any]]] = []

    def orm(model: str, method: str, body: dict[str, Any]) -> Any:
        received.append((model, method, body))
        if method == "search_count":
            return 0
        if method == "fields_get":
            return ScriptedSession().fields.get(model, {})
        if (model, method) == ("res.partner", "search_read"):
            return [{"id": 3, "name": "Acme", "signup_token": "TOKEN-DO-NOT-LEAK"}]
        if method in ("search_read", "read"):
            return [{"id": 1, "name": "S1"}]
        return True

    fake.serve_version()
    fake.serve_json2(orm)
    srv = McpServer(Settings(url=fake.url, db="db", login="admin", api_key=KEY, timeout=5))
    lines = [[0, 0, {"name": "Chair", "product_id": 5}], [1, 9, {"price_unit": 2.5}]]
    assert call(srv, "odoo_write", model="sale.order", ids=[1],
                values={"order_line": lines, "tag_ids": [[6, 0, [1, 2]]]})[0] is False
    error, text = call(srv, "odoo_search_read", model="sale.order",
                       domain=[["partner_id.country_id.code", "=", "MX"]], fields=["name"])
    assert error is False and "policy_withheld_fields" not in text
    error, text = call(srv, "odoo_search_read", model="res.partner")
    assert error is False and "TOKEN-DO-NOT-LEAK" not in text
    assert json.loads(text)["policy_withheld_fields"] == ["res.partner.signup_token"]
    assert call(srv, "odoo_search_read", model="ir.attachment",
                domain=[["res_model", "=", "res.partner"]])[0] is False
    calls = {(model, method): body for model, method, body in received}
    assert calls[("sale.order", "write")] == {"ids": [1], "vals": {
        "order_line": lines, "tag_ids": [[6, 0, [1, 2]]]}}
    # the guard's metadata reads (sale.order once: the session caches it) ...
    metadata = [model for model, method, _body in received if method == "fields_get"]
    assert metadata == ["sale.order", "res.partner"]
    # ... and the attachment search Odoo received, pinned
    assert calls[("ir.attachment", "search_read")]["domain"] == [
        ["res_field", "=", False], ["res_model", "=", "res.partner"]]
