# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""1.5.1 E1: a context passed positionally, which Odoo 10 to 12 read.

Odoo 10, 11 and 12 also take a call's context from the positional argument that follows the
method's own parameters; from 13 only ``kwargs["context"]`` is read. 1.5.0 read a context only
by name, so a list default, a structural default or a key outside the allowlist could ride a
positional argument of ``odoo_execute`` to Odoo 10 to 12 unchecked (a documented known limit).
Closed by construction, without refusing ordinary calls:

  * Layer A, on every series (it runs before the series is known): for a method ``ARG_SHAPES``
    names, an object after its parameters, or at a parameter that never holds an object, is
    the context and meets every context rule; a call with an argument after the parameters
    stays a ``shape`` refusal when the context rules let it pass, as before. For any other
    method every positional object may be the context, so its ``default_<field>`` keys meet
    the context rules, and a values object (``{"default_code": "A-1"}``) still runs.
  * Layer B: the guarded session applies the same on 10 to 12, as a backstop; from 13 the
    positional objects are values, checked as before.
  * ``full`` is unchanged. A refusal names the key, never its value, and gives the remedy.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from policy_fakes import ScriptedSession, call, guarded, policy, refused, server

from odoo_mcp.errors import PolicyDenied
from odoo_mcp.policy import texts
from odoo_mcp.policy.check import STRUCTURAL_DEFAULT_FIELDS
from odoo_mcp.policy.classify import (
    ARG_SHAPES,
    OBJECT,
    POSITIONAL_CONTEXT_UNTIL,
    ROWS,
    as_context,
    extract,
    positional_contexts,
)
from odoo_mcp.policy.model import Policy

MARKER = "DO-NOT-ECHO-E1"  # a value no refusal may carry
LIST = {"default_child_ids": [[0, 0, {"name": MARKER}]]}  # a list default: x2many commands
PLACE = "in a positional argument, which Odoo 10 to 12 take as the call's context"
REMEDY = ("pass the context by name in kwargs 'context' (the same rules apply there) and the "
          "method's other arguments by name, or put the values in the record's values")
STRUCTURAL = "sets a field that binds or exposes a related record"
LIST_HINT = "holds a list or an object"


def _execute(raw: ScriptedSession, model: str, method: str, *, p: Policy | None = None,
             **arguments: Any) -> tuple[bool, str]:
    """odoo_execute through the full server route (Layer A, then the guard)."""
    return call(server(raw, p=p or policy("standard")), "odoo_execute", model=model,
                method=method, **arguments)


def _stopped_at_layer_a(raw: ScriptedSession, err: bool, text: str, key: str,
                        hint: str = LIST_HINT) -> None:
    assert err is True, f"the call ran: {text[:200]}"
    assert "rule context)" in text and "Nothing was sent to Odoo." in text, text
    assert f"context key '{key}', {PLACE}" in text and hint in text, text
    assert REMEDY in text, text
    assert MARKER not in text
    assert raw.calls == [] and raw.metadata == [], "the call went past Layer A"


def _guard(model: str, method: str, *, version: int, ids: Any = None,
           p: Policy | None = None, session: Any = None) -> tuple[Any, ScriptedSession]:
    """The guarded session of an odoo_execute call, Layer A skipped (the backstop alone)."""
    raw = session if session is not None else ScriptedSession(version=version)
    arguments: dict[str, Any] = {"model": model, "method": method}
    if ids is not None:
        arguments["ids"] = ids
    g, _scope = guarded("odoo_execute", arguments, p=p or policy("standard"), session=raw,
                        layer_a=False)
    return g, raw


# --- Layer A: a list default in a positional context ----------------------------------------

@pytest.mark.parametrize(("method", "arguments"), [
    # methods the policy knows: the object after the parameters is the context
    ("create", {"args": [{"name": "x"}, LIST]}),                        # model method
    ("write", {"ids": [3], "args": [{"name": "x"}, LIST]}),             # record method, ids=
    ("write", {"args": [[3], {"name": "x"}, LIST]}),                    # record method, legacy
    ("search_read", {"args": [[], ["name"], 0, 1, "id", LIST]}),        # a read
    ("read", {"ids": [3], "args": [["name"], "_classic_read", LIST]}),  # a record read
    # an object at a parameter that never holds one (search_count has no limit on 10 to 12)
    ("search_count", {"args": [[], LIST]}),
    # any other method: every positional object may be the context
    ("action_confirm", {"ids": [3], "args": [LIST]}),                   # record method, ids=
    ("action_confirm", {"args": [[3], LIST]}),                          # record method, legacy
    ("x_model_method", {"args": [LIST]}),                               # model method
    ("action_confirm", {"ids": [3], "args": [LIST, "after it"]}),       # not the last argument
])
def test_a_list_default_in_a_positional_context_stops_at_layer_a(
        method: str, arguments: dict[str, Any]) -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", method, **arguments)
    _stopped_at_layer_a(raw, err, text, "default_child_ids")


@pytest.mark.parametrize("value", [[], (), {"name": "x"}, [5]])
def test_every_list_or_object_default_is_refused_positionally(value: Any) -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "action_confirm", ids=[3],
                         args=[{"default_category_id": value}])
    _stopped_at_layer_a(raw, err, text, "default_category_id")


@pytest.mark.parametrize("profile", ["readonly", "standard", "builder"])
def test_every_sealed_profile_refuses_a_positional_list_default(profile: str) -> None:
    opened = policy(profile, {"res.partner": {"read": True, "create": True, "write": True,
                                              "call": True}})
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "action_confirm", p=opened, ids=[3], args=[LIST])
    _stopped_at_layer_a(raw, err, text, "default_child_ids")


# --- Layer A: a structural default on a call that can create ----------------------------------

@pytest.mark.parametrize(("model", "method", "arguments", "key"), [
    ("res.partner", "create", {"args": [{"name": "x"}, {"default_public": True}]},
     "default_public"),
    ("product.template", "write", {"ids": [1], "args": [{"name": "x"},
                                                        {"default_ir_attachment_id": 5}]},
     "default_ir_attachment_id"),
    ("res.partner", "action_confirm", {"ids": [3], "args": [{"default_public": True}]},
     "default_public"),
    ("product.template", "action_x", {"args": [[1], {"default_ir_attachment_id": 5}]},
     "default_ir_attachment_id"),
])
def test_a_structural_default_in_a_positional_context_is_refused_on_a_creating_call(
        model: str, method: str, arguments: dict[str, Any], key: str) -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, model, method, **arguments)
    _stopped_at_layer_a(raw, err, text, key, hint=STRUCTURAL)


@pytest.mark.parametrize("name", sorted(STRUCTURAL_DEFAULT_FIELDS))
def test_every_structural_field_is_refused_as_a_positional_default(name: str) -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "action_confirm", ids=[3],
                         args=[{f"default_{name}": 5}])
    _stopped_at_layer_a(raw, err, text, f"default_{name}", hint=STRUCTURAL)


def test_a_structural_default_in_a_positional_context_is_inert_on_a_read() -> None:
    # A read creates nothing (design 4.11): search_count's object is checked as a context,
    # and a plain structural default is left alone there, as by name.
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "search_count", args=[[], {"default_public": True}])
    assert err is False, text
    assert ("res.partner", "search_count") in raw.sent()


# --- Layer A: what still runs ------------------------------------------------------------------

@pytest.mark.parametrize(("method", "arguments"), [
    ("action_confirm", {"ids": [3], "args": [{"default_name": "x"}]}),
    ("action_confirm", {"args": [[3], {"default_name": "x", "lang": "es_MX"}]}),
    ("x_model_method", {"args": [{"default_type": "contact"}]}),
    ("search_count", {"args": [[], {"default_name": "x", "active_test": False}]}),
])
def test_a_scalar_default_in_a_positional_context_runs(method: str,
                                                       arguments: dict[str, Any]) -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", method, **arguments)
    assert err is False, text
    args, _kwargs, _ids = raw.call("res.partner", method)
    assert args == arguments["args"]  # sent as given


@pytest.mark.parametrize(("method", "arguments"), [
    ("x_set_values", {"ids": [1], "args": [{"default_code": "A-1"}]}),
    ("x_set_values", {"args": [[1], {"default_code": "A-1", "name": "Widget"}]}),
    ("create", {"args": [{"default_code": "A-1", "name": "Widget"}]}),
    ("write", {"ids": [1], "args": [{"default_code": "A-1"}]}),
])
def test_a_values_object_with_a_real_default_code_field_still_runs(
        method: str, arguments: dict[str, Any]) -> None:
    # default_code is a real field of product.product holding text: as a value it is a value,
    # and read as a possible context it is a plain default of a field that is not withheld.
    raw = ScriptedSession()
    err, text = _execute(raw, "product.product", method, **arguments)
    assert err is False, text
    assert ("product.product", method) in raw.sent()


def test_only_what_the_context_rules_refuse_is_refused() -> None:
    # The same values object with a list in default_code is refused, as a context would be.
    raw = ScriptedSession()
    err, text = _execute(raw, "product.product", "x_set_values", ids=[1],
                         args=[{"default_code": [MARKER]}])
    _stopped_at_layer_a(raw, err, text, "default_code")


def test_a_key_outside_the_allowlist_in_a_known_positional_context_is_refused() -> None:
    # search_count's object can only be a context: the allowlist applies to it in full.
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "search_count", args=[[], {"tracking_disable": 1}])
    assert err is True and raw.calls == [], text
    assert f"context key 'tracking_disable', {PLACE}, is not allowed" in text, text
    assert REMEDY in text and "rule context)" in text


def test_an_argument_after_the_parameters_stays_a_shape_refusal_as_before() -> None:
    # The context rules let this one pass; the call is still malformed from Odoo 13 on, and
    # is refused by its shape as before. Not an object at all: the same shape refusal.
    for extra in ({"default_name": "y", "lang": "es_MX"}, 5, None):
        raw = ScriptedSession()
        err, text = _execute(raw, "res.partner", "create", args=[{"name": "x"}, extra])
        assert err is True and raw.calls == [], text
        assert "rule shape)" in text and "takes at most 1 positional argument(s)" in text, text


def test_a_context_by_name_keeps_its_own_wording() -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "action_confirm", ids=[3],
                         kwargs={"context": LIST})
    assert err is True and raw.calls == [], text
    assert "context key 'default_child_ids' holds a list or an object" in text, text
    assert PLACE not in text


def test_the_documented_residual_other_keys_of_an_opaque_object_are_values() -> None:
    # docs/policy.md, known limit 10: an object passed positionally to a method outside the
    # table may be its values, so only its default_<field> keys meet the context rules.
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "action_confirm", ids=[3],
                         args=[{"name": "x", "tracking_disable": True}])
    assert err is False, text


# --- the refusal ------------------------------------------------------------------------------

def test_the_refusal_names_the_key_and_the_remedy_never_the_value() -> None:
    raw = ScriptedSession()
    hint = ("context key 'default_child_ids', in a positional argument, which Odoo 10 to 12 "
            "take as the call's context, holds a list or an object, and Odoo applies a context "
            "default to every record the call creates, including x2many lines and records of "
            "other models, so it cannot be checked; pass the context by name in kwargs "
            "'context' (the same rules apply there) and the method's other arguments by name, "
            "or put the values in the record's values, where they are checked, or use profile "
            "'full' (the user sets it in the plugin option 'Permission profile')")
    err, text = _execute(raw, "res.partner", "action_confirm", ids=[3], args=[LIST])
    assert (err, text) == (True, refused("call", "res.partner", "context", hint, layer="A"))
    assert MARKER not in text


def test_a_key_that_is_not_a_plain_name_is_described_not_echoed() -> None:
    raw = ScriptedSession()
    err, text = _execute(raw, "res.partner", "search_count",
                         args=[[], {f"{MARKER} key": True}])
    assert err is True and raw.calls == [], text
    assert f"context key of that name, {PLACE}, is not allowed" in text and MARKER not in text


def test_the_positional_hints_are_the_named_ones_with_the_place_and_the_remedy() -> None:
    p = Policy(profile_name="standard")
    for factory in (texts.context, texts.context_default, texts.context_structural_default):
        named = str(factory(p, "call", "res.partner", "default_x"))
        positional = str(factory(p, "call", "res.partner", "default_x", positional=True))
        assert PLACE not in named and PLACE in positional
        assert REMEDY in positional


# --- full is unchanged -----------------------------------------------------------------------

def test_full_forwards_a_positional_object_unchanged() -> None:
    raw = ScriptedSession(version=12)
    err, text = _execute(raw, "res.partner", "action_confirm", p=Policy(profile_name="full"),
                         ids=[3], args=[LIST])
    assert err is False, text
    args, _kwargs, ids = raw.call("res.partner", "action_confirm")
    assert (args, ids) == ([LIST], [3])


def test_full_keeps_the_shape_refusal_and_the_unchecked_parameter() -> None:
    full = Policy(profile_name="full")
    raw = ScriptedSession(version=12)
    err, text = _execute(raw, "res.partner", "create", p=full, args=[{"name": "x"}, LIST])
    assert err is True and "rule shape)" in text and raw.calls == [], text
    err, text = _execute(raw, "res.partner", "search_count", p=full,
                         args=[[], {"tracking_disable": True}])
    assert err is False, text


# --- Layer B: the guarded session on 10 to 12 ----------------------------------------------------

@pytest.mark.parametrize("version", [10, 11, 12])
@pytest.mark.parametrize(("method", "args", "ids"), [
    ("action_confirm", [LIST], [3]),                    # any other method, ids=
    ("action_confirm", [[3], LIST], None),              # any other method, legacy form
    ("x_model_method", [LIST], None),                   # any other method, model method
    ("create", [{"name": "x"}, LIST], None),            # after create's parameter
    ("write", [{"name": "x"}, LIST], [3]),              # after write's parameter
    ("search_count", [[], LIST], None),                 # at a parameter of no object
])
def test_the_guard_refuses_a_positional_list_default_on_10_to_12(
        version: int, method: str, args: list[Any], ids: Any) -> None:
    g, raw = _guard("res.partner", method, version=version, ids=ids)
    with pytest.raises(PolicyDenied) as info:
        g.execute("res.partner", method, args, {}, ids=ids)
    assert (info.value.rule, info.value.layer) == ("context", "B")
    assert f"context key 'default_child_ids', {PLACE}" in str(info.value)
    assert MARKER not in str(info.value)
    assert raw.calls == [] and raw.metadata == []


@pytest.mark.parametrize("version", [13, 17, 19])
def test_from_13_the_guard_leaves_a_positional_object_to_the_values_checks(
        version: int) -> None:
    # Odoo 13+ reads no positional context: the object is a value of the method, checked as
    # before (Layer A refused it already, on every series).
    g, raw = _guard("res.partner", "action_confirm", version=version, ids=[3])
    g.execute("res.partner", "action_confirm", [LIST], {}, ids=[3])
    assert raw.sent() == [("res.partner", "action_confirm")]


@pytest.mark.parametrize(("version", "rule"), [(12, "context"), (13, "shape")])
def test_series_12_and_13_for_an_argument_after_the_parameters(version: int,
                                                                rule: str) -> None:
    g, raw = _guard("res.partner", "create", version=version)
    with pytest.raises(PolicyDenied) as info:
        g.execute("res.partner", "create", [{"name": "x"}, LIST], {})
    assert (info.value.rule, info.value.layer) == (rule, "B")
    assert raw.calls == []


@pytest.mark.parametrize(("version", "sent"), [(12, False), (13, True)])
def test_series_12_and_13_for_a_structural_default_on_a_creating_call(version: int,
                                                                     sent: bool) -> None:
    g, raw = _guard("res.partner", "action_confirm", version=version, ids=[3])
    if sent:
        g.execute("res.partner", "action_confirm", [{"default_public": True}], {}, ids=[3])
        assert raw.sent() == [("res.partner", "action_confirm")]
        return
    with pytest.raises(PolicyDenied) as info:
        g.execute("res.partner", "action_confirm", [{"default_public": True}], {}, ids=[3])
    assert (info.value.rule, info.value.layer) == ("context", "B")
    assert STRUCTURAL in str(info.value) and raw.calls == []


@pytest.mark.parametrize(("model", "method", "args", "ids"), [
    ("res.partner", "action_confirm", [{"default_name": "x"}], [3]),
    ("res.partner", "x_model_method", [{"default_type": "contact", "lang": "es_MX"}], None),
    ("res.partner", "search_count", [[], {"lang": "es_MX"}], None),
    ("product.product", "x_set_values", [{"default_code": "A-1"}], [1]),
    ("product.product", "x_set_values", [{"default_code": "A-1", "name": "Widget"}], [1]),
])
def test_the_guard_on_12_lets_a_scalar_default_and_a_values_object_through(
        model: str, method: str, args: list[Any], ids: Any) -> None:
    g, raw = _guard(model, method, version=12, ids=ids)
    g.execute(model, method, args, {}, ids=ids)
    assert raw.sent() == [(model, method)]


def test_the_guard_on_12_applies_the_structural_values_rule_of_a_named_default() -> None:
    # default_res_model on an ir.attachment call must name a parent the agent may write, as
    # the same key by name does (design 4.5); payment.provider is a secrets-tier model.
    g, raw = _guard("ir.attachment", "x_bind", version=12, ids=[6])
    with pytest.raises(PolicyDenied) as info:
        g.execute("ir.attachment", "x_bind", [{"default_res_model": "payment.provider"}], {},
                  ids=[6])
    assert (info.value.rule, info.value.layer) == ("tier:secrets", "B")
    assert raw.calls == []


def test_the_guard_counts_a_series_it_cannot_tell_as_10_to_12() -> None:
    class Unknown(ScriptedSession):
        def facts(self) -> Any:
            return SimpleNamespace(version=None)

    g, raw = _guard("res.partner", "action_confirm", version=17, ids=[3], session=Unknown())
    with pytest.raises(PolicyDenied) as info:
        g.execute("res.partner", "action_confirm", [LIST], {}, ids=[3])
    assert info.value.rule == "context" and raw.calls == []


def test_the_guard_reads_the_series_only_when_an_object_is_passed_positionally() -> None:
    class Counting(ScriptedSession):
        asked = 0

        def facts(self) -> Any:
            Counting.asked += 1
            return super().facts()

    raw = Counting(version=12)
    g, _raw = _guard("res.partner", "action_confirm", version=12, ids=[3], session=raw)
    g.execute("res.partner", "action_confirm", [], {}, ids=[3])
    g.execute("res.partner", "action_confirm", ["a word"], {}, ids=[3])
    assert Counting.asked == 0


def test_full_is_unchanged_in_the_guard() -> None:
    g, raw = _guard("res.partner", "action_confirm", version=12, ids=[3],
                    p=Policy(profile_name="full"))
    g.execute("res.partner", "action_confirm", [LIST], {}, ids=[3])
    assert raw.sent() == [("res.partner", "action_confirm")]


# --- how the objects are found (classify) ------------------------------------------------------

CTX = {"lang": "es_MX"}
CTX2 = {"tz": "UTC"}


@pytest.mark.parametrize(("method", "args", "ids_given", "certain", "possible"), [
    ("create", [{"name": "x"}, CTX], False, [CTX], []),
    ("write", [[3], {"name": "x"}, CTX], False, [CTX], []),
    ("write", [{"name": "x"}, CTX], True, [CTX], []),
    ("search_count", [[], CTX], False, [CTX], []),
    ("read_group", [[], ["a"], ["b"], CTX], False, [CTX], []),  # extract refuses the shape
    ("search_read", [[], ["name"], 0, 5, "name"], False, [], []),
    ("copy_data", [[3], {"name": "Copy"}], False, [], []),   # an object parameter
    ("onchange", [[3], {"name": "x"}, ["name"], {"name": {}}], False, [], []),
    ("update_field_translations", [[3], "name", {"fr_FR": "x"}], False, [], []),
    ("action_confirm", [[3], CTX, "x", CTX2], False, [], [CTX, CTX2]),
    ("action_confirm", [CTX], True, [], [CTX]),
    ("action_confirm", "not a list", False, [], []),
    ("action_confirm", None, False, [], []),
])
def test_positional_contexts(method: str, args: Any, ids_given: bool, certain: list[Any],
                             possible: list[Any]) -> None:
    found = positional_contexts(method, args, ids_given=ids_given)
    assert (found.certain, found.possible) == (certain, possible)


def test_the_object_parameters_are_named_and_read_nothing() -> None:
    # Every parameter without a role takes no object, so an object there can only be a
    # context; the three that take one say so (OBJECT), and their objects are not read.
    marked = {(method, name) for method, shape in ARG_SHAPES.items()
              for name, role in shape.params if role == OBJECT}
    assert marked == {("copy_data", "default"), ("onchange", "values"),
                      ("update_field_translations", "translations")}
    parts = extract("copy_data", [[3], {"name": "Copy"}])
    assert (parts.values, parts.paths, parts.contexts) == ([], [], [])


def test_the_last_series_that_reads_a_positional_context_is_12() -> None:
    assert POSITIONAL_CONTEXT_UNTIL == 12


# --- a context given as [key, value] pairs ----------------------------------------------------
# Odoo 10 to 12 build a positional context with dict(arg), which also takes a list of pairs:
# [["default_child_ids", ...]] is the context {"default_child_ids": ...}. Such a list is read
# as the context it builds, with the same rules as an object.

PAIRS = [["default_child_ids", [[0, 0, {"name": MARKER}]]]]
EVERY_SERIES = [10, 11, 12, 13, 17, 19]


@pytest.mark.parametrize("version", EVERY_SERIES)
@pytest.mark.parametrize(("method", "arguments"), [
    ("action_confirm", {"ids": [3], "args": [PAIRS]}),                  # any other method, ids=
    ("action_confirm", {"args": [[3], PAIRS]}),                         # legacy form
    ("x_model_method", {"args": [PAIRS]}),                              # model method
    ("create", {"args": [{"name": "x"}, PAIRS]}),                       # after the parameters
    ("search_count", {"args": [[], PAIRS]}),                            # search_count's limit
    ("action_confirm", {"ids": [3], "args": [tuple(tuple(p) for p in PAIRS)]}),  # tuples
    # whatever dict() takes as a pair rides along: an x2many command, a two-letter text
    ("action_confirm", {"ids": [3], "args": [[*PAIRS, [4, 5]]]}),
    ("action_confirm", {"ids": [3], "args": [[*PAIRS, "ab"]]}),
])
def test_a_list_default_given_as_pairs_stops_at_layer_a_on_every_series(
        version: int, method: str, arguments: dict[str, Any]) -> None:
    raw = ScriptedSession(version=version)
    err, text = _execute(raw, "res.partner", method, **arguments)
    _stopped_at_layer_a(raw, err, text, "default_child_ids")


@pytest.mark.parametrize("version", EVERY_SERIES)
@pytest.mark.parametrize("pairs", [
    [["default_public", True]],
    [{"default_public": 1, "x": 0}],  # dict() takes a two-key object as the pair of its keys
])
def test_a_structural_default_given_as_pairs_stops_at_layer_a_on_every_series(
        version: int, pairs: list[Any]) -> None:
    raw = ScriptedSession(version=version)
    err, text = _execute(raw, "res.partner", "action_confirm", ids=[3], args=[pairs])
    _stopped_at_layer_a(raw, err, text, "default_public", hint=STRUCTURAL)


@pytest.mark.parametrize("version", EVERY_SERIES)
def test_a_key_outside_the_allowlist_given_as_pairs_at_search_counts_limit_is_refused(
        version: int) -> None:
    raw = ScriptedSession(version=version)
    err, text = _execute(raw, "res.partner", "search_count",
                         args=[[], [["tracking_disable", True]]])
    assert err is True and raw.calls == [] and raw.metadata == [], text
    assert f"context key 'tracking_disable', {PLACE}, is not allowed" in text, text
    assert REMEDY in text and "rule context)" in text


@pytest.mark.parametrize(("version", "refused_here"), [(12, True), (13, False)])
@pytest.mark.parametrize(("method", "args", "ids", "key"), [
    ("action_confirm", [PAIRS], [3], "default_child_ids"),
    ("action_confirm", [[["default_public", True]]], [3], "default_public"),
    ("search_count", [[], [["tracking_disable", True]]], None, "tracking_disable"),
])
def test_the_guard_on_12_and_13_for_a_context_given_as_pairs(
        version: int, refused_here: bool, method: str, args: list[Any], ids: Any,
        key: str) -> None:
    g, raw = _guard("res.partner", method, version=version, ids=ids)
    if not refused_here:  # from 13 the list is a value (Layer A refused it on every series)
        g.execute("res.partner", method, args, {}, ids=ids)
        assert raw.sent() == [("res.partner", method)]
        return
    with pytest.raises(PolicyDenied) as info:
        g.execute("res.partner", method, args, {}, ids=ids)
    assert (info.value.rule, info.value.layer) == ("context", "B")
    assert f"context key '{key}', {PLACE}" in str(info.value)
    assert MARKER not in str(info.value) and raw.calls == [] and raw.metadata == []


ORDINARY_LISTS = [
    [["name", "=", "x"]],                                 # a domain: its leaves have 3 items
    ["|", ["name", "=", "x"], ["name", "=", "y"]],        # a domain with an operator
    ["name", "email"],                                    # a field list
    ["id", "vat"],                                        # two-letter names: still names
    [],                                                   # an empty list
    [1, 2, 3],                                            # ids
]


@pytest.mark.parametrize("version", [12, 13])
@pytest.mark.parametrize("value", ORDINARY_LISTS)
@pytest.mark.parametrize("slot", ["business method", "search_count's limit"])
def test_a_list_that_builds_no_context_still_runs_in_those_slots(version: int, value: Any,
                                                                  slot: str) -> None:
    # Layer A, then the guard on 12 (which reads positional contexts) and 13 (which does not).
    raw = ScriptedSession(version=version)
    if slot == "business method":
        method, arguments = "action_confirm", {"ids": [3], "args": [value]}
    else:
        method, arguments = "search_count", {"args": [[], value]}
    err, text = _execute(raw, "res.partner", method, **arguments)
    assert err is False, text
    assert raw.call("res.partner", method)[0] == arguments["args"]  # sent as given


@pytest.mark.parametrize("version", [12, 13])
@pytest.mark.parametrize("value", [
    [[4, 5], [4, 6]],                          # x2many links: pairs without a text key
    [["draft", "Draft"], ["done", "Done"]],    # selection pairs, no default_ key
    [["Acme", "a@example.com"]],               # a row of two columns
    ["fr", "es"],                              # langs
])
def test_a_business_methods_list_of_pairs_without_a_context_default_runs(version: int,
                                                                         value: Any) -> None:
    raw = ScriptedSession(version=version)
    err, text = _execute(raw, "res.partner", "action_confirm", ids=[3], args=[value])
    assert err is False, text
    assert ("res.partner", "action_confirm") in raw.sent()


@pytest.mark.parametrize("version", [12, 13])
def test_an_import_with_two_columns_still_runs(version: int) -> None:
    # load()'s rows are values (ROWS): a two-column row is a pair of texts, never a context.
    raw = ScriptedSession(version=version)
    rows = [["Acme", "acme@example.com"], ["Beta", "beta@example.com"]]
    err, text = _execute(raw, "res.partner", "load", args=[["name", "email"], rows])
    assert err is False, text
    assert raw.call("res.partner", "load")[0] == [["name", "email"], rows]
    err, text = call(server(ScriptedSession(version=version), p=policy("standard")),
                     "odoo_import", model="res.partner", fields=["name", "email"], rows=rows)
    assert err is False, text


@pytest.mark.parametrize("version", [12, 13])
def test_langs_still_run_in_get_field_translations(version: int) -> None:
    raw = ScriptedSession(version=version)
    err, text = _execute(raw, "res.partner", "get_field_translations", ids=[3],
                         args=["name", ["fr", "es_MX"]])
    assert err is False, text


def test_a_safe_context_given_as_pairs_runs_on_12() -> None:
    raw = ScriptedSession(version=12)
    pairs = [["lang", "es_MX"], ["default_name", "x"]]
    err, text = _execute(raw, "res.partner", "action_confirm", ids=[3], args=[pairs])
    assert err is False, text
    assert raw.call("res.partner", "action_confirm")[0] == [pairs]  # sent as given


def test_full_forwards_a_context_given_as_pairs_unchanged() -> None:
    raw = ScriptedSession(version=12)
    err, text = _execute(raw, "res.partner", "action_confirm", p=Policy(profile_name="full"),
                         ids=[3], args=[PAIRS])
    assert err is False, text
    assert raw.call("res.partner", "action_confirm")[0] == [PAIRS]


def test_a_named_context_given_as_pairs_is_still_a_shape_refusal() -> None:
    # By name a context must be an object, as before (stricter than Odoo, never weaker).
    raw = ScriptedSession(version=12)
    err, text = _execute(raw, "res.partner", "action_confirm", ids=[3],
                         kwargs={"context": [["lang", "es_MX"]]})
    assert err is True and "rule shape)" in text and raw.calls == [], text


@pytest.mark.parametrize(("value", "built"), [
    ({"lang": "es_MX"}, {"lang": "es_MX"}),
    ([["lang", "es_MX"], ["default_x", 1]], {"lang": "es_MX", "default_x": 1}),
    ((("lang", "es_MX"),), {"lang": "es_MX"}),
    ([["a", 1], ["a", 2]], {"a": 2}),                       # a later pair wins, as in dict()
    ([["default_x", [1]], [4, 5]], {"default_x": [1], 4: 5}),
    ([["default_x", [1]], "ab"], {"default_x": [1], "a": "b"}),
    ([{"default_public": 1, "x": 0}], {"default_public": "x"}),
    ([[4, 5]], {4: 5}),
    ([["name", "=", "x"]], None),                           # a domain leaf has three items
    (["|", ["a", "=", 1], ["b", "=", 2]], None),
    (["name", "email"], None),                              # text only: names
    (["id", "vat"], None),
    (["fr", "es"], None),
    ([], None),
    ([1, 2], None),                                         # ids
    ([[["unhashable"], 1]], None),                          # dict() fails in Odoo as well
    ([["a", 1], "abc"], None),                              # an item of three letters
    ([["a", 1], "x" * 100_000], None),                      # refused by length, not copied
    ("lang", None),
    (5, None),
    (None, None),
])
def test_as_context_builds_what_dict_builds(value: Any, built: Any) -> None:
    assert as_context(value) == built


def test_positional_contexts_reads_pairs_as_the_context_they_build() -> None:
    found = positional_contexts("action_confirm", [[3], [["lang", "es_MX"]], ["a", "b"]],
                                ids_given=False)
    assert (found.certain, found.possible) == ([], [{"lang": "es_MX"}])
    found = positional_contexts("search_count", [[], [["tracking_disable", True]]],
                                ids_given=False)
    assert (found.certain, found.possible) == ([{"tracking_disable": True}], [])
    found = positional_contexts("load", [["name", "email"], [["Acme", "a@example.com"]]],
                                ids_given=False)
    assert (found.certain, found.possible) == ([], [])


def test_load_rows_are_the_one_parameter_of_pairs_and_read_nothing() -> None:
    marked = {(method, name) for method, shape in ARG_SHAPES.items()
              for name, role in shape.params if role == ROWS}
    assert marked == {("load", "data")}
    parts = extract("load", [["name", "email"], [["Acme", "a@example.com"]]])
    assert (parts.values, parts.paths, parts.contexts) == ([], [], [])
    assert parts.columns == [(("name",), False), (("email",), False)]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
