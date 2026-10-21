# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""How the policy reads a call: method classes, argument shapes, field paths.

Every shape the tools send today (and the ``odoo_execute`` forms, positional
and ``ids=``) is read here the way Odoo binds it, and whatever the table cannot
read with certainty is a ``shape`` refusal, never a guess.
"""

from __future__ import annotations

from typing import Any

import pytest

from odoo_mcp.policy import classify
from odoo_mcp.policy.classify import (
    ARG_SHAPES,
    CREATE_METHODS,
    CREATE_WRITE_METHODS,
    INSPECT_METHODS,
    METHOD_CLASSES,
    READ_METHODS,
    UNLINK_METHODS,
    VALUE_CHECKED,
    WRITE_METHODS,
    ShapeError,
    column_paths,
    domain_paths,
    extract,
    is_internal_note,
    method_class,
    method_ops,
    order_paths,
    specification_paths,
    term_paths,
    valid_method,
    valid_model,
)
from odoo_mcp.transport import fallback
from odoo_mcp.transport.json2_signatures import MODEL_SIGNATURES, SERIES_VARIANTS, SIGNATURES

# --- method classes ---------------------------------------------------------------


def test_the_policy_reads_exactly_what_the_transport_replays_as_reads() -> None:
    # Design 9.2 #9: equality, not only a subset. A read method added to the
    # transport has to be classified here, and the other way round. The design
    # counted 22; copy_data, a read of the records, makes 23.
    assert INSPECT_METHODS | READ_METHODS == fallback.READ_METHODS
    assert len(fallback.READ_METHODS) == 23


def test_every_method_json2_marks_readonly_is_a_read_or_an_inspect() -> None:
    readonly = {name for name, sig in SIGNATURES.items() if sig.readonly}
    readonly |= {name for (_model, name), sig in MODEL_SIGNATURES.items() if sig.readonly}
    readonly |= {name for name, variants in SERIES_VARIANTS.items()
                 for v in variants if v.signature is not None and v.signature.readonly}
    assert readonly <= READ_METHODS | INSPECT_METHODS


def test_the_method_classes_are_disjoint() -> None:
    seen: set[str] = set()
    for _name, methods in METHOD_CLASSES:
        assert not seen & methods
        seen |= methods


@pytest.mark.parametrize(("method", "cls", "ops"), [
    ("fields_get", "inspect", ("inspect",)),
    ("has_group", "inspect", ("inspect",)),
    ("search_read", "read", ("read",)),
    ("export_data", "read", ("read",)),
    ("copy_data", "read", ("read",)),  # the values a duplicate would get
    ("create", "create", ("create",)),
    ("copy", "create", ("create",)),
    ("write", "write", ("write",)),
    ("update", "write", ("write",)),  # BaseModel.update assigns the fields: a write
    ("action_archive", "write", ("write",)),
    ("load", "create_write", ("create", "write")),
    ("web_save", "create_write", ("create", "write")),
    ("unlink", "unlink", ("unlink",)),
    ("action_confirm", "call", ("call",)),
    ("message_post", "call", ("call",)),
])
def test_method_classes(method: str, cls: str, ops: tuple[str, ...]) -> None:
    assert method_class(method) == cls
    assert method_ops(method) == ops


def test_every_value_checked_method_has_an_argument_shape() -> None:
    checked = READ_METHODS | CREATE_METHODS | WRITE_METHODS | CREATE_WRITE_METHODS | UNLINK_METHODS
    assert {method_class(m) for m in checked} == VALUE_CHECKED
    assert checked == set(ARG_SHAPES)


def test_the_shapes_agree_with_the_json2_signature_table() -> None:
    for method, shape in ARG_SHAPES.items():
        signature = SIGNATURES.get(method)
        if signature is not None:
            names = tuple(name for name, _role in shape.params)
            assert names[:len(signature.params)] == signature.params, method
            assert shape.record is not signature.model_level, method
        for variant in SERIES_VARIANTS.get(method, ()):
            if variant.signature is not None:
                for name in variant.signature.params:
                    assert shape.knows(shape.aliases.get(name, name)), (method, name)


@pytest.mark.parametrize(("name", "valid"), [("res.partner", True), ("x_custom", True),
                                             ("ir.model.fields", True), ("Res.Partner", False),
                                             ("res partner", False), ("res.partner\n", False),
                                             ("", False), ("a" * 128, True), ("a" * 129, False)])
def test_model_names(name: str, valid: bool) -> None:
    assert valid_model(name) is valid


@pytest.mark.parametrize(("name", "valid"), [("action_confirm", True), ("Action", True),
                                             ("_private", False), ("1x", False),
                                             ("a-b", False), ("write\n", False),
                                             ("m" * 128, True), ("m" * 129, False)])
def test_method_names(name: str, valid: bool) -> None:
    assert valid_method(name) is valid


# --- the shapes the tools send ------------------------------------------------------

def P(*paths: str) -> list[tuple[str, ...]]:
    return [tuple(path.split(".")) for path in paths]


TOOL_SHAPES: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = [
    # (where it comes from, method, call, expected parts)
    ("odoo_search", "search",
     {"args": [[["partner_id.country_id", "=", 1]]],
      "kwargs": {"limit": 5, "offset": 0, "order": "name desc"}},
     {"paths": P("partner_id.country_id", "name")}),
    ("odoo_search_count", "search_count", {"args": [[["state", "=", "draft"]]]},
     {"paths": P("state")}),
    ("odoo_read", "read", {"args": [[1, 2]], "kwargs": {"fields": ["name", "email"]}},
     {"ids": [1, 2], "paths": P("name", "email")}),
    ("odoo_search_read", "search_read",
     {"args": [[]], "kwargs": {"fields": ["name"], "limit": 10, "order": "id"}},
     {"paths": P("name", "id")}),
    ("odoo_create", "create", {"args": [{"name": "Acme"}]}, {"values": [{"name": "Acme"}]}),
    ("odoo_write", "write", {"args": [[3], {"email": "a@b.c"}]},
     {"ids": [3], "values": [{"email": "a@b.c"}]}),
    ("odoo_unlink", "unlink", {"args": [[3]]}, {"ids": [3]}),
    ("odoo_read_group classic", "read_group",
     {"args": [[["stage_id", "!=", False]], ["stage_id", "expected_revenue:sum"], ["stage_id"]],
      "kwargs": {"limit": 3, "offset": 0, "orderby": "stage_id desc", "lazy": True}},
     {"paths": P("stage_id", "stage_id", "expected_revenue", "stage_id", "stage_id")}),
    ("odoo_read_group formatted", "formatted_read_group",
     {"args": [[]], "kwargs": {"groupby": ["date:month"], "aggregates": ["__count", "amount:sum"],
                               "order": "date:month desc", "limit": 4,
                               "context": {"read_group_expand": True}}},
     {"paths": P("date", "amount", "date"), "contexts": [{"read_group_expand": True}]}),
    ("session.fields_get", "fields_get", {"args": [], "kwargs": {"attributes": ["type"]}}, {}),
    ("odoo_translate_get", "read",
     {"args": [[7], ["name"]], "kwargs": {"context": {"lang": "es_MX"}}},
     {"ids": [7], "paths": P("name"), "contexts": [{"lang": "es_MX"}]}),
    ("odoo_translate_set 16+", "update_field_translations",
     {"args": [[7], "name", {"es_MX": "Hola"}]}, {"ids": [7], "paths": P("name")}),
    ("odoo_translate_set <=15", "write",
     {"args": [[7], {"name": "Hola"}], "kwargs": {"context": {"lang": "es_MX"}}},
     {"ids": [7], "values": [{"name": "Hola"}], "contexts": [{"lang": "es_MX"}]}),
    ("odoo_list_models", "search_read",
     {"args": [["|", ("model", "ilike", "sale"), ("name", "ilike", "sale")]],
      "kwargs": {"fields": ["model", "name"], "limit": 200}},
     {"paths": P("model", "name", "model", "name")}),
    ("odoo_online_profile apikeys", "search_read",
     {"args": [[["user_id", "=", 2]]], "kwargs": {"fields": ["name", "expiration_date"]}},
     {"paths": P("user_id", "name", "expiration_date")}),
    ("odoo_online_profile modules", "search_read",
     {"args": [[["state", "=", "installed"], "|", ["application", "=", True],
                ["name", "=", "web_studio"]]],
      "kwargs": {"fields": ["name"], "order": "name"}},
     {"paths": P("state", "application", "name", "name", "name")}),
    ("odoo_access_check 18+", "has_access", {"args": ["read"], "ids": [1, 2]}, {"ids": [1, 2]}),
    ("odoo_access_check 10-17", "check_access_rights",
     {"args": ["read"], "kwargs": {"raise_exception": False}}, {}),
    ("odoo_record_documents", "search_read",
     {"args": [[["res_model", "=", "account.move"], ["res_id", "=", 9]]],
      "kwargs": {"fields": ["name", "mimetype"], "limit": 50,
                 "order": "create_date desc, id desc"}},
     {"paths": P("res_model", "res_id", "name", "mimetype", "create_date", "id")}),
    ("odoo_import_preview create", "create",
     {"args": [{"res_model": "res.partner", "file": "a\n", "file_type": "text/csv",
                "file_name": "x.csv"}]},
     {"values": [{"res_model": "res.partner", "file": "a\n", "file_type": "text/csv",
                  "file_name": "x.csv"}]}),
    ("odoo_import_preview execute", "execute_import",
     {"args": [[5], ["name"], ["name"], {}], "kwargs": {"dryrun": True}}, {}),
    ("odoo_import", "load", {"args": [["name", "parent_id/id", "child_ids/name"], [["a", "", ""]]]},
     {"columns": [(("name",), False), (("parent_id",), True), (("child_ids", "name"), False)]}),
    ("session.module_installed", "search_count",
     {"args": [[["name", "=", "base_import"], ["state", "=", "installed"]]]},
     {"paths": P("name", "state")}),
    ("session.name_get", "read", {"args": [[1, 2]], "kwargs": {"fields": ["display_name"]}},
     {"ids": [1, 2], "paths": P("display_name")}),
    ("odoo_add_field model_id", "search", {"args": [[["model", "=", "res.partner"]]],
                                           "kwargs": {"limit": 1}},
     {"paths": P("model")}),
    ("odoo_add_automation unlink", "unlink", {"args": [[11]]}, {"ids": [11]}),
]


@pytest.mark.parametrize(("where", "method", "call", "parts"), TOOL_SHAPES,
                         ids=[row[0] for row in TOOL_SHAPES])
def test_every_shape_the_tools_send(where: str, method: str, call: dict[str, Any],
                                    parts: dict[str, Any]) -> None:
    kwargs = {"ids": call["ids"]} if "ids" in call else {}
    got = extract(method, call.get("args"), call.get("kwargs"), **kwargs)
    assert got.method == method and got.cls == method_class(method)
    for name in ("ids", "paths", "values", "columns", "contexts"):
        expected = parts.get(name, None if name == "ids" else [])
        assert getattr(got, name) == expected, (where, name)


# --- odoo_execute: the legacy positional form and the ids= form --------------------------

@pytest.mark.parametrize(("method", "legacy", "ids_form", "expected"), [
    ("write", {"args": [[1], {"name": "x"}]}, {"ids": [1], "args": [{"name": "x"}]},
     {"values": [{"name": "x"}]}),
    ("write", {"args": [[1]], "kwargs": {"vals": {"name": "x"}}},
     {"ids": [1], "kwargs": {"values": {"name": "x"}}}, {"values": [{"name": "x"}]}),
    ("copy", {"args": [[1], {"name": "Copy"}]},
     {"ids": [1], "kwargs": {"default": {"name": "Copy"}}},
     {"values": [{"name": "Copy"}]}),
    ("update", {"args": [[1], {"email": "x@example.com"}]},
     {"ids": [1], "kwargs": {"values": {"email": "x@example.com"}}},
     {"values": [{"email": "x@example.com"}]}),
    ("copy_data", {"args": [[1], {"name": "Copy"}]},
     {"ids": [1], "kwargs": {"default": {"name": "Copy"}}}, {}),  # it writes nothing
    ("unlink", {"args": [[4, 5]]}, {"ids": [4, 5]}, {}),
    ("web_read", {"args": [[1], {"partner_id": {"fields": {"display_name": {}}}}]},
     {"ids": [1], "kwargs": {"specification": {"partner_id": {"fields": {"display_name": {}}}}}},
     {"paths": P("partner_id", "partner_id.display_name")}),
    ("export_data", {"args": [[1], ["name", "partner_id/name", "partner_id/id"]]},
     {"ids": [1], "kwargs": {"fields_to_export": ["name", "partner_id/name", "partner_id/id"]}},
     {"paths": P("name", "partner_id.name", "partner_id")}),
    ("web_save", {"args": [[], {"name": "x"}, {"display_name": {}}]},
     {"ids": [], "kwargs": {"vals": {"name": "x"}, "specification": {"display_name": {}}}},
     {"values": [{"name": "x"}], "paths": P("display_name")}),
    ("get_field_translations", {"args": [[1], "name"]},
     {"ids": [1], "kwargs": {"field_name": "name"}},
     {"paths": P("name")}),
])
def test_both_odoo_execute_forms_read_the_same(method: str, legacy: dict[str, Any],
                                               ids_form: dict[str, Any],
                                               expected: dict[str, Any]) -> None:
    a = extract(method, legacy.get("args"), legacy.get("kwargs"))
    b = extract(method, ids_form.get("args"), ids_form.get("kwargs"), ids=ids_form["ids"])
    assert a.ids == b.ids == ids_form["ids"]
    for name in ("paths", "values", "columns"):
        assert getattr(a, name) == getattr(b, name) == expected.get(name, []), name


@pytest.mark.parametrize(("method", "args", "kwargs", "expected"), [
    ("create", [[{"name": "a"}, {"name": "b"}]], None, {"values": [{"name": "a"}, {"name": "b"}]}),
    ("create", None, {"vals": {"name": "a"}}, {"values": [{"name": "a"}]}),
    ("create", None, {"vals_list": [{"name": "a"}]}, {"values": [{"name": "a"}]}),
    ("search", None, {"args": [["name", "=", "x"]], "count": True}, {"paths": P("name")}),
    ("name_search", ["acme"], {"args": [["customer_rank", ">", 0]], "limit": 5},
     {"paths": P("customer_rank")}),
    ("default_get", [["name", "email"]], None, {"paths": P("name", "email")}),
    ("default_get", None, {"fields_list": ["name"]}, {"paths": P("name")}),
    ("web_search_read", [[["active", "=", True]], {"name": {}, "child_ids": {
        "fields": {"email": {}}, "order": "name", "context": {"active_test": False}}}],
     {"limit": 80}, {"paths": P("active", "name", "child_ids", "child_ids.email",
                               "child_ids.name"), "contexts": [{"active_test": False}]}),
    ("read_group", [[], ["total:sum(amount)", "partner_id.country_id"]],
     {"groupby": "partner_id", "orderby": "total desc"},
     {"paths": P("amount", "partner_id.country_id", "partner_id", "total")}),
    ("read_group", [[]], {"groupby": ["partner_id"], "aggregates": ["amount:sum"],
                         "having": [["amount:sum", ">", 10]], "order": "partner_id"},
     {"paths": P("partner_id", "amount", "amount", "partner_id")}),
    ("web_read_group", [[]], {"groupby": ["stage_id"], "aggregates": ["__count"],
                             "unfold_read_specification": {"name": {}},
                             "groupby_read_specification": {"stage_id": {"sequence": {}}}},
     {"paths": P("stage_id", "name", "stage_id", "stage_id.sequence")}),
    ("load", None, {"fields": ["id", "order_line/product_id/.id"], "data": [["x", "1"]]},
     {"columns": [((), True), (("order_line", "product_id"), True)]}),
    ("message_post", [[1]], {"body": "x"}, {}),  # a business method: nothing to read
])
def test_keyword_aliases_and_nested_parts(method: str, args: Any, kwargs: Any,
                                          expected: dict[str, Any]) -> None:
    got = extract(method, args, kwargs)
    for name in ("paths", "values", "columns", "contexts"):
        assert getattr(got, name) == expected.get(name, []), name


# --- what cannot be read is refused ----------------------------------------------------

@pytest.mark.parametrize(("method", "args", "kwargs", "ids"), [
    ("search", [[]], {"unknown": 1}, None),
    ("search", [[]], {"<script>": 1}, None),
    ("search", [[], 0], {"offset": 1}, None),  # given twice
    ("search", None, {"domain": [], "args": []}, None),  # the alias of the same parameter
    ("unlink", [[1], "extra"], None, None),
    ("create", [{"name": "x"}], None, [1]),  # a model method with ids
    ("read_group", [[], ["a"], ["b"], 0], None, None),  # positions differ on 20.0
    ("web_read_group", [[], ["stage_id"]], None, None),  # positions differ from saas~18.4
    ("web_read_group", [[]], {"opening_info": []}, None),
    ("search", ["not a domain"], None, None),
    ("search", [[["name", "="]]], None, None),
    ("search", [[["name", 1, "x"]]], None, None),
    ("search", [[["name with space", "=", "x"]]], None, None),
    ("search", [["&&", ["a", "=", 1]]], None, None),
    ("search", [[[True, "=", 1]]], None, None),
    ("search", [[["a", "any", "not a domain"]]], None, None),
    ("search_read", [[]], {"fields": "name"}, None),
    ("search_read", [[]], {"order": "name; drop table"}, None),
    ("search_read", [[]], {"order": "name,"}, None),
    ("search_read", [[]], {"order": 5}, None),
    ("web_read", [[1], {"partner_id": {"fields": {}, "domain": []}}], None, None),
    ("web_read", [[1], {"partner_id": "x"}], None, None),
    ("web_read", [[1], ["name"]], None, None),
    ("export_data", [[1], ["partner_id/.id/name"]], None, None),
    ("export_data", [[1], ["partner_id:id"]], None, None),
    ("write", [[1], "not values"], None, None),
    ("write", [[1], {"a.b": 1}], None, None),
    ("create", [[{"name": "x"}, "y"]], None, None),
    ("update_field_translations", [[1], ["name"], {}], None, None),
    ("read_group", [[], ["!bad"], ["x"]], None, None),
    ("search", "not a list", None, None),
    ("search", [[]], ["not", "an", "object"], None),
])
def test_unknown_shapes_are_refused(method: str, args: Any, kwargs: Any, ids: Any) -> None:
    extra = {"ids": ids} if ids is not None else {}
    with pytest.raises(ShapeError) as raised:
        extract(method, args, kwargs, **extra)
    assert raised.value.method == method
    assert "<script>" not in str(raised.value) and "drop table" not in str(raised.value)


def test_nesting_has_a_limit() -> None:
    domain: Any = [["name", "=", "x"]]
    for _ in range(classify.MAX_DEPTH):
        domain = [["child_ids", "any", domain]]
    assert len(domain_paths(domain)[-1]) == classify.MAX_DEPTH + 1
    with pytest.raises(ShapeError):
        domain_paths([["child_ids", "any", domain]])
    spec: Any = {"name": {}}
    for _ in range(classify.MAX_DEPTH + 1):
        spec = {"child_ids": {"fields": spec}}
    with pytest.raises(ShapeError):
        specification_paths(spec)


# --- the path parsers ------------------------------------------------------------------

def test_domain_paths_continue_through_any_and_not_any() -> None:
    domain = ["|", ["partner_id", "any", [["signup_token", "=like", "a%"]]],
              "!", ("child_ids", "NOT ANY", [["user_ids.login", "=", "x"]]),
              (1, "=", 1), [0, "=", 1]]
    assert domain_paths(domain) == P("partner_id", "partner_id.signup_token", "child_ids",
                                     "child_ids.user_ids.login")
    assert domain_paths(None) == [] and domain_paths(False) == []


def test_having_leaves_name_aggregates() -> None:
    assert domain_paths([["amount:sum", ">", 10], ["__count", ">", 1]], aggregates=True) == P(
        "amount", "__count")
    with pytest.raises(ShapeError):
        domain_paths([["amount:sum", "any", []]], aggregates=True)


@pytest.mark.parametrize(("terms", "paths"), [
    (["stage_id", "date:month", "partner_id.country_id"],
     P("stage_id", "date", "partner_id.country_id")),
    (["amount:sum", "__count", "total:sum(amount)", "n:count_distinct(partner_id.email)"],
     P("amount", "amount", "partner_id.email")),
    ("partner_id", P("partner_id")),
    (["amount:sum junk"], P("amount")),  # Odoo reads the prefix and ignores the rest
    (None, []),
])
def test_term_paths(terms: Any, paths: list[tuple[str, ...]]) -> None:
    assert term_paths(terms) == paths


@pytest.mark.parametrize(("order", "paths"), [
    ("name", P("name")),
    ("name desc, id", P("name", "id")),
    ("partner_id.name ASC NULLS LAST", P("partner_id.name")),
    ('"name" desc', P("name")),
    ("date:month desc", P("date")),
    ("", []),
    (None, []),
])
def test_order_paths(order: Any, paths: list[tuple[str, ...]]) -> None:
    assert order_paths(order) == paths


def test_column_paths_mark_references() -> None:
    assert column_paths(["id", ".id", "name", "partner_id/id", "order_line/product_id",
                         "order_line/product_id/.id"]) == [
        ((), True), ((), True), (("name",), False), (("partner_id",), True),
        (("order_line", "product_id"), False), (("order_line", "product_id"), True)]


def test_specification_contexts_are_collected() -> None:
    contexts: list[Any] = []
    specification_paths({"partner_id": {"fields": {"name": {}}, "context": {"lang": "es_MX"}}},
                        contexts=contexts)
    assert contexts == [{"lang": "es_MX"}]


def test_shape_errors_never_echo_values() -> None:
    with pytest.raises(ShapeError) as raised:
        extract("search", [[]], {"SECRET-MARKER-1 value": 1})
    assert "SECRET-MARKER" not in str(raised.value)
    assert str(raised.value) == "search: takes no keyword of that name"
    with pytest.raises(ShapeError) as named:
        extract("search", [[]], {"domian": []})
    assert str(named.value) == "search: takes no keyword 'domian'"


# --- the internal-note predicate, on its own ------------------------------------------------

@pytest.mark.parametrize(("args", "kwargs", "ids_given", "note"), [
    ([], {"subtype_xmlid": "mail.mt_note"}, True, True),
    ([[1, 2]], {"subtype": "mail.mt_note"}, False, True),
    ([[1, 2]], {"subtype": "mail.mt_note"}, True, False),  # with ids=, args are parameters
    ([], {"subtype_xmlid": "mail.mt_note", "partner_ids": [5]}, True, False),
    ([], {}, True, False),
    (None, None, False, False),
])
def test_is_internal_note(args: Any, kwargs: Any, ids_given: bool, note: bool) -> None:
    assert is_internal_note("message_post", args, kwargs, ids_given=ids_given) is note
    assert not is_internal_note("message_notify", args, kwargs, ids_given=ids_given)
