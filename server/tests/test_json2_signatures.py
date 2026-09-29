# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Contract tests of the JSON-2 positional-to-named mapping (json2_signatures)."""

from __future__ import annotations

from typing import Any

import pytest

from odoo_mcp.errors import CompatError
from odoo_mcp.transport.json2_signatures import (
    MODEL_SIGNATURES,
    SERIES_VARIANTS,
    SIGNATURES,
    Signature,
    lookup,
    to_named,
)

DOMAIN = [["is_company", "=", True]]

# (model, method, args, kwargs, series, expected body): every call the plugin makes.
CALL_SITES: list[tuple[str, str, list[Any], dict[str, Any], tuple[int, int], dict[str, Any]]] = [
    # session.module_installed
    ("ir.module.module", "search_count", [DOMAIN], {}, (19, 0), {"domain": DOMAIN}),
    # session.fields_get and odoo_fields_get
    ("res.partner", "fields_get", [], {"attributes": ["type"]}, (19, 0),
     {"attributes": ["type"]}),
    # session.name_get, odoo_read, JSON-2 sign-in
    ("res.partner", "read", [[1, 2]], {"fields": ["display_name"]}, (19, 0),
     {"ids": [1, 2], "fields": ["display_name"]}),
    # odoo_search
    ("res.partner", "search", [DOMAIN], {"limit": 5, "offset": 1, "order": "name"}, (19, 0),
     {"domain": DOMAIN, "limit": 5, "offset": 1, "order": "name"}),
    # odoo_search_read, exports, odoo_list_models, odoo_module_info
    ("res.partner", "search_read", [DOMAIN], {"fields": ["name"], "limit": 2}, (19, 0),
     {"domain": DOMAIN, "fields": ["name"], "limit": 2}),
    # odoo_create, studio
    ("res.partner", "create", [{"name": "x"}], {}, (19, 0), {"vals_list": {"name": "x"}}),
    ("res.partner", "create", [[{"name": "x"}, {"name": "y"}]], {}, (19, 0),
     {"vals_list": [{"name": "x"}, {"name": "y"}]}),
    # odoo_write
    ("res.partner", "write", [[7], {"name": "z"}], {}, (19, 0), {"ids": [7], "vals": {"name": "z"}}),
    # odoo_unlink, studio cleanup
    ("res.partner", "unlink", [[7, 8]], {}, (19, 0), {"ids": [7, 8]}),
    # odoo_read_group from saas~18.4
    ("crm.lead", "formatted_read_group", [DOMAIN],
     {"groupby": ["stage_id"], "aggregates": ["__count"], "order": "stage_id"}, (19, 0),
     {"domain": DOMAIN, "groupby": ["stage_id"], "aggregates": ["__count"], "order": "stage_id"}),
    # studio _model_id
    ("ir.model", "search", [[["model", "=", "res.partner"]]], {"limit": 1}, (19, 0),
     {"domain": [["model", "=", "res.partner"]], "limit": 1}),
    # odoo_translate_get (context hoisting, positional fields)
    ("res.partner", "read", [[3], ["name"]], {"context": {"lang": "es_MX"}}, (19, 0),
     {"ids": [3], "fields": ["name"], "context": {"lang": "es_MX"}}),
    # odoo_translate_set 16+
    ("res.partner", "update_field_translations", [[3], "name", {"es_MX": "Hola"}], {}, (19, 0),
     {"ids": [3], "field_name": "name", "translations": {"es_MX": "Hola"}}),
    # JSON-2 sign-in / odoo_online_profile
    ("res.users", "context_get", [], {}, (19, 0), {}),
    ("res.users.apikeys", "search_read", [[["user_id", "=", 2]]], {"fields": ["name"]}, (19, 0),
     {"domain": [["user_id", "=", 2]], "fields": ["name"]}),
    # odoo_access_check
    ("res.partner", "has_access", [[], "write"], {}, (19, 0), {"ids": [], "operation": "write"}),
    ("res.partner", "check_access_rights", ["read"], {"raise_exception": False}, (19, 0),
     {"operation": "read", "raise_exception": False}),
    ("res.users", "has_group", [[2], "base.group_allow_export"], {}, (19, 0),
     {"ids": [2], "group_ext_id": "base.group_allow_export"}),
    # odoo_import_preview / odoo_import
    ("base_import.import", "execute_import", [[4], ["name"], ["name"], {}], {"dryrun": True},
     (19, 0), {"ids": [4], "fields": ["name"], "columns": ["name"], "options": {}, "dryrun": True}),
    ("res.partner", "load", [["name"], [["a"]]], {}, (19, 0),
     {"fields": ["name"], "data": [["a"]]}),
    # odoo_execute favourites
    ("res.partner", "name_search", ["Az", DOMAIN, "ilike", 5], {}, (19, 0),
     {"name": "Az", "domain": DOMAIN, "operator": "ilike", "limit": 5}),
    ("res.partner", "copy", [[7], {"name": "Copy"}], {}, (19, 0),
     {"ids": [7], "default": {"name": "Copy"}}),
    ("res.partner", "name_create", ["New"], {}, (19, 0), {"name": "New"}),
    ("res.partner", "web_read", [[7], {"name": {}}], {}, (19, 0),
     {"ids": [7], "specification": {"name": {}}}),
    ("res.partner", "web_search_read", [DOMAIN, {"name": {}}], {"limit": 3}, (19, 0),
     {"domain": DOMAIN, "specification": {"name": {}}, "limit": 3}),
    ("res.partner", "get_field_translations", [[7], "name"], {}, (19, 0),
     {"ids": [7], "field_name": "name"}),
    ("res.partner", "export_data", [[7], ["name"]], {}, (19, 0),
     {"ids": [7], "fields_to_export": ["name"]}),
    # the one name that differs between JSON-2 series
    ("res.partner", "default_get", [["type"]], {}, (18, 4), {"fields_list": ["type"]}),
    ("res.partner", "default_get", [["type"]], {}, (19, 0), {"fields": ["type"]}),
    ("res.partner", "default_get", [["type"]], {}, (19, 3), {"fields": ["type"]}),
    # read_group: classic up to 19.0, the _read_group signature on 20.0+
    ("res.partner", "read_group", [DOMAIN, ["color:sum"], ["country_id"]], {"lazy": False},
     (19, 0), {"domain": DOMAIN, "fields": ["color:sum"], "groupby": ["country_id"],
               "lazy": False}),
    ("res.partner", "read_group", [DOMAIN, ["country_id"], ["color:sum"]], {}, (20, 0),
     {"domain": DOMAIN, "groupby": ["country_id"], "aggregates": ["color:sum"]}),
    # no positional args: kwargs go through untouched
    ("res.partner", "get_formview_id", [], {"ids": [1]}, (19, 0), {"ids": [1]}),
]


@pytest.mark.parametrize(("model", "method", "args", "kwargs", "series", "expected"), CALL_SITES)
def test_every_call_site_maps_to_named_arguments(model: str, method: str, args: list[Any],
                                                 kwargs: dict[str, Any],
                                                 series: tuple[int, int],
                                                 expected: dict[str, Any]) -> None:
    assert to_named(model, method, args, kwargs, series) == expected


@pytest.mark.parametrize("series", [(19, 1), (19, 2), (19, 4)])
def test_classic_read_group_is_refused_where_it_does_not_exist(series: tuple[int, int]) -> None:
    with pytest.raises(CompatError, match="formatted_read_group"):
        to_named("res.partner", "read_group", [[], ["color:sum"], ["country_id"]], {}, series)


@pytest.mark.parametrize(("method", "series"), [("check_access_rights", (19, 1)),
                                                ("name_get", (18, 4)), ("name_get", (19, 0))])
def test_removed_methods_explain_the_replacement(method: str, series: tuple[int, int]) -> None:
    with pytest.raises(CompatError) as info:
        to_named("res.partner", method, [[1]], {}, series)
    assert info.value.remediation


def test_model_methods_never_get_ids_and_record_methods_take_args0() -> None:
    assert "ids" not in to_named("res.partner", "search", [DOMAIN], {}, (19, 0))
    assert to_named("res.partner", "unlink", [5], {}, (19, 0)) == {"ids": [5]}  # int -> [int]
    assert all(SIGNATURES[m].model_level for m in ("search", "create", "fields_get", "load"))
    assert not any(SIGNATURES[m].model_level for m in ("read", "write", "unlink", "copy"))


def test_explicit_ids_are_sent_as_is_and_args_follow_them() -> None:
    body = to_named("res.partner", "write", [{"name": "z"}], {}, (19, 0), ids=[7])
    assert body == {"ids": [7], "vals": {"name": "z"}}
    # an unknown method needs no signature when every argument is named
    assert to_named("res.partner", "action_foo", [], {"flag": True}, (19, 0), ids=[1]) == {
        "ids": [1], "flag": True}


def test_unknown_positional_args_use_the_introspector_or_ask_for_kwargs() -> None:
    seen: list[tuple[str, str]] = []

    def introspect(model: str, method: str) -> Signature | None:
        seen.append((model, method))
        return Signature(False, ("view_id",)) if method == "get_formview_id" else None

    body = to_named("res.partner", "get_formview_id", [[1], 9], {}, (19, 0),
                    introspect=introspect)
    assert body == {"ids": [1], "view_id": 9} and seen == [("res.partner", "get_formview_id")]
    with pytest.raises(CompatError, match="named arguments only") as info:
        to_named("res.partner", "mystery", [[1]], {}, (19, 0), introspect=introspect)
    assert '"kwargs"' in (info.value.remediation or "") and '"ids"' in info.value.remediation


def test_too_many_or_duplicated_arguments_are_refused_locally() -> None:
    with pytest.raises(CompatError, match="positional"):
        to_named("res.partner", "search_count", [DOMAIN, 5, "extra"], {}, (19, 0))
    with pytest.raises(CompatError, match="given twice"):
        to_named("res.partner", "search", [DOMAIN], {"domain": []}, (19, 0))
    with pytest.raises(CompatError, match="given twice"):
        to_named("res.partner", "write", [[7], {}], {"ids": [8]}, (19, 0))


def test_context_is_hoisted_to_the_top_level() -> None:
    body = to_named("res.partner", "search_read", [DOMAIN],
                    {"fields": ["name"], "context": {"lang": "es_MX", "active_test": False}},
                    (19, 0))
    assert body["context"] == {"lang": "es_MX", "active_test": False}
    assert "context" not in {k for k in body if k != "context"}


def test_table_shape() -> None:
    # model-specific entries win over the generic table
    assert lookup("res.users", "has_group", (19, 0)) == MODEL_SIGNATURES[("res.users", "has_group")]
    for variants in SERIES_VARIANTS.values():
        for variant in variants:
            assert variant.until is None or variant.since < variant.until
            assert variant.signature is not None or variant.note
    assert lookup("res.partner", "no_such_method", (19, 0)) is None
    assert lookup("res.partner", "default_get", None).params == ("fields",)  # default 19.0
