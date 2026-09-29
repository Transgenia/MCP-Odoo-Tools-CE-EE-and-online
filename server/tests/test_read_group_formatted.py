# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""odoo_read_group on formatted_read_group (saas~18.4+), keeping the classic output shape."""

from __future__ import annotations

from typing import Any

import pytest

from odoo_mcp.compat import EnvFacts, method_available, resolve_method
from odoo_mcp.errors import CompatError
from odoo_mcp.registry import ToolContext
from odoo_mcp.tools.crud import odoo_read_group

FIELDS = {
    "country_id": {"type": "many2one"},
    "is_company": {"type": "boolean"},
    "color": {"type": "integer", "aggregator": "sum"},
    "name": {"type": "char"},
    "create_date": {"type": "datetime"},
    "stage_id": {"type": "many2one"},
}


class _Session:
    def __init__(self, series: tuple[int, int], rows: list[dict[str, Any]] | None = None) -> None:
        self._facts = EnvFacts(series[0], "community", "onprem", f"{series[0]}.{series[1]}",
                               series[1]).clamp()
        self.rows = rows or []
        self.calls: list[tuple[str, str, list[Any], dict[str, Any]]] = []
        self.fields_calls: list[tuple[str, list[str] | None]] = []

    def facts(self) -> EnvFacts:
        return self._facts

    def fields_get(self, model: str, attributes: list[str] | None = None) -> dict[str, Any]:
        self.fields_calls.append((model, attributes))
        return FIELDS

    def execute(self, model: str, method: str, args: list[Any] | None = None,
                kwargs: dict[str, Any] | None = None) -> Any:
        self.calls.append((model, method, args or [], kwargs or {}))
        return self.rows


def _run(session: _Session, **args: Any) -> dict[str, Any]:
    return odoo_read_group(ToolContext(session=session, manager=None),
                           {"model": "res.partner", **args})


@pytest.mark.parametrize(("series", "method"), [
    ((10, 0), "read_group"), ((17, 0), "read_group"), ((18, 0), "read_group"),
    ((18, 3), "read_group"), ((18, 4), "formatted_read_group"),
    ((19, 0), "formatted_read_group"), ((19, 2), "formatted_read_group"),
    ((20, 0), "formatted_read_group"),  # clamped to (19, 99)
])
def test_the_method_follows_the_series(series: tuple[int, int], method: str) -> None:
    session = _Session(series)
    _run(session, fields=["color:sum"], groupby=["country_id"])
    assert session.calls[-1][1] == method


def test_lazy_two_groupbys_keep_the_classic_shape() -> None:
    session = _Session((19, 0), rows=[
        {"country_id": [128, "Liechtenstein"],
         "__extra_domain": [["country_id", "=", 128]], "color:sum": 0, "__count": 1},
    ])
    out = _run(session, domain=[["is_company", "=", True]], fields=["color:sum"],
               groupby=["country_id", "is_company"], limit=2, orderby="country_id")
    model, method, args, kwargs = session.calls[-1]
    assert (model, method, args) == ("res.partner", "formatted_read_group",
                                     [[["is_company", "=", True]]])
    assert kwargs == {"groupby": ["country_id"], "aggregates": ["__count", "color:sum"],
                      "limit": 2, "order": "country_id",
                      "context": {"read_group_expand": True}}
    assert out["groups"] == [{
        "country_id": [128, "Liechtenstein"],
        "country_id_count": 1,
        "color": 0,
        "__domain": ["&", ["is_company", "=", True], ["country_id", "=", 128]],
        "__context": {"group_by": ["is_company"]},
    }]
    assert "dropped_fields" not in out


def test_eager_grouping_uses_count_and_every_groupby() -> None:
    session = _Session((19, 0), rows=[
        {"country_id": [128, "Liechtenstein"], "is_company": True,
         "__extra_domain": ["&", ["country_id", "=", 128], ["is_company", "=", True]],
         "color:sum": 0, "__count": 1},
    ])
    out = _run(session, domain=[["is_company", "=", True]], fields=["color:sum"],
               groupby=["country_id", "is_company"], lazy=False)
    kwargs = session.calls[-1][3]
    assert kwargs["groupby"] == ["country_id", "is_company"] and "context" not in kwargs
    group = out["groups"][0]
    assert group["__count"] == 1 and "country_id_count" not in group
    assert "__context" not in group
    # the form classic read_group returns on 19.0 for the same call
    assert group["__domain"] == ["&", "&", ["is_company", "=", True], ["country_id", "=", 128],
                                 ["is_company", "=", True]]


def test_bare_fields_use_the_default_aggregator_or_are_reported() -> None:
    session = _Session((19, 0), rows=[{"is_company": True, "__extra_domain": [
        ["is_company", "=", True]], "color:sum": 3, "__count": 10}])
    out = _run(session, fields=["color", "name", "is_company", "__count"], groupby=["is_company"])
    assert session.calls[-1][3]["aggregates"] == ["__count", "color:sum"]
    assert out["groups"][0] == {"is_company": True, "is_company_count": 10, "color": 3,
                                "__domain": [["is_company", "=", True]]}
    assert set(out["dropped_fields"]) == {"name"}  # no aggregator; the groupby field is silent
    assert "name:sum" in out["dropped_fields"]["name"]
    assert session.fields_calls == [("res.partner", ["type", "aggregator"])]


def test_named_aggregates_and_orderby_translation() -> None:
    session = _Session((19, 0), rows=[{"country_id": False, "__extra_domain": [
        ["country_id", "=", False]], "color:max": 5, "__count": 2}])
    out = _run(session, fields=["top:max(color)"], groupby=["country_id"],
               orderby="top desc, country_id_count desc,country_id")
    kwargs = session.calls[-1][3]
    assert kwargs["aggregates"] == ["__count", "color:max"]
    assert kwargs["order"] == "color:max desc,__count desc,country_id"
    assert out["groups"][0]["top"] == 5 and out["groups"][0]["country_id"] is False


def test_date_groups_get_the_label_and_a_rebuilt_range() -> None:
    session = _Session((19, 0), rows=[
        {"create_date:month": ["2026-09-01 00:00:00", "September 2026"],
         "__extra_domain": ["&", ["create_date", ">=", "2026-09-01 00:00:00"],
                            ["create_date", "<", "2026-10-01 00:00:00"]],
         "color:sum": 0, "__count": 38},
        {"create_date:month": False, "__extra_domain": [["create_date", "=", False]],
         "color:sum": 0, "__count": 1},
    ])
    out = _run(session, fields=["color:sum"], groupby=["create_date"], orderby="create_date desc")
    kwargs = session.calls[-1][3]
    assert kwargs["groupby"] == ["create_date:month"]  # classic default granularity
    assert kwargs["order"] == "create_date:month desc"
    first, empty = out["groups"]
    assert first["create_date"] == "September 2026" and first["create_date_count"] == 38
    assert first["__range"] == {"create_date": {"from": "2026-09-01 00:00:00",
                                                "to": "2026-10-01 00:00:00"}}
    assert empty["create_date"] is False and empty["__range"] == {"create_date": False}


def test_explicit_granularity_keeps_the_requested_key() -> None:
    session = _Session((19, 0), rows=[{"create_date:week": ["2026-09-21 00:00:00", "W39 2026"],
                                       "__extra_domain": [], "__count": 4}])
    out = _run(session, fields=[], groupby=["create_date:week"])
    group = out["groups"][0]
    assert group["create_date:week"] == "W39 2026" and group["create_date_count"] == 4
    assert "__range" not in group  # no bounds in __extra_domain: omitted


def test_fold_information_is_passed_through() -> None:
    session = _Session((19, 0), rows=[{"stage_id": [1, "New"], "__fold": False,
                                       "__extra_domain": [["stage_id", "=", 1]], "__count": 0}])
    out = _run(session, fields=[], groupby=["stage_id"])
    assert out["groups"][0]["__fold"] is False and out["groups"][0]["stage_id_count"] == 0


@pytest.mark.parametrize(("fields", "groupby", "match"), [
    (["nope"], ["country_id"], "invalid field"),
    (["color:sum"], ["nope"], "invalid groupby"),
    (["!!"], ["country_id"], "invalid field specification"),
    # trailing text after a valid prefix used to be dropped silently (re.match)
    (["color:sum trailing"], ["country_id"], "invalid field specification"),
    (["total:sum(color)junk"], ["country_id"], "invalid field specification"),
    (["color:sum,name:count"], ["country_id"], "invalid field specification"),
    (["color:sum "], ["country_id"], "invalid field specification"),
    ([" color"], ["country_id"], "invalid field specification"),
    (["top:max(color"], ["country_id"], "invalid field specification"),
    (["color.id"], ["country_id"], "invalid field specification"),
])
def test_bad_fields_are_refused_before_calling_odoo(fields: list[str], groupby: list[str],
                                                    match: str) -> None:
    session = _Session((19, 0))
    with pytest.raises(CompatError, match=match):
        _run(session, fields=fields, groupby=groupby)
    assert session.calls == []


@pytest.mark.parametrize(("spec", "aggregate"), [
    ("color", "color:sum"),  # default aggregator
    ("color:max", "color:max"),
    ("color:count_distinct", "color:count_distinct"),
    ("top:max(color)", "color:max"),
])
def test_valid_field_specifications_still_pass(spec: str, aggregate: str) -> None:
    session = _Session((19, 0))
    _run(session, fields=[spec], groupby=["country_id"])
    assert session.calls[-1][3]["aggregates"] == ["__count", aggregate]


def test_classic_path_is_unchanged_before_saas_18_4() -> None:
    session = _Session((18, 0), rows=[{"stage_id": [1, "New"], "__count": 2}])
    out = _run(session, fields=["stage_id", "color:sum"], groupby=["stage_id"], lazy=False)
    assert session.calls[-1] == ("res.partner", "read_group",
                                 [[], ["stage_id", "color:sum"], ["stage_id"]], {"lazy": False})
    assert out["groups"] == [{"stage_id": [1, "New"], "__count": 2}]
    assert session.fields_calls == []



@pytest.mark.parametrize("series", [(17, 0), (17, 2), (18, 0), (18, 3)])
@pytest.mark.parametrize("spec", ["color:sum trailing", "total:sum(color)junk",
                                  "color:sum,id:count", " color"])
def test_classic_path_refuses_bad_specs_from_17(series: tuple[int, int], spec: str) -> None:
    session = _Session(series)
    with pytest.raises(CompatError, match="invalid field specification"):
        _run(session, fields=[spec], groupby=["stage_id"])
    assert session.calls == []  # refused before any call to Odoo


@pytest.mark.parametrize("series", [(10, 0), (13, 0), (16, 0)])
def test_classic_path_below_17_keeps_odoo_behaviour(series: tuple[int, int]) -> None:
    session = _Session(series)
    _run(session, fields=["color:sum trailing"], groupby=["stage_id"])
    assert session.calls[-1][1] == "read_group"
    assert session.calls[-1][2][1] == ["color:sum trailing"]  # passed through unchanged


@pytest.mark.parametrize("spec", ["color", "color:sum", "tot:sum(color)", "__count",
                                  "color:count_distinct"])
def test_classic_path_valid_specs_pass_from_17(spec: str) -> None:
    session = _Session((17, 0))
    _run(session, fields=[spec], groupby=["stage_id"])
    assert session.calls[-1][2][1] == [spec]

# --- method deltas -------------------------------------------------------------


def _facts(series: tuple[int, int]) -> EnvFacts:
    return EnvFacts(series[0], "community", "onprem", "", series[1]).clamp()


@pytest.mark.parametrize(("method", "series", "available"), [
    ("formatted_read_group", (18, 3), False), ("formatted_read_group", (18, 4), True),
    ("read_group", (19, 0), True), ("read_group", (19, 1), False), ("read_group", (20, 0), False),
    ("check_access_rights", (19, 0), True), ("check_access_rights", (19, 1), False),
    ("has_access", (17, 0), False), ("has_access", (18, 0), True),
    ("search_read", (10, 0), True),  # not in the table: assumed available
])
def test_method_availability(method: str, series: tuple[int, int], available: bool) -> None:
    assert method_available(method, _facts(series)) is available


@pytest.mark.parametrize(("method", "series", "resolved"), [
    ("read_group", (18, 0), "read_group"), ("read_group", (18, 4), "formatted_read_group"),
    ("read_group", (19, 3), "formatted_read_group"),
    ("check_access_rights", (18, 0), "check_access_rights"),
    ("check_access_rights", (19, 1), "has_access"),
    ("search", (19, 0), "search"),
])
def test_method_resolution(method: str, series: tuple[int, int], resolved: str) -> None:
    assert resolve_method(method, _facts(series)) == resolved


@pytest.mark.parametrize(("domain", "extra", "expected"), [
    ([], [], []),
    ([], [["a", "=", 1]], [["a", "=", 1]]),
    ([["a", "=", 1]], [], [["a", "=", 1]]),
    ([["a", "=", 1], ["b", "=", 2]], [["c", "=", 3]],
     ["&", "&", ["a", "=", 1], ["b", "=", 2], ["c", "=", 3]]),
    (["|", ["a", "=", 1], ["b", "=", 2]], [["c", "=", 3]],
     ["&", "|", ["a", "=", 1], ["b", "=", 2], ["c", "=", 3]]),
    (["!", ["a", "=", 1]], ["&", ["b", ">=", 1], ["b", "<", 2]],
     ["&", "&", "!", ["a", "=", 1], ["b", ">=", 1], ["b", "<", 2]]),
    (["|", ["a", "=", 1]], [["c", "=", 3]], ["|", ["a", "=", 1], ["c", "=", 3]]),  # malformed
])
def test_group_domains_are_anded_like_classic_read_group(domain: list, extra: list,
                                                         expected: list) -> None:
    from odoo_mcp.tools.crud import _and_domains

    assert _and_domains(domain, extra) == expected
