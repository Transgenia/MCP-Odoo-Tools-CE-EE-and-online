# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The permission policy in the MCP server: listing, Layer A, texts and outputs (design 9.5).

Layer A runs in ``McpServer.call_tool`` before any session exists, so every
refusal here is checked against a connection manager that records whether a
session was asked for: a refused call must never sign in, and is not counted.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fake_odoo_http import FakeOdoo

from odoo_mcp.compat import EnvFacts
from odoo_mcp.config import Settings
from odoo_mcp.errors import CompatError, OdooFault, PolicyDenied
from odoo_mcp.policy.model import PROFILES, Policy
from odoo_mcp.policy.texts import (
    ADMIN_WARNING,
    CONTEXT_ALLOWED,
    DESCRIPTION_LIMIT,
    DESCRIPTION_SUFFIXES,
    INSTRUCTIONS_LIMIT,
    attachment_field,
    delegation_link,
    description_suffix,
    disabled,
    envelope,
    identity,
    read_only_tool,
    relational,
)
from odoo_mcp.policy.tiers import SAFE_CONTEXT_KEYS
from odoo_mcp.registry import registry
from odoo_mcp.server import McpServer, check_readonly, serve
from odoo_mcp.support import INSTRUCTIONS

SEP = " \u2014 "  # CompatError joins a message and its remedy with it
A = "Nothing was sent to Odoo."
NO_WORKAROUND = "do not use another tool to do the same thing."
KEY = "K3Y-POLICY-DO-NOT-LEAK-0123456789abcdef"
STANDARD_HIDDEN = ["odoo_unlink", "odoo_add_field", "odoo_add_automation"]
WRITE_TOOLS = {t.name for t in registry.all() if not t.read_only}


class Manager:
    """Records whether a session was built and which calls were counted."""

    def __init__(self, session: Any = None) -> None:
        self.session = session
        self.built = 0
        self.calls: list[str] = []

    def default(self) -> Any:
        self.built += 1
        if self.session is None:
            raise AssertionError("a session was built")
        return self.session

    def record_tool_call(self, name: str) -> None:
        self.calls.append(name)

    def connections(self) -> list[dict[str, str]]:
        return []


class Session:
    """An Odoo 17 session that answers the calls of odoo_list_models and
    odoo_access_check, and the administrator probe of odoo_version."""

    def __init__(self, *, version: int = 17, models: list[str] | None = None,
                 allowed: bool = True, admin: Any = False) -> None:
        self.uid = 2
        self._facts = EnvFacts(version=version, edition="community", deployment="onprem",
                               raw_version=f"{version}.0")
        self.transport = SimpleNamespace(active="jsonrpc(auto)", transport_notice=None)
        self.models = models or []
        self.allowed = allowed
        self.admin = admin
        self.calls: list[tuple[str, str, Any, Any]] = []

    def facts(self) -> EnvFacts:
        return self._facts

    def execute(self, model: str, method: str, args: Any = None, kwargs: Any = None, *,
                ids: Any = None, transports: Any = None) -> Any:
        self.calls.append((model, method, args, ids))
        if (model, method) == ("ir.model", "search_read"):
            return [{"model": name, "name": name.title()} for name in self.models]
        if method in ("check_access_rights", "has_access"):
            return self.allowed
        if (model, method) == ("res.users", "has_group"):
            if args == ["base.group_system"]:
                if isinstance(self.admin, Exception):
                    raise self.admin
                return self.admin
            return True
        raise AssertionError(f"unexpected call {model}.{method}")


def server(manager: Manager | None = None, **settings: Any) -> McpServer:
    return McpServer(Settings(**settings), manager=manager or Manager())  # type: ignore[arg-type]


def call(srv: McpServer, tool: str, /, **arguments: Any) -> tuple[bool, str]:
    result = srv.call_tool({"name": tool, "arguments": arguments})
    return result["isError"], result["content"][0]["text"]


def listed(srv: McpServer) -> list[str]:
    return [t["name"] for t in srv.list_tools()["tools"]]


def write_policy(tmp_path: Path, document: Any) -> str:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    return str(path)


# --- tools/list per profile ---------------------------------------------------------

@pytest.mark.parametrize(("settings", "count", "hidden"), [
    ({"policy_profile": "readonly"}, 19, WRITE_TOOLS),
    ({"policy_profile": "standard"}, 25, set(STANDARD_HIDDEN)),
    ({}, 25, set(STANDARD_HIDDEN)),
    ({"policy_profile": "builder"}, 28, set()),
    ({"policy_profile": "full"}, 28, set()),
    ({"policy_profile": "full", "readonly": True}, 19, WRITE_TOOLS),
])
def test_tools_list_per_profile(settings: dict[str, Any], count: int, hidden: set[str]) -> None:
    names = listed(server(**settings))
    assert len(names) == count
    assert set(names) == {t.name for t in registry.all()} - hidden


def test_the_server_reads_the_policy_once_or_takes_the_one_it_is_given() -> None:
    srv = server(policy_profile="builder")
    assert srv.policy.profile_name == "builder" and srv.policy.digest == Policy(
        profile_name="builder").digest
    given = Policy(profile_name="readonly")
    injected = McpServer(Settings(), manager=Manager(), policy=given)  # type: ignore[arg-type]
    assert injected.policy is given and len(listed(injected)) == 19


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_a_tool_is_listed_exactly_when_check_tool_lets_it_run(profile: str) -> None:
    for readonly in (False, True):
        srv = server(policy_profile=profile, readonly=readonly)
        visible = set(listed(srv))
        for tool in registry.all():
            try:
                srv.policy.check_tool(tool)
                runs = True
            except PolicyDenied:
                runs = False
            assert runs is (tool.name in visible), (profile, readonly, tool.name)


def hidden_text(tool: str, op: str) -> str:
    return (f"{tool} is not available: the odoo-tools permission policy (profile 'standard') "
            f"allows '{op}' on no model. {A}{SEP}the user can change this in the plugin options "
            f"'Permission profile' or 'Permission policy file'; {NO_WORKAROUND}")


def test_a_hidden_tool_called_by_name_is_refused_uncounted_and_never_signs_in() -> None:
    manager = Manager()
    srv = server(manager)
    assert call(srv, "odoo_unlink", model="res.partner", ids=[1]) == (
        True, hidden_text("odoo_unlink", "unlink"))
    assert call(srv, "odoo_add_field", model="res.partner")[1] == hidden_text(
        "odoo_add_field", "schema")
    # A refused fixed touch is named first, as tools/list checks it first.
    assert call(srv, "odoo_add_automation", model="res.partner")[1] == refused(
        "create", "base.automation", "tier:customization", CUSTOMIZATION_HINT)
    # check_tool runs before the arguments are validated: no "Input validation error"
    assert call(srv, "odoo_unlink")[1].startswith("odoo_unlink is not available")
    assert manager.built == 0 and manager.calls == []


def test_a_disabled_tool_says_so(tmp_path: Path) -> None:
    path = write_policy(tmp_path, {"version": 1, "tools": {"disabled": ["odoo_import"]}})
    manager = Manager()
    srv = server(manager, policy_file=path)
    assert "odoo_import" not in listed(srv) and "odoo_import_preview" in listed(srv)
    error, text = call(srv, "odoo_import", model="res.partner", fields=["name"], rows=[["x"]])
    assert error is True
    assert text == (f"odoo_import is disabled by the odoo-tools permission policy file ({path}). "
                    f"{A}{SEP}the user can change this in the policy file; {NO_WORKAROUND}")
    assert manager.built == 0 and manager.calls == []


def test_read_only_mode_keeps_its_own_message_first() -> None:
    srv = server(readonly=True, policy_profile="full")
    error, text = call(srv, "odoo_create", model="res.partner", values={})
    assert error is True and "ODOO_READONLY=1" in text
    # check_tool says the same words, should it ever run first
    with pytest.raises(CompatError) as expected:
        check_readonly(Settings(readonly=True), registry.get("odoo_create"))
    assert str(read_only_tool("odoo_create")) == str(expected.value)


# --- Layer A refusals, exact texts ---------------------------------------------------

def refused(op: str, model: str, rule: str, hint: str, *, profile: str = "standard",
            workaround: bool = True) -> str:
    tail = f"; {NO_WORKAROUND}" if workaround else ""
    return (f"the odoo-tools permission policy refuses '{op}' on '{model}' (profile '{profile}', "
            f"rule {rule}). {A}{SEP}{hint}{tail}")


SECURITY_HINT = ("users, groups, access rules, modules, API keys, bank accounts, chatter history "
                 "and fiscal sequences are read-only outside profile 'full' unless the policy "
                 "file names the model exactly, with a reason")
CUSTOMIZATION_HINT = ("fields, views, automations and other ir.* records need profile 'builder', "
                      "or an entry naming the model exactly, with a reason")
NEVER_HINT = ("odoo-tools never creates, changes or revokes API keys and never uninstalls "
              "modules, in any profile; do this in Odoo itself")
PIN_HINT = ("generic access to ir.attachment must name the parent model: add [\"res_model\", "
            "\"=\", \"<model>\"] to the domain and do not filter on res_field, or use "
            "odoo_record_documents")


def field_hint(name: str, model: str) -> str:
    return (f"field '{name}' of '{model}' looks like a credential or token and is not read, "
            "written, filtered, grouped or sorted on through these tools; read other fields, or "
            "release it with fields.allow in the policy file")


LAYER_A_CASES = [
    ("odoo_write", {"model": "res.users", "ids": [2], "values": {"name": "x"}},
     refused("write", "res.users", "tier:security", SECURITY_HINT)),
    ("odoo_search_read", {"model": "ir.config_parameter"},
     refused("read", "ir.config_parameter", "tier:secrets",
             "this model holds credentials or acts as one; only an entry naming it exactly, "
             "with a reason, in the policy file opens it")),
    ("odoo_create", {"model": "mail.template", "values": {"name": "x"}},
     refused("create", "mail.template", "tier:outbound",
             "this model sends e-mail, SMS, letters or share links, or decides what is sent; "
             "only an entry naming it exactly, with a reason, opens it")),
    ("odoo_create", {"model": "ir.ui.view", "values": {"name": "x"}},
     refused("create", "ir.ui.view", "tier:customization", CUSTOMIZATION_HINT)),
    ("odoo_write", {"model": "website.page", "ids": [1], "values": {"arch": "<t/>"}},
     refused("write", "website.page",
             "tier:customization, through ir.ui.view, which website.page delegates to",
             CUSTOMIZATION_HINT)),
    ("odoo_execute", {"model": "res.users.apikeys", "method": "unlink", "ids": [1]},
     refused("call", "res.users.apikeys", "never:api-keys", NEVER_HINT)),
    ("odoo_execute", {"model": "ir.module.module", "method": "button_immediate_uninstall",
                      "ids": [1]},
     refused("call", "ir.module.module", "never:module-uninstall", NEVER_HINT)),
    ("odoo_execute", {"model": "res.partner", "method": "message_post", "ids": [1],
                      "kwargs": {"body": "Hello", "partner_ids": [7]}},
     refused("call", "res.partner", "outbound-method",
             "'message_post' sends e-mail, SMS or notifications; profile 'standard' allows "
             "internal notes only (message_post with subtype_xmlid 'mail.mt_note' and no "
             "partner_ids). An entry naming 'res.partner' exactly with \"call\": "
             "[\"message_post\"] and a reason allows it")),
    ("odoo_execute", {"model": "res.partner", "method": "unlink", "ids": [1]},
     refused("unlink", "res.partner", "profile:standard",
             "profile 'standard' does not delete: archive instead (odoo_write {\"active\": "
             "false}) where the model has an active field, or ask the user to allow unlink")),
    ("odoo_search_read", {"model": "res.partner", "fields": ["name", "signup_token"]},
     refused("read", "res.partner", "field", field_hint("signup_token", "res.partner"))),
    ("odoo_search_read", {"model": "sale.order",
                          "domain": [["partner_id.signup_token", "=like", "a%"]]},
     refused("read", "sale.order", "field", field_hint("partner_id.signup_token", "sale.order"))),
    ("odoo_read_group", {"model": "res.partner", "fields": ["name"], "groupby": ["name"],
                         "orderby": "access_token desc"},
     refused("read", "res.partner", "field", field_hint("access_token", "res.partner"))),
    ("odoo_write", {"model": "res.company", "ids": [1],
                    "values": {"l10n_mx_edi_pac_password": "x"}},
     refused("write", "res.company", "field",
             field_hint("l10n_mx_edi_pac_password", "res.company"))),
    ("odoo_translate_get", {"model": "res.partner", "id": 1, "field": "signup_url",
                            "lang": "es_MX"},
     refused("read", "res.partner", "field", field_hint("signup_url", "res.partner"))),
    ("odoo_import", {"model": "res.partner", "fields": ["name", "user_ids/password"],
                     "rows": [["a", "b"]]},
     refused("create", "res.partner", "field", field_hint("user_ids/password", "res.partner"))),
    ("odoo_search_read", {"model": "ir.attachment", "domain": [["name", "ilike", "cfdi"]]},
     refused("read", "ir.attachment", "attachment-pin", PIN_HINT)),
    ("odoo_search_count", {"model": "ir.attachment",
                           "domain": ["|", ["res_model", "=", "res.partner"],
                                      ["res_model", "=", "sale.order"]]},
     refused("read", "ir.attachment", "attachment-pin", PIN_HINT)),
    ("odoo_search_read", {"model": "ir.attachment",
                          "domain": [["res_model", "=", "res.partner"],
                                     ["res_field", "!=", False]]},
     refused("read", "ir.attachment", "attachment-pin", PIN_HINT)),
    ("odoo_execute", {"model": "ir.attachment", "method": "search_read",
                      "kwargs": {"domain": [["res_model", "=", "certificate.key"]]}},
     refused("read", "certificate.key", "tier:secrets",
             "this model holds credentials or acts as one; only an entry naming it exactly, "
             "with a reason, in the policy file opens it")),
    ("odoo_execute", {"model": "res.partner", "method": "write", "ids": [1],
                      "kwargs": {"vals": {"name": "x"}, "context": {"tracking_disable": True}}},
     refused("call", "res.partner", "context",
             f"context key 'tracking_disable' is not allowed through these tools (allowed: "
             f"{CONTEXT_ALLOWED})")),
    ("odoo_execute", {"model": "res.partner", "method": "create",
                      "kwargs": {"vals_list": [{"name": "x"}],
                                 "context": {"default_password": "x"}}},
     refused("call", "res.partner", "context",
             f"context key 'default_password' is not allowed through these tools (allowed: "
             f"{CONTEXT_ALLOWED})")),
    ("odoo_execute", {"model": "res.partner", "method": "search_read", "args": [[]],
                      "kwargs": {"bogus": 1}},
     refused("call", "res.partner", "shape",
             "the arguments of this search_read call cannot be checked (takes no keyword "
             "'bogus'); use the dedicated tool (odoo_create, odoo_write, odoo_search_read) or "
             "pass the arguments by name", workaround=False)),
    ("odoo_search_read", {"model": "res.partner", "domain": [["name", "=", "x"], "?"]},
     refused("read", "res.partner", "shape",
             "the arguments of this odoo_search_read call cannot be checked (a domain holds an "
             "unknown operator); correct them")),
    ("odoo_execute", {"model": "res.partner", "method": "_compute_display_name"},
     refused("call", "res.partner", "invalid-name",
             "the method name is not a public method name (a letter first, then letters, digits "
             "and '_'; Odoo refuses private methods over RPC)")),
    ("odoo_add_field", {"model": "res.partner", "name": "x_key", "label": "Key",
                        "field_type": "many2one", "relation": "payment.provider"},
     None),  # hidden under standard: the schema operation is allowed nowhere
]


@pytest.mark.parametrize(("name", "arguments", "expected"), LAYER_A_CASES)
def test_layer_a_refusals(name: str, arguments: dict[str, Any], expected: str | None) -> None:
    manager = Manager()
    srv = server(manager)
    error, text = call(srv, name, **arguments)
    assert error is True
    if expected is not None:
        assert text == expected
    assert manager.built == 0 and manager.calls == []  # never signed in, never counted


def test_an_invalid_model_name_is_described_not_echoed() -> None:
    marker = "SECRET-MARKER-41 X"
    error, text = call(server(), "odoo_search", model=marker)
    assert error is True and marker not in text
    assert text == (
        f"the odoo-tools permission policy refuses 'read' on this model (profile 'standard', "
        f"rule invalid-name). {A}{SEP}the model name is not a valid Odoo model name (lowercase "
        f"letters, digits, '_' and '.', e.g. res.partner); {NO_WORKAROUND}")
    _, context = call(server(), "odoo_execute", model="res.partner", method="action_x",
                      kwargs={"context": {marker: 1}})
    assert "context key of that name is not allowed" in context and marker not in context


def test_a_file_rule_and_a_method_list_name_themselves(tmp_path: Path) -> None:
    path = write_policy(tmp_path, {"version": 1, "models": {
        "hr.*": {"read": False}, "sale.order": {"call": ["action_confirm", "action_cancel"]}}})
    srv = server(policy_file=path)
    assert call(srv, "odoo_search_read", model="hr.employee")[1] == refused(
        "read", "hr.employee", "file:hr.*", "the policy file rule 'hr.*' refuses it")
    assert call(srv, "odoo_execute", model="sale.order", method="action_draft", ids=[1])[1] == (
        refused("call", "sale.order", "file:sale.order",
                "method 'action_draft' is not among the methods allowed on 'sale.order' "
                "(action_cancel, action_confirm)"))


def test_an_alias_names_the_rule_it_came_through(tmp_path: Path) -> None:
    path = write_policy(tmp_path, {"version": 1, "models": {"account.invoice": {"read": False}}})
    assert call(server(policy_file=path), "odoo_search_read", model="account.move")[1] == refused(
        "read", "account.move", "file:account.invoice, alias of account.move",
        "the policy file rule 'account.invoice' refuses it")


def test_a_withheld_field_of_the_file_says_so(tmp_path: Path) -> None:
    path = write_policy(tmp_path, {"version": 1, "fields": {"withhold": ["*.vat"]}})
    for profile in ("standard", "full"):  # fields.withhold applies in profile full too
        text = call(server(policy_file=path, policy_profile=profile), "odoo_read",
                    model="res.partner", ids=[1], fields=["vat"])[1]
        assert text == refused(
            "read", "res.partner", "field",
            "field 'vat' of 'res.partner' is withheld by the policy file (fields.withhold) and is "
            "not read, written, filtered, grouped or sorted on through these tools; read other "
            "fields", profile=profile)


class Recorder:
    """A session that answers every call with an empty list and records it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def facts(self) -> EnvFacts:
        return EnvFacts(version=17, edition="community", deployment="onprem", raw_version="17.0")

    def execute(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((model, method))
        return []


def test_profile_full_turns_the_rules_off_but_keeps_never_and_the_name_checks() -> None:
    session = Recorder()
    srv = server(Manager(session=session), policy_profile="full")
    # withheld fields, the attachment pin and the context rule are off: these reach Odoo
    for tool, arguments in [
        ("odoo_search_read", {"model": "res.partner", "fields": ["signup_token"]}),
        ("odoo_search_read", {"model": "ir.attachment", "domain": []}),
        ("odoo_execute", {"model": "res.partner", "method": "action_x",
                          "kwargs": {"context": {"tracking_disable": True}}}),
    ]:
        assert call(srv, tool, **arguments)[0] is False
    assert session.calls == [("res.partner", "search_read"), ("ir.attachment", "search_read"),
                             ("res.partner", "action_x")]
    assert call(srv, "odoo_execute", model="res.users.apikeys", method="unlink",
                ids=[1])[1].startswith(
        "the odoo-tools permission policy refuses 'call' on 'res.users.apikeys' (profile "
        "'full', rule never:api-keys)")
    assert "invalid-name" in call(srv, "odoo_search", model="Res.Partner")[1]


ALLOWED_CASES = [
    # an internal note notifies nobody by e-mail
    ("odoo_execute", {"model": "crm.lead", "method": "message_post", "ids": [3],
                      "kwargs": {"body": "Called the customer", "subtype_xmlid": "mail.mt_note"}}),
    ("odoo_execute", {"model": "sale.order", "method": "action_confirm", "ids": [1],
                      "kwargs": {"context": {"lang": "es_MX", "default_note": "x"}}}),
    ("odoo_search_read", {"model": "ir.attachment",
                          "domain": [["res_model", "=", "res.partner"], ["res_id", "=", 3]]}),
    ("odoo_search_read", {"model": "ir.attachment",
                          "domain": ["&", ["res_model", "in", ["sale.order", False]],
                                     ["name", "ilike", "pdf"]]}),
    ("odoo_search_read", {"model": "res.partner", "fields": ["name", "payment_token_id"]}),
    ("odoo_write", {"model": "res.partner", "ids": [1], "values": {"comment": "x"}}),
    ("odoo_record_documents", {"model": "account.move", "res_id": 7}),
    ("odoo_fields_get", {"model": "res.users"}),
]


@pytest.mark.parametrize(("name", "arguments"), ALLOWED_CASES)
def test_layer_a_lets_allowed_calls_reach_the_handler(name: str, arguments: dict[str, Any]
                                                      ) -> None:
    manager = Manager(session=SimpleNamespace())  # any use of it fails the call, not Layer A
    srv = server(manager)
    _error, text = call(srv, name, **arguments)  # the fake session fails the handler
    assert manager.built == 1 and manager.calls == [name]
    assert "permission policy" not in text


def test_the_context_text_lists_every_safe_key() -> None:
    listed_keys = {key.strip() for key in CONTEXT_ALLOWED.split(",")}
    assert listed_keys - {"default_<field> with a plain value"} == SAFE_CONTEXT_KEYS


def test_the_envelope_text() -> None:
    exc = envelope("odoo_read", "res.partner", "unlink")
    assert (exc.rule, exc.layer) == ("envelope", "B")
    assert str(exc) == (
        "internal error: odoo_read tried res.partner.unlink, which its permission mapping does "
        "not declare. The call was stopped before it reached Odoo. This is a bug in odoo-tools; "
        "please report it to dev@transgenia.org.")


B = ("The call was stopped before Odoo ran it: nothing was changed and no record data was "
     "returned.")


def test_the_texts_of_the_rules_the_guarded_session_applies() -> None:
    p = Policy()
    cases = [
        (relational(p, method="write", model="res.partner", op="write", comodel="res.users",
                    field="user_ids", command=1, rule="tier:security"),
         "write", "res.users", "relational",
         ("this write on 'res.partner' also writes 'res.users' through field 'user_ids' "
          "(command 1), and the policy refuses 'write' on 'res.users' (tier:security)")),
        (attachment_field(p, "read", 42), "read", "ir.attachment", "attachment-field",
         ("attachment 42 stores a field of a record, or belongs to a model the policy does not "
          "let you read; use odoo_record_documents for a record's files")),
        (identity(p, 7), "write", "res.partner", "identity",
         ("contact 7 is the login identity of an Odoo user (its e-mail receives password-reset "
          "links), so changing its e-mail counts as a change to res.users; change it in Odoo's "
          "user settings")),
        (delegation_link(p, "create", "product.document", "ir_attachment_id", "ir.attachment"),
         "create", "product.document", "delegation-link",
         ("'ir_attachment_id' would link product.document to an existing ir.attachment record "
          "and expose or change it through product.document; create the product.document with "
          "its own content instead")),
    ]
    for exc, op, model, rule, hint in cases:
        assert (exc.rule, exc.layer) == (rule, "B")
        assert str(exc) == (
            f"the odoo-tools permission policy refuses '{op}' on '{model}' (profile 'standard', "
            f"rule {rule}). {B}{SEP}{hint}; {NO_WORKAROUND}")


def test_the_disabled_text_keeps_the_path_on_one_line() -> None:
    assert "(/etc/odoo?tools/policy.json)" in str(disabled("odoo_import",
                                                           "/etc/odoo\ntools/policy.json"))


def test_a_bug_in_the_policy_check_refuses_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(self: Policy, tool: Any, arguments: Any) -> Any:
        raise RuntimeError("bug")

    monkeypatch.setattr(Policy, "check", broken)
    manager = Manager()
    error, text = call(server(manager), "odoo_search", model="res.partner")
    assert error is True and "refused (fail closed)" in text and manager.built == 0


# --- what the agent is told before it calls -------------------------------------------

@pytest.mark.parametrize("profile", sorted(PROFILES))
@pytest.mark.parametrize("readonly", [False, True])
def test_the_instructions_line(profile: str, readonly: bool) -> None:
    srv = server(policy_profile=profile, readonly=readonly)
    text = srv.initialize({})["instructions"]
    assert text.startswith(INSTRUCTIONS)
    line = text[len(INSTRUCTIONS):].strip()
    assert "\n" not in line and len(line) < INSTRUCTIONS_LIMIT
    assert line.startswith(f"Permission policy for this connection: profile '{profile}' "
                           f"({srv.policy.digest}).")
    assert line.endswith("never try another tool or the shell to get the same result.")
    hidden = [t.name for t in registry.all() if not srv.policy.tool_visible(t)]
    if not hidden:
        assert "Not listed" not in line
    elif len(hidden) <= 3:
        assert f"Not listed because the policy forbids them: {', '.join(hidden)}." in line
    else:
        assert f"Not listed because the policy forbids them: {len(hidden)} tools" in line
    assert ("Read-only mode is on." in line) is readonly


def test_the_instructions_line_of_the_default_profile() -> None:
    srv = server()
    line = srv.initialize({})["instructions"][len(INSTRUCTIONS):].strip()
    assert line == (
        f"Permission policy for this connection: profile 'standard' ({srv.policy.digest}). Not "
        "listed because the policy forbids them: odoo_unlink, odoo_add_field, "
        "odoo_add_automation. A refusal that names the permission policy is final: tell the "
        "user, who can change it in the plugin options; never try another tool or the shell to "
        "get the same result.")


def test_the_instructions_line_names_a_policy_file(tmp_path: Path) -> None:
    path = write_policy(tmp_path, {"version": 1, "models": {"*": {"call": False}}})
    srv = server(policy_file=path)
    assert (f"profile 'standard' plus a policy file ({srv.policy.digest})"
            in srv.initialize({})["instructions"])


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_the_description_suffix(profile: str) -> None:
    srv = server(policy_profile=profile)
    for entry in srv.list_tools()["tools"]:
        tool = registry.get(entry["name"])
        assert entry["description"].startswith(tool.description)
        suffix = entry["description"][len(tool.description):]
        assert len(suffix) <= DESCRIPTION_LIMIT
        takes_model = "model" in tool.input_schema.get("properties", {})
        assert suffix == (DESCRIPTION_SUFFIXES.get(profile, "") if takes_model else "")
    assert description_suffix(srv.policy) == DESCRIPTION_SUFFIXES.get(profile, "")
    assert all(len(text) <= DESCRIPTION_LIMIT for text in DESCRIPTION_SUFFIXES.values())


def test_the_annotations_state_destructive_hint_for_every_write_tool() -> None:
    tools = {t["name"]: t["annotations"] for t in server(policy_profile="full").list_tools()["tools"]}
    assert {name: hints.get("destructiveHint") for name, hints in tools.items()
            if not hints["readOnlyHint"]} == {
        "odoo_create": False, "odoo_write": True, "odoo_unlink": True, "odoo_execute": True,
        "odoo_translate_set": True, "odoo_import_preview": False, "odoo_import": True,
        "odoo_add_field": False, "odoo_add_automation": True}
    assert all(set(hints) == {"readOnlyHint"} for hints in tools.values() if hints["readOnlyHint"])


# --- locked mode ---------------------------------------------------------------------

def test_a_locked_policy_lists_odoo_version_alone_and_explains_itself(tmp_path: Path) -> None:
    path = write_policy(tmp_path, {"version": 1, "models": {"res.partner": {"read": "yes"}}})
    manager = Manager()
    srv = server(manager, policy_file=path)
    assert srv.policy.locked and srv.policy.error_code == "E11"
    assert listed(srv) == ["odoo_version"]
    error, text = call(srv, "odoo_version")
    assert error is False
    payload = json.loads(text)
    assert payload["policy"]["error"] == srv.policy.error
    assert payload["policy"]["error_code"] == "E11" and payload["policy"]["digest"] is None
    assert payload["note"] == str(srv.policy.lock_error())
    lock = str(srv.policy.lock_error())
    assert call(srv, "odoo_search_read", model="res.partner") == (True, lock)
    assert call(srv, "odoo_report", report_name="x", ids=[1]) == (True, lock)
    # odoo_version answered without a session; the other calls were refused before one
    assert manager.built == 0 and manager.calls == ["odoo_version"]
    line = srv.initialize({})["instructions"][len(INSTRUCTIONS):].strip()
    assert line == ("Permission policy for this connection: locked, because it could not be "
                    f"loaded ({srv.policy.error}). Only odoo_version works: tell the user, who "
                    "can fix the policy file or the plugin options and reconnect the server; "
                    "never try another tool or the shell to get the same result.")
    assert len(line) < INSTRUCTIONS_LIMIT


def test_a_locked_line_with_a_long_error_stays_short(tmp_path: Path) -> None:
    deep = tmp_path / ("d" * 150) / ("e" * 100)
    deep.mkdir(parents=True)
    path = deep / "policy.json"
    path.write_text("{", encoding="utf-8")
    srv = server(policy_file=str(path))
    line = srv.initialize({})["instructions"][len(INSTRUCTIONS):].strip()
    assert srv.policy.error_code == "E5" and len(line) < INSTRUCTIONS_LIMIT
    assert "..." in line and line.endswith("to get the same result.")


def test_an_unknown_profile_locks_with_its_own_remedy() -> None:
    srv = server(policy_profile="readonyl")
    assert listed(srv) == ["odoo_version"]
    text = call(srv, "odoo_search", model="res.partner")[1]
    assert "unknown permission profile 'readonyl'" in text
    assert "set the option 'Permission profile' to readonly, standard, builder or full" in text


# --- the startup log -----------------------------------------------------------------

def test_the_startup_log_line_carries_the_digest(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="odoo_mcp.server"):
        serve(Settings(), stdin=io.BytesIO(b""), stdout=io.BytesIO())
    digest = Policy().digest
    assert any(f"permission policy: profile standard, digest {digest}, file none" in
               record.getMessage() for record in caplog.records)


def test_the_startup_log_line_carries_the_lock_error(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="odoo_mcp.server"):
        serve(Settings(policy_profile="readonyl"), stdin=io.BytesIO(b""), stdout=io.BytesIO())
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any("permission policy locked (E1): unknown permission profile 'readonyl'" in message
               for message in errors)


# --- odoo_version: the policy block and W10 --------------------------------------------

@pytest.fixture
def fake() -> Iterator[FakeOdoo]:
    odoo = FakeOdoo()
    try:
        yield odoo
    finally:
        odoo.close()


def _odoo_version_on_19(fake: FakeOdoo, admin: bool) -> tuple[dict[str, Any], list[Any]]:
    seen: list[Any] = []

    def orm(model: str, method: str, body: dict[str, Any]) -> Any:
        seen.append((model, method, body))
        if method == "search_count":
            return 0
        if (model, method) == ("res.users", "has_group"):
            return admin and body.get("group_ext_id") == "base.group_system"
        raise AssertionError(f"unexpected call {model}.{method}")

    fake.serve_version()
    fake.serve_json2(orm)
    srv = McpServer(Settings(url=fake.url, db="db", login="admin", api_key=KEY, timeout=5))
    error, text = call(srv, "odoo_version")
    assert error is False, text
    return json.loads(text), seen


def test_odoo_version_returns_the_policy_block_and_warns_on_an_administrator(
        fake: FakeOdoo) -> None:
    payload, seen = _odoo_version_on_19(fake, admin=True)
    assert payload["version"] == 19 and payload["transport"] == "json2"
    block = payload["policy"]
    assert block == {**Policy().describe(registry.all()),
                     "warnings": [{"code": "W10", "text": ADMIN_WARNING}]}
    assert block["profile"] == "standard" and block["hidden_tools"] == STANDARD_HIDDEN
    # one has_group call, a record method with the signed-in user on 18+
    probes = [body for model, method, body in seen if method == "has_group"]
    assert len(probes) == 1 and probes[0]["ids"] == [2]
    assert probes[0]["group_ext_id"] == "base.group_system"
    assert KEY not in json.dumps(payload)


def test_odoo_version_does_not_warn_for_a_user_who_is_not_an_administrator(
        fake: FakeOdoo) -> None:
    payload, _seen = _odoo_version_on_19(fake, admin=False)
    assert payload["policy"]["warnings"] == []


@pytest.mark.parametrize("admin", [OdooFault("AccessError"), True])
def test_the_administrator_probe_is_a_model_method_before_18_and_may_fail(admin: Any) -> None:
    session = Session(version=17, admin=admin)
    srv = server(Manager(session=session))
    payload = json.loads(call(srv, "odoo_version")[1])
    expected = [] if isinstance(admin, Exception) else [{"code": "W10", "text": ADMIN_WARNING}]
    assert payload["policy"]["warnings"] == expected
    assert [(m, f, a, ids) for m, f, a, ids in session.calls] == [
        ("res.users", "has_group", ["base.group_system"], None)]


def test_no_probe_when_the_policy_closes_res_users(tmp_path: Path) -> None:
    path = write_policy(tmp_path, {"version": 1, "models": {"res.users": {"read": False}}})
    session = Session(admin=True)
    payload = json.loads(call(server(Manager(session=session), policy_file=path),
                              "odoo_version")[1])
    assert payload["policy"]["warnings"] == [] and session.calls == []


# --- odoo_list_models, odoo_access_check, odoo_report ----------------------------------

def test_odoo_list_models_leaves_out_what_the_policy_allows_nothing_on() -> None:
    models = ["res.partner", "ir.config_parameter", "res.users", "payment.provider",
              "sale.order", "base.module.uninstall"]
    session = Session(models=models)
    payload = json.loads(call(server(Manager(session=session)), "odoo_list_models")[1])
    assert [row["model"] for row in payload["models"]] == ["res.partner", "res.users",
                                                           "sale.order"]
    assert payload["hidden_by_policy"] == 3
    full = json.loads(call(server(Manager(session=Session(models=models)),
                                  policy_profile="full"), "odoo_list_models")[1])
    assert full["hidden_by_policy"] == 1  # the uninstall wizard is NEVER, even under full


def test_odoo_access_check_reports_the_policy_next_to_odoo() -> None:
    session = Session(allowed=True)
    payload = json.loads(call(server(Manager(session=session)), "odoo_access_check",
                              model="res.users")[1])
    assert payload["access"] == {"read": True, "write": True, "create": True, "unlink": True}
    assert payload["policy"] == {"read": True, "write": False, "create": False,
                                 "unlink": False}
    notes = [note for note in payload["notes"] if "permission policy" in note]
    assert notes == [
        f"'{op}' is allowed by Odoo for this user but refused by the odoo-tools permission "
        f"policy (rule tier:security)" for op in ("write", "create", "unlink")]


def test_odoo_access_check_adds_no_note_when_odoo_refuses_too() -> None:
    payload = json.loads(call(server(Manager(session=Session(allowed=False))),
                              "odoo_access_check", model="res.partner")[1])
    assert payload["policy"] == {"read": True, "write": True, "create": True, "unlink": False}
    assert not [note for note in payload.get("notes", []) if "permission policy" in note]


def test_odoo_report_never_asks_for_a_session_even_unconfigured() -> None:
    manager = Manager()  # building a session would fail the test
    error, text = call(server(manager), "odoo_report", report_name="account.report_invoice",
                       ids=[1])
    assert error is True and text.startswith("odoo_report cannot work over RPC")
    assert "ODOO_URL" not in text  # its own refusal, not the setup message
    assert manager.built == 0 and manager.calls == ["odoo_report"]
