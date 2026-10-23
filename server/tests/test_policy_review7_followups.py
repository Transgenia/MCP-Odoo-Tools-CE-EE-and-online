# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Seventh round: the context ``default_<field>`` channel, closed by construction.

The channel leaked in four consecutive review rounds, each time through another gap in
the check of a ``default_<field>`` list against the model a call names. The last round
showed why no such check can be sound: Odoo applies a context default to every record
created while the call runs, not only to the record the call names. A write whose values
create a line with ``(0, 0, vals)`` creates that line with the call's context, and a
business method (``action_confirm``, a wizard, an import) creates records of other
models with it, so ``default_user_ids`` or ``default_bank_ids`` reach ``res.users`` or
``res.partner.bank`` through a record the guard never saw being created.

The rule (design 6.5 step 7): under ``readonly``, ``standard`` and ``builder``, a
``default_<anything>`` whose value is a list, a tuple or an object is refused at Layer A
by ``check_context``, for every tool, method and model, with rule ``context`` and a text
that names the key, never its value, and gives the remedy: the record's values, where
they are checked, or profile ``full``. The guarded session runs the same check on every
actual call (Layer B). A plain default keeps its checks, and ``full`` is unchanged.

The reproductions of the last round are kept here as permanent tests. Each must stop at
Layer A, before any session exists: nothing reaches the raw session, not even a
``fields_get``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from policy_fakes import (
    CHAR,
    A,
    ScriptedSession,
    call,
    guarded,
    m2o,
    o2m,
    policy,
    refused,
    server,
)

from odoo_mcp.audit import AuditLog
from odoo_mcp.errors import PolicyDenied
from odoo_mcp.policy.check import check_context
from odoo_mcp.policy.model import Policy

MARKER = "ATTACKER-CLABE-7Q"  # a value no refusal, result or audit line may echo
SEALED_USER = [[0, 0, {"login": "attacker"}]]
WRITE_CHILD = {"child_ids": [[0, 0, {"name": "kid"}]]}  # a write that creates a line
HINT = ("context key '{key}' holds a list or an object, and Odoo applies a context default to "
        "every record the call creates, including x2many lines and records of other models, so "
        "it cannot be checked; pass those values in the record's values, where they are "
        "checked, or use profile 'full' (the user sets it in the plugin option 'Permission "
        "profile')")


def _execute(raw: ScriptedSession, model: str, method: str, *, p: Policy | None = None,
             **arguments: Any) -> tuple[bool, str]:
    """odoo_execute through the full server route (Layer A, then the guard)."""
    return call(server(raw, p=p or policy("standard")), "odoo_execute", model=model,
                method=method, **arguments)


def _stopped_at_layer_a(raw: ScriptedSession, err: bool, text: str, key: str) -> None:
    assert err is True, f"the call ran: {text[:200]}"
    assert "rule context)" in text and A in text, text
    assert f"context key '{key}' holds a list or an object" in text, text
    assert raw.calls == [] and raw.metadata == [], "the call went past Layer A"


# --- the last round's re-attack: a default riding a call that creates records -------------

@pytest.mark.parametrize(("method", "key", "value"), [
    ("write", "default_user_ids", SEALED_USER),                              # res.users
    ("write", "default_bank_ids", [[0, 0, {"acc_number": "DIVERTED"}]]),     # res.partner.bank
    ("write", "default_message_follower_ids", [[0, 0, {"partner_id": 9}]]),  # mail.followers
    ("update", "default_user_ids", [[0, 0, {"login": "a"}]]),                # update is a write
])
def test_a_sealed_default_riding_a_write_that_creates_a_line_stops_at_layer_a(
        method: str, key: str, value: Any) -> None:
    # The write creates a child contact with (0, 0, vals); Odoo creates it with the call's
    # context, so the default would create the sealed record through that child.
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", method, ids=[3], args=[WRITE_CHILD],
                         kwargs={"context": {key: value}})
    _stopped_at_layer_a(raw, err, text, key)


CROSS_MODEL = {
    "x.parent": {"name": CHAR, "line_ids": o2m("x.line", "parent_id")},
    "x.line": {"name": CHAR, "parent_id": m2o("x.parent"),
               "user_ids": o2m("res.users", "x_id")},
}


def test_a_default_naming_a_field_of_a_nested_comodel_stops_at_layer_a() -> None:
    # user_ids is no field of x.parent, only of the x.line its command creates: no check
    # against the model the call names can see it, so the value is not decided at all.
    raw = ScriptedSession(fields=CROSS_MODEL)
    err, text = _execute(raw, "x.parent", "create",
                         args=[{"name": "P", "line_ids": [[0, 0, {"name": "L"}]]}],
                         kwargs={"context": {"default_user_ids": SEALED_USER}})
    _stopped_at_layer_a(raw, err, text, "default_user_ids")


# --- the same round's first finding: a link command mixed with a bare id ------------------

@pytest.mark.parametrize("context", [
    {"default_user_ids": [[4, 4], 99]},             # a LINK of res.users, then a bare id
    {"default_user_ids": [[6, 0, [4]], 9]},         # a SET, then a bare id
    {"default_bank_ids": [[4, 7], 9]},              # res.partner.bank (security)
    {"default_message_follower_ids": [[4, 7], 9]},  # mail.followers (outbound)
])
def test_a_mixed_link_and_id_default_list_stops_at_layer_a(context: dict[str, Any]) -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "create", args=[{"name": "x"}],
                         kwargs={"context": context})
    _stopped_at_layer_a(raw, err, text, next(iter(context)))


# --- the rule: every tool, method, model, value shape and nesting -------------------------

def test_the_refusal_names_the_key_and_the_remedy_never_the_value() -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "create", args=[{"name": "x"}],
                         kwargs={"context": {"default_bank_ids": [[0, 0, {"acc_number": MARKER}]]}})
    assert (err, text) == (True, refused("call", "res.partner", "context",
                                         HINT.format(key="default_bank_ids"), layer="A"))
    assert MARKER not in text
    assert raw.calls == [] and raw.metadata == []


@pytest.mark.parametrize(("method", "arguments"), [
    ("create", {"args": [{"name": "x"}]}),
    ("name_create", {"args": ["x"]}),
    ("copy", {"ids": [3], "args": [{"name": "y"}]}),
    ("write", {"ids": [3], "args": [{"name": "y"}]}),
    ("update", {"ids": [3], "args": [{"name": "y"}]}),
    ("action_archive", {"ids": [3]}),
    ("web_save", {"ids": [3], "args": [{"name": "y"}, {}]}),
    ("load", {"args": [["name"], [["x"]]]}),
    ("search_read", {"args": [[]], "kwargs": {"fields": ["name"]}}),
    ("default_get", {"args": [["name"]]}),
    ("fields_get", {}),
    ("action_confirm", {"ids": [3]}),
    ("a_module_specific_verb", {"ids": [3]}),
])
@pytest.mark.parametrize("profile", ["standard", "builder"])
def test_every_method_class_is_refused_at_layer_a(profile: str, method: str,
                                                  arguments: dict[str, Any]) -> None:
    # Not only the classes that create the record they name: a read, an inspect or a
    # business verb is refused the same way, so no class list can drift again.
    raw = ScriptedSession()
    kwargs = {**arguments.get("kwargs", {}), "context": {"default_user_ids": SEALED_USER}}
    rest = {name: value for name, value in arguments.items() if name != "kwargs"}
    err, text = _execute(raw, "res.partner", method, p=policy(profile), kwargs=kwargs, **rest)
    _stopped_at_layer_a(raw, err, text, "default_user_ids")


def test_an_unlink_a_file_opens_is_refused_at_layer_a_too() -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "unlink", ids=[3],
                         p=policy("standard", {"res.partner": {"unlink": True}}),
                         kwargs={"context": {"default_user_ids": SEALED_USER}})
    _stopped_at_layer_a(raw, err, text, "default_user_ids")


def test_readonly_refuses_it_where_a_file_opens_odoo_execute() -> None:
    opened = policy("readonly", {"res.partner": {"call": True}})
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "search_read", p=opened, args=[[]],
                         kwargs={"context": {"default_user_ids": SEALED_USER}})
    _stopped_at_layer_a(raw, err, text, "default_user_ids")
    err, text = _execute(raw, "res.partner", "search_read", p=opened, args=[[]],
                         kwargs={"context": {"default_name": "x"}})
    assert err is False, text  # a plain default still runs


NESTED = {"default_user_ids": SEALED_USER}


@pytest.mark.parametrize(("method", "arguments"), [
    ("web_read", {"ids": [1], "kwargs": {"specification": {
        "partner_id": {"fields": {"name": {}}, "context": NESTED}}}}),
    ("web_read", {"ids": [1], "kwargs": {"specification": {      # two levels down
        "partner_id": {"fields": {"child_ids": {"fields": {"name": {}}, "context": NESTED}}}}}}),
    ("web_search_read", {"kwargs": {"domain": [], "specification": {
        "order_line": {"fields": {"name": {}}, "context": NESTED}}}}),
    ("web_save", {"ids": [1], "kwargs": {"vals": {"note": "x"}, "specification": {
        "order_line": {"fields": {"name": {}}, "context": NESTED}}}}),
    ("web_read_group", {"kwargs": {"domain": [], "groupby": ["partner_id"],
                                   "unfold_read_specification": {
                                       "order_line": {"fields": {"name": {}},
                                                      "context": NESTED}}}}),
])
def test_a_default_list_in_a_nested_context_stops_at_layer_a(
        method: str, arguments: dict[str, Any]) -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, "sale.order", method, **arguments)
    _stopped_at_layer_a(raw, err, text, "default_user_ids")


@pytest.mark.parametrize("value", [
    [],                                        # an empty list
    [5],                                       # a bare id list (Odoo reads a SET)
    [[6, 0, [1, 2]]],                          # a SET of a business comodel
    [[4, 1]],                                  # a LINK
    [[0, 0, {"name": "x"}]],                   # a CREATE of a business record
    [[0, 0, {"child_ids": [[0, 0, {"user_ids": SEALED_USER}]]}]],  # commands nested deeper
    {"name": "x"},                             # an object
    {},                                        # an empty object
])
def test_every_non_scalar_value_is_refused_even_on_a_business_comodel(value: Any) -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "create", args=[{"name": "x"}],
                         kwargs={"context": {"default_category_id": value}})
    _stopped_at_layer_a(raw, err, text, "default_category_id")


@pytest.mark.parametrize("profile", ["readonly", "standard", "builder"])
@pytest.mark.parametrize(("key", "value"), [
    ("default_user_ids", (4, 4)),                  # a tuple, which an internal caller may pass
    ("default_user_ids", ((0, 0, {"login": "a"}),)),
    ("default_note", {"a": 1}),
    ("default_x", frozenset({1})),                 # any container is not a plain value
    ("default_", [1]),                             # whatever follows the prefix
    ("default_a.b", [[4, 1]]),
])
def test_check_context_refuses_a_non_scalar_default_in_every_sealed_profile(
        profile: str, key: str, value: Any) -> None:
    with pytest.raises(PolicyDenied) as info:
        check_context(Policy(profile_name=profile), "res.partner", {key: value})
    assert (info.value.rule, info.value.layer) == ("context", "A")
    assert "holds a list or an object" in str(info.value)


def test_a_key_that_is_no_plain_identifier_is_described_not_echoed() -> None:
    with pytest.raises(PolicyDenied) as info:
        check_context(Policy(profile_name="standard"), "res.partner", {"default_a.b": [1]})
    assert "context key of that name holds a list or an object" in str(info.value)
    assert "default_a.b" not in str(info.value)


def test_the_guard_refuses_it_on_its_own_before_any_metadata() -> None:
    # Layer A skipped: the guarded session still refuses, with the same check, on Layer B.
    raw = ScriptedSession()
    g, _scope = guarded("odoo_execute", {"model": "res.partner", "method": "write", "ids": [3]},
                        p=policy("standard"), session=raw, layer_a=False)
    with pytest.raises(PolicyDenied) as info:
        g.execute("res.partner", "write", [WRITE_CHILD],
                  {"context": {"default_user_ids": SEALED_USER}}, ids=[3])
    assert (info.value.rule, info.value.layer) == ("context", "B")
    assert "context key 'default_user_ids' holds a list or an object" in str(info.value)
    assert raw.calls == [] and raw.metadata == []


@pytest.fixture
def audit_lines() -> Iterator[tuple[AuditLog, list[dict[str, Any]]]]:
    lines: list[dict[str, Any]] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(json.loads(record.getMessage()))

    logger, handler = logging.getLogger("odoo_mcp.audit"), Keep(logging.INFO)
    level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield AuditLog("stderr"), lines
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)


def test_the_audit_records_a_layer_a_context_refusal_without_the_value(audit_lines) -> None:
    audit, lines = audit_lines
    raw = ScriptedSession()
    err, _text = call(server(raw, p=policy("standard"), audit=audit), "odoo_execute",
                      model="res.partner", method="write", ids=[3], args=[WRITE_CHILD],
                      kwargs={"context": {"default_bank_ids": [[0, 0, {"acc_number": MARKER}]]}})
    assert err is True
    (line,) = lines
    assert (line["layer"], line["rule"], line["status"]) == ("A", "context", "refused")
    assert MARKER not in json.dumps(line)


# --- what keeps working ---------------------------------------------------------------------

@pytest.mark.parametrize("value", ["x", 7, 1.5, True, False, None])
def test_a_plain_default_still_runs(value: Any) -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "create", args=[{"name": "x"}],
                         kwargs={"context": {"default_comment": value}})
    assert err is False, text
    assert ("res.partner", "create") in raw.sent()


def test_a_plain_default_on_a_withheld_field_is_still_refused() -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "create", args=[{"name": "x"}],
                         kwargs={"context": {"default_signup_token": "T"}})
    assert err is True and "context key 'default_signup_token' is not allowed" in text
    assert raw.calls == []


def test_the_values_route_of_the_same_link_runs_and_is_checked() -> None:
    # The remedy the refusal gives: the same values in the record's values are decided
    # against the comodel. A business link runs; the sealed create is refused as before.
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "create",
                         args=[{"name": "x", "category_id": [[6, 0, [1, 2]]]}])
    assert err is False, text
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "write", ids=[3],
                         args=[{"child_ids": [[0, 0, {"name": "kid", "user_ids": SEALED_USER}]]}])
    assert err is True and "rule relational" in text
    assert ("res.partner", "write") not in raw.sent()


# The MRP backorder wizard, the example the CHANGELOG gives, takes its lines in values:
# test_policy_review6_followups.py runs it that way and refuses its action context.


def test_full_is_unchanged() -> None:
    raw = ScriptedSession()
    context = {"default_user_ids": SEALED_USER}
    err, text = _execute(raw, "res.partner", "write", p=Policy(profile_name="full"), ids=[3],
                         args=[WRITE_CHILD], kwargs={"context": context})
    assert err is False, text
    _args, kwargs, _ids = raw.call("res.partner", "write")
    assert kwargs["context"] == context  # sent as given


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
