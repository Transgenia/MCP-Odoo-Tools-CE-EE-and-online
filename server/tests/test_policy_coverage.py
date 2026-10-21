# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""A wrong mapping or a bypass cannot reach Odoo (design 9.2, #6 to #8 and #10).

6. A lying mapping: each write tool declares only ``read`` and runs under profile
   ``full`` against a scripted Odoo; the guard's envelope stops its first
   undeclared call, and Odoo receives no method that is not a read.
7. A deny-all policy: every tool, called with its ``GOLDEN`` arguments, sends
   Odoo nothing beyond the sign-in and the version probe.
8. Layer B alone: with Layer A granting every declared touch, Layer B still
   refuses every tool's primary effect.
10. Internal hygiene: each internal predicate holds for the call its tool makes
    and fails for a changed one; an explicit file refusal stops an internal.

Plus the guard's own calls: the only unchecked calls it makes are its
``SYSTEM_CALLS``.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fake_odoo_http import FakeOdoo
from policy_fakes import (
    FIELDS,
    KEY,
    ScriptedSession,
    call,
    guarded,
    policy,
    server,
)
from test_policy_mapping import GOLDEN, TOOLS_DIR, WRITE_TOOLS

from odoo_mcp.config import Settings
from odoo_mcp.errors import PolicyEnvelopeError, PolicyError
from odoo_mcp.policy.check import scope_for
from odoo_mcp.policy.guard import METADATA_ATTRIBUTES, SYSTEM_CALLS, GuardedSession
from odoo_mcp.policy.model import Policy, model_tiers
from odoo_mcp.policy.tiers import OPERATIONS
from odoo_mcp.registry import Access, ToolDef, obj, registry
from odoo_mcp.server import McpServer
from odoo_mcp.tools import studio
from odoo_mcp.transport.fallback import READ_METHODS

B_SUFFIX = "The call was stopped before Odoo ran it"
# What a session sends Odoo by itself: the sign-in (JSON-2: context_get, then the
# login of the key's owner) and the edition probe (installed modules).
SYSTEM_PROBE = {("res.users", "context_get"), ("res.users", "read"),
                ("ir.module.module", "search_count")}


@pytest.fixture
def fake() -> Iterator[FakeOdoo]:
    odoo = FakeOdoo()
    try:
        yield odoo
    finally:
        odoo.close()


def _orm(model: str, method: str, body: dict[str, Any]) -> Any:
    """An Odoo 19 that answers every call plausibly."""
    if method == "search_count":
        return 1  # base_import, and the other probed modules, are installed
    if method == "fields_get":
        return FIELDS.get(model, {"name": {"type": "char"}})
    if method in ("search_read", "read", "web_read", "formatted_read_group"):
        return []
    if method == "search":
        return [42]
    if method == "create":
        return [101]
    return True


def _server(fake: FakeOdoo, **settings: Any) -> McpServer:
    fake.serve_version()
    fake.serve_json2(_orm)
    return McpServer(Settings(url=fake.url, db="db", login="admin", api_key=KEY, timeout=5,
                              **settings))


def _seen(fake: FakeOdoo) -> list[tuple[str, str]]:
    out = []
    for request in fake.calls("/json/2/"):
        _empty, _json, _two, model, method = request["path"].split("/", 4)
        out.append((model, method))
    return out


# --- 6. a lying mapping ---------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(WRITE_TOOLS))
def test_a_lying_mapping_is_stopped_by_the_envelope(fake: FakeOdoo,
                                                    monkeypatch: pytest.MonkeyPatch,
                                                    name: str) -> None:
    monkeypatch.setattr(registry.get(name), "access", Access(arg_ops=("read",)))
    srv = _server(fake, policy_profile="full")
    error, text = call(srv, name, **GOLDEN[name][0])
    assert error is True
    assert text.startswith(f"internal error: {name} tried "), text
    assert text.endswith("This is a bug in odoo-tools; please report it to dev@transgenia.org.")
    assert [pair for pair in _seen(fake) if pair[1] not in READ_METHODS] == []


def test_a_tool_that_declares_read_and_deletes_is_stopped(fake: FakeOdoo,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    def liar(ctx: Any, args: dict[str, Any]) -> Any:
        return ctx.session.execute(args["model"], "unlink", [[1]])

    monkeypatch.setitem(registry._tools, "t_liar", ToolDef(
        "t_liar", "reads, it says", obj({"model": {"type": "string"}}, required=["model"]),
        liar, access=Access(arg_ops=("read",))))
    srv = _server(fake, policy_profile="full")
    error, text = call(srv, "t_liar", model="res.partner")
    assert (error, text) == (True, (
        "internal error: t_liar tried res.partner.unlink, which its permission mapping does not "
        "declare. The call was stopped before it reached Odoo. This is a bug in odoo-tools; "
        "please report it to dev@transgenia.org."))
    assert not [pair for pair in _seen(fake) if pair[1] == "unlink"]


# --- 7. deny-all ------------------------------------------------------------------------------

DENY_ALL = {"version": 1, "models": {"*": {op: False for op in OPERATIONS}}}
ANSWER_WITHOUT_DATA = {"odoo_version", "odoo_connections", "odoo_telemetry_preview",
                       "odoo_online_profile"}


def _deny_all(tmp_path: Path) -> str:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(DENY_ALL), encoding="utf-8")
    path.chmod(0o600)
    return str(path)


def _check_system_only(fake: FakeOdoo) -> None:
    seen = _seen(fake)
    assert set(seen) <= SYSTEM_PROBE, set(seen) - SYSTEM_PROBE
    for request in fake.calls("/json/2/res.users/read"):
        assert request["body"]["fields"] == ["login"]  # the sign-in's own read


def _degraded_profile(text: str) -> None:
    payload = json.loads(text)
    assert set(payload["unavailable"]) == {"user", "api_keys", "modules", "doc_bearer"}
    assert all(note.startswith("withheld by the odoo-tools permission policy")
               for note in payload["unavailable"].values())
    assert payload["user"] is None and payload["api_keys"] is None
    assert payload["applications"] is None and payload["doc_bearer"] is False


def test_a_deny_all_policy_lets_nothing_but_the_sign_in_reach_odoo(fake: FakeOdoo,
                                                                   tmp_path: Path) -> None:
    srv = _server(fake, policy_profile="readonly", policy_file=_deny_all(tmp_path))
    for name in sorted(GOLDEN):
        error, text = call(srv, name, **GOLDEN[name][0])
        if name in ANSWER_WITHOUT_DATA:
            assert error is False, (name, text)
        else:
            assert error is True, name
            assert "permission policy" in text or name == "odoo_report", (name, text)
        if name == "odoo_online_profile":
            _degraded_profile(text)
    _check_system_only(fake)


# --- 8. Layer B alone ----------------------------------------------------------------------------

def test_layer_b_alone_refuses_every_primary_effect(fake: FakeOdoo, tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    # Layer A grants every declared touch, as a wrong Layer A would.
    monkeypatch.setattr(Policy, "check_tool", lambda self, tool: None)
    monkeypatch.setattr(Policy, "check", lambda self, tool, arguments: scope_for(
        self, tool, arguments))
    srv = _server(fake, policy_profile="readonly", policy_file=_deny_all(tmp_path))
    for name in sorted(GOLDEN):
        error, text = call(srv, name, **GOLDEN[name][0])
        if name in ANSWER_WITHOUT_DATA:
            assert error is False, (name, text)
        elif name == "odoo_report":
            assert error is True and text.startswith("odoo_report cannot work over RPC")
        else:
            assert error is True and B_SUFFIX in text, (name, text)
        if name == "odoo_online_profile":
            _degraded_profile(text)
    _check_system_only(fake)


# --- 10. internal hygiene ---------------------------------------------------------------------

def _envelope(fn: Any, *args: Any, **kwargs: Any) -> None:
    with pytest.raises(PolicyEnvelopeError):
        fn(*args, **kwargs)


def test_no_internal_targets_a_secrets_model() -> None:
    for tool in registry.all():
        for internal in tool.access.internal:  # type: ignore[union-attr]
            model = "base.automation" if internal.model == "$automation" else internal.model
            assert "secrets" not in model_tiers(model), (tool.name, internal.model)
            assert internal.check is not None or internal.methods == {"fields_get"}, (
                tool.name, internal.model)


def test_has_group_is_about_the_signed_in_user_and_that_group_only() -> None:
    raw = ScriptedSession(results={("res.users", "has_group"): True})
    g, _scope = guarded("odoo_version", {}, session=raw)
    assert g.execute("res.users", "has_group", ["base.group_system"]) is True
    assert g.execute("res.users", "has_group", ["base.group_system"], ids=[2]) is True
    _envelope(g.execute, "res.users", "has_group", ["base.group_erp_manager"])
    _envelope(g.execute, "res.users", "has_group", ["base.group_system"], ids=[99])
    _envelope(g.execute, "res.users", "has_group", ["base.group_system"],
              {"context": {"uid": 1}})
    # odoo_access_check on res.users itself: the internal pins has_group all the same
    g, _scope = guarded("odoo_access_check", {"model": "res.users"}, session=raw)
    assert g.execute("res.users", "has_group", ["base.group_allow_export"], ids=[2]) is True
    _envelope(g.execute, "res.users", "has_group", ["base.group_system"], ids=[2])
    assert raw.sent() == [("res.users", "has_group")] * 3


def test_odoo_record_documents_returns_a_stored_invoice_pdf_under_standard() -> None:
    raw = ScriptedSession(version=18, results={
        ("ir.attachment", "search_read"): [
            {k: v for k, v in FIELDS_ROW.items() if k != "res_field"}]})
    payload = json.loads(call(server(raw), "odoo_record_documents", model="account.move",
                              res_id=7, attachment_id=11, include_content=True)[1])
    assert payload["attachment"]["content_base64"] == "UERG"
    assert payload["attachment"]["is_invoice_pdf"] is True
    assert {doc["id"] for doc in payload["documents"]} == {10, 11}
    assert [pair for pair in raw.sent()] == [
        ("account.move", "read"), ("ir.attachment", "search_read"), ("ir.attachment", "read"),
        ("ir.attachment", "read"), ("ir.attachment", "read"), ("ir.attachment", "read")]
    # the guard's pre-read of the file's field, before its content
    assert raw.calls[-2][3] == {"fields": ["res_model", "res_field"]}


FIELDS_ROW = {"id": 10, "name": "scan.png", "mimetype": "image/png", "file_size": 10,
              "create_date": "2026-09-01 10:00:00", "type": "binary", "res_field": False}


def test_the_record_documents_predicates_pin_each_call_to_the_record() -> None:
    raw = ScriptedSession(version=18)
    arguments = {"model": "account.move", "res_id": 7, "attachment_id": 12,
                 "include_content": True}
    g, _scope = guarded("odoo_record_documents", arguments, session=raw)
    listing = ["name", "mimetype", "file_size", "create_date", "type"]
    # the listing: this record, the listing fields
    g.execute("ir.attachment", "search_read",
              [[["res_model", "=", "account.move"], ["res_id", "=", 7]]], {"fields": listing})
    _envelope(g.execute, "ir.attachment", "search_read",
              [[["res_model", "=", "account.move"], ["res_id", "=", 8]]], {"fields": listing})
    _envelope(g.execute, "ir.attachment", "search_read",
              [[["res_model", "=", "account.move"], ["res_id", "=", 7]]],
              {"fields": [*listing, "datas"]})
    # flags: only what the record points to, read in this call
    _envelope(g.execute, "ir.attachment", "read", [[11]], {"fields": listing})
    g.execute("account.move", "read", [[7]], {"fields": ["message_main_attachment_id",
                                                         "invoice_pdf_report_id"]})
    g.execute("ir.attachment", "read", [[11]], {"fields": listing})
    _envelope(g.execute, "ir.attachment", "read", [[13]], {"fields": listing})
    # content: never before this call showed the attachment is the record's
    _envelope(g.execute, "ir.attachment", "read", [[12]], {"fields": ["datas"]})
    g.execute("ir.attachment", "read", [[12]], {"fields": [*listing, "res_model", "res_id"]})
    _envelope(g.execute, "ir.attachment", "read", [[12]], {"fields": ["datas"]})  # res_id 8
    _envelope(g.execute, "ir.attachment", "read", [[11]], {"fields": ["datas"]})  # not asked


def test_the_content_of_a_withheld_binary_field_is_refused() -> None:
    raw = ScriptedSession(version=18)
    error, text = call(server(raw), "odoo_record_documents", model="account.move", res_id=7,
                       attachment_id=13, include_content=True)
    assert error is True and "rule attachment-field" in text and "attachment 13" in text
    assert "U0VD" not in text and raw.sent()[-1] == ("ir.attachment", "read")
    assert raw.calls[-1][3] == {"fields": ["res_model", "res_field"]}  # the pre-read, last


def _preview_session() -> ScriptedSession:
    return ScriptedSession(version=18, results={
        ("base_import.import", "create"): [42],
        ("base_import.import", "execute_import"): {"ids": [1, 2], "messages": []},
        ("base_import.import", "unlink"): True,
    })


def test_the_import_preview_runs_its_three_internal_calls() -> None:
    raw = _preview_session()
    error, text = call(server(raw), "odoo_import_preview", model="res.partner",
                       fields=["name", "email"], rows=[["Acme", "info@example.com"]])
    assert error is False and json.loads(text)["would_import"] == 2
    assert raw.sent() == [("base_import.import", "create"),
                          ("base_import.import", "execute_import"),
                          ("base_import.import", "unlink")]


def test_the_import_preview_predicates() -> None:
    raw = _preview_session()
    arguments = {"model": "res.partner", "fields": ["name"], "rows": [["Acme"]]}
    g, _scope = guarded("odoo_import_preview", arguments, session=raw)
    good = {"res_model": "res.partner", "file": "Acme\n", "file_type": "text/csv",
            "file_name": "x.csv"}
    _envelope(g.execute, "base_import.import", "create", [{**good, "res_model": "res.users"}])
    _envelope(g.execute, "base_import.import", "create", [{**good, "import_id": 1}])
    _envelope(g.execute, "base_import.import", "execute_import",
              [[42], ["name"], ["name"], {}], {"dryrun": True})  # no wizard created yet
    assert g.execute("base_import.import", "create", [good]) == [42]
    _envelope(g.execute, "base_import.import", "execute_import",
              [[42], ["name"], ["name"], {}], {"dryrun": False})
    _envelope(g.execute, "base_import.import", "execute_import",
              [[42], ["name", "email"], ["name", "email"], {}], {"dryrun": True})
    g.execute("base_import.import", "execute_import", [[42], ["name"], ["name"], {}],
              {"dryrun": True})
    _envelope(g.execute, "base_import.import", "unlink", [[43]])
    g.execute("base_import.import", "unlink", [[42]])


def _field_arguments(**extra: Any) -> dict[str, Any]:
    return {"model": "res.partner", "name": "x_tier", "label": "Tier", "field_type": "char",
            **extra}


def test_odoo_add_field_works_under_builder_and_with_a_schema_opening() -> None:
    for p in (Policy(profile_name="builder"), policy(models={"*": {"schema": True}})):
        raw = ScriptedSession(results={("ir.model", "search"): [42],
                                       ("ir.model.fields", "create"): 999})
        payload = json.loads(call(server(raw, p=p), "odoo_add_field",
                                  **_field_arguments())[1])
        assert payload["field_id"] == 999
        assert raw.sent() == [("ir.model", "search"), ("ir.model.fields", "create")]
        assert raw.invalidated == ["res.partner"]


def test_the_add_field_predicates() -> None:
    raw = ScriptedSession(results={("ir.model", "search"): [42]})
    g, _scope = guarded("odoo_add_field", _field_arguments(field_type="many2one",
                                                           relation="res.country"),
                        session=raw, p=Policy(profile_name="builder"))
    vals = {"name": "x_tier", "field_description": "Tier", "ttype": "many2one", "model_id": 42,
            "model": "res.partner", "state": "manual", "required": False,
            "relation": "res.country"}
    _envelope(g.execute, "ir.model", "search", [[["model", "=", "res.users"]]], {"limit": 1})
    _envelope(g.execute, "ir.model.fields", "create", [vals])  # no ir.model id found yet
    g.execute("ir.model", "search", [[["model", "=", "res.partner"]]], {"limit": 1})
    for bad in ({"compute": "for r in self: r.x_tier = 1"}, {"depends": "name"},
                {"related": "partner_id.name"}, {"state": "base"}, {"name": "tier"},
                {"model_id": 43}, {"model": "res.users"}, {"relation": "res.users"}):
        _envelope(g.execute, "ir.model.fields", "create", [{**vals, **bad}])
    g.execute("ir.model.fields", "create", [vals])


def test_an_explicit_refusal_stops_an_internal() -> None:
    raw = ScriptedSession(results={("ir.model", "search"): [42]})
    closed = policy("builder", models={"ir.model.fields": {"create": False}})
    error, text = call(server(raw, p=closed), "odoo_add_field", **_field_arguments())
    assert error is True and "rule file:ir.model.fields" in text and B_SUFFIX in text
    assert raw.sent() == [("ir.model", "search")]


AUTOMATION_V17 = {"name": {"type": "char"}, "model_id": {"type": "many2one"},
                  "trigger": {"type": "selection"}, "state": {"type": "selection"},
                  "code": {"type": "text"}}
AUTOMATION_V15 = {"name": {"type": "char"}, "model_id": {"type": "many2one"},
                  "trigger": {"type": "selection"},
                  "action_server_id": {"type": "many2one", "relation": "ir.actions.server"}}
AUTOMATION_V10 = {"name": {"type": "char"}, "model_id": {"type": "many2one"},
                  "trigger": {"type": "selection"},
                  "server_action_ids": {"type": "many2many", "relation": "ir.actions.server"}}
AUTOMATION_ARGUMENTS = {"model": "crm.lead", "name": "Flag",
                        "code": "records.write({'priority': '1'})"}


@pytest.mark.parametrize(("version", "automation", "metadata", "expected"), [
    (17, "base.automation", AUTOMATION_V17, [("base.automation", "create")]),
    (15, "base.automation", AUTOMATION_V15, [("ir.actions.server", "create"),
                                            ("base.automation", "create")]),
    (10, "base.action.rule", AUTOMATION_V10, [("ir.actions.server", "create"),
                                             ("base.action.rule", "create")]),
])
def test_odoo_add_automation_works_under_builder(version: int, automation: str,
                                                 metadata: dict[str, Any],
                                                 expected: list[tuple[str, str]]) -> None:
    raw = ScriptedSession(version=version, fields={automation: metadata}, results={
        ("ir.model", "search"): [42], ("ir.actions.server", "create"): 555,
        (automation, "create"): 777})
    error, text = call(server(raw, policy_profile="builder"), "odoo_add_automation",
                       **AUTOMATION_ARGUMENTS)
    assert error is False, text
    assert json.loads(text)["automation_id"] == 777
    assert raw.sent() == [("ir.model", "search"), *expected]


def test_the_automation_predicates() -> None:
    raw = ScriptedSession(fields={"base.automation": AUTOMATION_V15}, results={
        ("ir.model", "search"): [42], ("ir.actions.server", "create"): 555})
    g, _scope = guarded("odoo_add_automation", AUTOMATION_ARGUMENTS, session=raw,
                        p=Policy(profile_name="builder"))
    assert g.fields_get("base.automation") == AUTOMATION_V15
    g.execute("ir.model", "search", [[["model", "=", "crm.lead"]]], {"limit": 1})
    action = {"name": "Flag", "model_id": 42, "state": "code", "code": "pass"}
    for bad in ({"state": "webhook"}, {"model_id": 1}, {"usage": "ir_cron"}):
        _envelope(g.execute, "ir.actions.server", "create", [{**action, **bad}])
    assert g.execute("ir.actions.server", "create", [action]) == 555
    automation = {"name": "Flag", "model_id": 42, "trigger": "on_create"}
    for bad in ({"state": "webhook"}, {"action_server_id": 556},
                {"action_server_ids": [[6, 0, [555, 556]]]}, {"model_id": 1},
                {"webhook_uuid": "x"}):
        _envelope(g.execute, "base.automation", "create", [{**automation, **bad}])
    _envelope(g.execute, "ir.actions.server", "unlink", [[556]])
    g.execute("base.automation", "create", [{**automation, "action_server_id": 555}])
    g.execute("ir.actions.server", "unlink", [[555]])


def test_a_file_refusal_on_server_actions_stops_odoo_add_automation() -> None:
    closed = policy("builder", models={"ir.actions.server": {"create": False}})
    raw = ScriptedSession(fields={"base.automation": AUTOMATION_V17})
    error, text = call(server(raw, p=closed), "odoo_add_automation", **AUTOMATION_ARGUMENTS)
    assert error is True and "rule file:ir.actions.server" in text and raw.sent() == []
    # Layer B on its own, both shapes: inline (17) and linked (15)
    for metadata in (AUTOMATION_V17, AUTOMATION_V15):
        raw = ScriptedSession(fields={"base.automation": metadata},
                              results={("ir.model", "search"): [42]})
        g, _scope = guarded("odoo_add_automation", AUTOMATION_ARGUMENTS, session=raw, p=closed,
                            layer_a=False)
        definition = registry.get("odoo_add_automation")
        from odoo_mcp.registry import ToolContext

        with pytest.raises(PolicyError) as info:
            definition.handler(ToolContext(session=g, manager=None, policy=closed),
                               AUTOMATION_ARGUMENTS)
        # stopped at its first internal call: what it declared is no longer allowed
        assert "file:ir.actions.server" in str(info.value)
        assert raw.sent() == []


def test_a_refused_automation_removes_the_server_action_it_left(
        monkeypatch: pytest.MonkeyPatch) -> None:
    # The automation create is stopped (here as a predicate bug would stop it) after
    # the server action was created: the tool removes it, then reports the refusal.
    monkeypatch.setattr(studio, "_automation", lambda call, scope: False)
    monkeypatch.setattr(registry.get("odoo_add_automation"), "access", replace(
        registry.get("odoo_add_automation").access,  # type: ignore[arg-type]
        internal=tuple(replace(internal, check=studio._automation)
                       if internal.model == "$automation" and "create" in internal.methods
                       else internal
                       for internal in registry.get("odoo_add_automation").access.internal)))
    raw = ScriptedSession(fields={"base.automation": AUTOMATION_V15}, results={
        ("ir.model", "search"): [42], ("ir.actions.server", "create"): 555})
    error, text = call(server(raw, policy_profile="builder"), "odoo_add_automation",
                       **AUTOMATION_ARGUMENTS)
    assert error is True and text.startswith(
        "internal error: odoo_add_automation tried base.automation.create")
    assert raw.sent() == [("ir.model", "search"), ("ir.actions.server", "create"),
                          ("ir.actions.server", "unlink")]
    assert raw.call("ir.actions.server", "unlink")[0] == [[555]]


# --- the guard's own calls ----------------------------------------------------------------------

SYSTEM = {(model, method) for model, method, _why in SYSTEM_CALLS}


@pytest.mark.parametrize(("tool", "arguments", "asked"), [
    ("odoo_write", {"model": "res.partner", "ids": [8],
                    "values": {"email": "a@example.com", "x_attachment_ids": [[4, 6]]}},
     ("res.partner", "write", [[8], {"email": "a@example.com", "x_attachment_ids": [[4, 6]]}])),
    ("odoo_read", {"model": "ir.attachment", "ids": [6]}, ("ir.attachment", "read", [[6]])),
    ("odoo_search_read", {"model": "sale.order", "domain": [["partner_id.name", "=", "x"]]},
     ("sale.order", "search_read", [[["partner_id.name", "=", "x"]]])),
    ("odoo_import", {"model": "res.partner", "fields": ["name", "child_ids/name"],
                     "rows": [["a", "b"]]},
     ("res.partner", "load", [["name", "child_ids/name"], [["a", "b"]]])),
])
def test_the_guard_makes_no_unchecked_call_but_its_system_calls(
        tool: str, arguments: dict[str, Any], asked: tuple[str, str, Any]) -> None:
    raw = ScriptedSession()
    g, _scope = guarded(tool, arguments, session=raw)
    model, method, args = asked
    g.execute(model, method, args)
    sent = raw.sent()
    assert sent[-1] == (model, method)
    for pair in sent[:-1]:
        assert pair in SYSTEM, pair
    assert all(attributes == list(METADATA_ATTRIBUTES) for _model, attributes in raw.metadata)
    assert ("*", "fields_get") in SYSTEM


def test_no_tool_reaches_into_the_guarded_session() -> None:
    private = {name for cls in (GuardedSession,) for name in cls.__slots__}
    private |= {"_transport", "_manager", "_check", "_fields", "_redact"}
    for path in sorted(TOOLS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = sorted({node.attr for node in ast.walk(tree)
                        if isinstance(node, ast.Attribute) and node.attr in private})
        assert found == [], (path.name, found)
