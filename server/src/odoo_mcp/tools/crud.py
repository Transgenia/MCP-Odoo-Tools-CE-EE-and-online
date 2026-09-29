# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Generic CRUD tools, all routed through the compat layer.

Model names are resolved for the target version; requested field names are
remapped and unavailable fields dropped with a warning in the response so a
caller written for one version keeps working on another.
"""

from __future__ import annotations

import itertools
import re
from typing import Any

from ..compat import requires_edition, resolve_fields, resolve_method, resolve_model
from ..errors import CompatError
from ..registry import ToolContext, obj, registry

_DOMAIN = {
    "type": "array",
    "description": "Odoo search domain, e.g. [[\"state\",\"=\",\"posted\"]]",
}
_FIELDS = {"type": "array", "items": {"type": "string"}}


def _facts(ctx: ToolContext) -> Any:
    return ctx.session.facts()


def _remap_fields(ctx: ToolContext, model: str, fields: list[str] | None) -> tuple[list[str] | None, dict]:
    if not fields:
        return None, {}
    res = resolve_fields(model, fields, _facts(ctx))
    warn = {"dropped_fields": res.dropped} if res.dropped else {}
    return res.usable, warn


@registry.tool(
    "odoo_search",
    "Search a model and return matching record ids.",
    obj(
        {
            "model": {"type": "string"},
            "domain": _DOMAIN,
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
            "order": {"type": "string"},
        },
        required=["model"],
    ),
)
def odoo_search(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    requires_edition(model, _facts(ctx))
    kwargs = {k: args[k] for k in ("limit", "offset", "order") if k in args}
    ids = ctx.session.execute(model, "search", [args.get("domain", [])], kwargs)
    return {"model": model, "ids": ids}


@registry.tool(
    "odoo_search_count",
    "Count records matching a domain.",
    obj({"model": {"type": "string"}, "domain": _DOMAIN}, required=["model"]),
)
def odoo_search_count(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    requires_edition(model, _facts(ctx))
    count = ctx.session.execute(model, "search_count", [args.get("domain", [])])
    return {"model": model, "count": count}


@registry.tool(
    "odoo_read",
    "Read records by id, optionally limiting fields.",
    obj(
        {
            "model": {"type": "string"},
            "ids": {"type": "array", "items": {"type": "integer"}},
            "fields": _FIELDS,
        },
        required=["model", "ids"],
    ),
)
def odoo_read(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    requires_edition(model, _facts(ctx))
    fields, warn = _remap_fields(ctx, model, args.get("fields"))
    kwargs = {"fields": fields} if fields else {}
    rows = ctx.session.execute(model, "read", [args["ids"]], kwargs)
    return {"model": model, "records": rows, **warn}


@registry.tool(
    "odoo_search_read",
    "Search and read in one call (the workhorse query tool).",
    obj(
        {
            "model": {"type": "string"},
            "domain": _DOMAIN,
            "fields": _FIELDS,
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
            "order": {"type": "string"},
        },
        required=["model"],
    ),
)
def odoo_search_read(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    requires_edition(model, _facts(ctx))
    fields, warn = _remap_fields(ctx, model, args.get("fields"))
    kwargs: dict[str, Any] = {k: args[k] for k in ("limit", "offset", "order") if k in args}
    if fields:
        kwargs["fields"] = fields
    rows = ctx.session.execute(model, "search_read", [args.get("domain", [])], kwargs)
    return {"model": model, "records": rows, **warn}


@registry.tool(
    "odoo_create",
    "Create one record. Returns the new id. (write operation)",
    obj({"model": {"type": "string"}, "values": {"type": "object"}}, required=["model", "values"]),
    read_only=False,
)
def odoo_create(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    requires_edition(model, _facts(ctx))
    new_id = ctx.session.execute(model, "create", [args["values"]])
    return {"model": model, "id": new_id}


@registry.tool(
    "odoo_write",
    "Update records by id. (write operation)",
    obj(
        {
            "model": {"type": "string"},
            "ids": {"type": "array", "items": {"type": "integer"}},
            "values": {"type": "object"},
        },
        required=["model", "ids", "values"],
    ),
    read_only=False,
)
def odoo_write(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    requires_edition(model, _facts(ctx))
    ok = ctx.session.execute(model, "write", [args["ids"], args["values"]])
    return {"model": model, "ok": bool(ok)}


@registry.tool(
    "odoo_unlink",
    "Delete records by id. (write operation)",
    obj(
        {"model": {"type": "string"}, "ids": {"type": "array", "items": {"type": "integer"}}},
        required=["model", "ids"],
    ),
    read_only=False,
)
def odoo_unlink(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    requires_edition(model, _facts(ctx))
    ok = ctx.session.execute(model, "unlink", [args["ids"]])
    return {"model": model, "ok": bool(ok)}


@registry.tool(
    "odoo_execute",
    "Call any public model method (escape hatch); it may change data, so it is "
    "refused in read-only mode (ODOO_READONLY). Pass the records of a record method "
    "(write, unlink, copy, action_*) in 'ids' and the other arguments by name in "
    "'kwargs': that form works on every transport, including JSON-2 (Odoo 19+), which "
    "takes named arguments only. Positional 'args' (execute_kw style, the first element "
    "being the ids of a record method) are named on JSON-2 from the plugin's table of the "
    "methods it knows; when a model's override uses other names, Odoo refuses them before "
    "running anything and the plugin corrects them, or in auto sends that call over "
    "JSON-RPC/XML-RPC. (write operation)",
    obj(
        {
            "model": {"type": "string"},
            "method": {"type": "string"},
            "ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "record ids for a record method; omit for model methods "
                "such as search or create",
            },
            "args": {"type": "array", "description": "positional arguments (execute_kw style)"},
            "kwargs": {
                "type": "object",
                "description": "named arguments, e.g. {\"fields\": [\"name\"]}",
            },
        },
        required=["model", "method"],
    ),
    read_only=False,
)
def odoo_execute(ctx: ToolContext, args: dict[str, Any]) -> Any:
    model = resolve_model(args["model"], _facts(ctx))
    method_args, method_kwargs = args.get("args", []), args.get("kwargs", {})
    if "ids" in args:
        result = ctx.session.execute(model, args["method"], method_args, method_kwargs,
                                     ids=args["ids"])
    else:
        result = ctx.session.execute(model, args["method"], method_args, method_kwargs)
    return {"model": model, "method": args["method"], "result": result}


@registry.tool(
    "odoo_read_group",
    "Server-side GROUP BY aggregation (pushes grouping to the database instead "
    "of pulling rows). Classic read_group arguments and output on Odoo 10-19; from "
    "saas~18.4 it runs on formatted_read_group (classic read_group is deprecated in "
    "19.0 and gone from saas~19.1), and a field without a default aggregator is "
    "listed in dropped_fields.",
    obj(
        {
            "model": {"type": "string"},
            "domain": _DOMAIN,
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "groupby fields plus aggregates, e.g. [\"stage_id\", \"expected_revenue:sum\"]",
            },
            "groupby": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
            "orderby": {"type": "string"},
            "lazy": {"type": "boolean", "default": True},
        },
        required=["model", "fields", "groupby"],
    ),
)
def odoo_read_group(ctx: ToolContext, args: dict[str, Any]) -> Any:
    facts = _facts(ctx)
    model = resolve_model(args["model"], facts)
    requires_edition(model, facts)
    if resolve_method("read_group", facts) == "formatted_read_group":
        # saas~18.4+: the classic method is deprecated (19.0), then gone (saas~19.1).
        return formatted_group(ctx, model, args)
    if facts.series >= (17, 0):
        # Odoo accepts "amount:sum junk" on the classic path and drops the tail without a
        # word. From 17.0 (the series Odoo still supports) the tool refuses it, as on
        # formatted_read_group; 10-16 keep Odoo's own behaviour.
        for spec in args["fields"]:
            _check_field_spec(spec)
    kwargs: dict[str, Any] = {
        k: args[k] for k in ("limit", "offset", "orderby", "lazy") if k in args
    }
    rows = ctx.session.execute(
        model, "read_group", [args.get("domain", []), args["fields"], args["groupby"]], kwargs
    )
    return {"model": model, "groups": rows}


# --- read_group on formatted_read_group (saas~18.4+) -------------------------
# The tool keeps the classic read_group contract (arguments and output shape),
# so callers written for Odoo 10-18 keep working. Classic rules reproduced:
# a date(time) groupby without granularity means ':month'; 'field' aggregates
# with the field's default aggregator, 'field:agg' and 'name:agg(field)' are
# explicit; lazy groups by the first groupby only and names the count
# '<groupby>_count'; values are keyed by the requested names.

_FIELD_AGG = re.compile(r"(\w+)(?::(\w+)(?:\((\w+)\))?)?")


def _check_field_spec(spec: str) -> re.Match[str]:
    """The whole spec must match: a prefix match would drop a typo or a second aggregate
    ("amount:sum,tax:sum") without a word and return something other than asked."""
    match = _FIELD_AGG.fullmatch(spec) if isinstance(spec, str) else None
    if not match:
        raise CompatError(f"invalid field specification {spec!r}",
                          remediation="use 'field', 'field:agg' or 'name:agg(field)', one "
                          "per list item, with nothing before or after")
    return match
_TIME_GRANULARITIES = frozenset({"hour", "day", "week", "month", "quarter", "year"})
_DATE_TYPES = frozenset({"date", "datetime"})


def _range_from(extra: Any, field: str) -> dict[str, Any] | None:
    lower = upper = None
    for term in extra if isinstance(extra, list) else ():
        if isinstance(term, (list, tuple)) and len(term) == 3 and term[0] == field:
            if term[1] == ">=":
                lower = term[2]
            elif term[1] == "<":
                upper = term[2]
    if lower is None or upper is None:
        return None
    return {"from": lower, "to": upper}


def _conjuncts(domain: list[Any]) -> list[list[Any]] | None:
    """Split a prefix-notation domain into the terms its implicit AND joins,
    opening nested '&' terms; ``None`` when it is not well formed."""
    terms: list[list[Any]] = []
    i = 0
    while i < len(domain):
        start, need = i, 1
        while need and i < len(domain):
            token = domain[i]
            i += 1
            if token in ("&", "|"):
                need += 1
            elif token != "!":
                need -= 1
        if need:
            return None
        term = domain[start:i]
        if term[0] == "&":
            inner = _conjuncts(term[1:])
            if inner is None:
                return None
            terms.extend(inner)
        else:
            terms.append(term)
    return terms


def _and_domains(domain: list[Any], extra: list[Any]) -> list[Any]:
    """``domain AND extra`` in the normalised form classic read_group returns
    (``['&', A, B]``); a plain concatenation (also their AND) if unparsable."""
    left, right = _conjuncts(domain), _conjuncts(extra)
    if left is None or right is None:
        return domain + extra
    terms = left + right
    return ["&"] * (len(terms) - 1) + [token for term in terms for token in term]


def formatted_group(ctx: ToolContext, model: str, args: dict[str, Any]) -> dict[str, Any]:
    domain = list(args.get("domain") or [])
    groupby = args["groupby"]
    groupby = [groupby] if isinstance(groupby, str) else list(groupby)
    lazy = args.get("lazy", True)
    lazy_groupby = groupby[:1] if lazy else groupby
    info = ctx.session.fields_get(model, ["type", "aggregator"])

    def ftype(name: str) -> str:
        return str((info.get(name) or {}).get("type") or "")

    annotated_groupby: dict[str, str] = {}  # requested spec -> spec sent to Odoo
    for spec in lazy_groupby:
        name = spec.split(":")[0].split(".")[0]
        if name not in info:
            raise CompatError(
                f"invalid groupby {spec!r}: '{name}' is not a field of {model}",
                remediation="check the field names with odoo_fields_get",
            )
        if ftype(name) in _DATE_TYPES:
            granularity = spec.split(":")[1] if ":" in spec else "month"
            annotated_groupby[spec] = f"{name}:{granularity}"
        else:
            annotated_groupby[spec] = spec

    count_key = (f"{lazy_groupby[0].split(':')[0]}_count"
                 if lazy and len(lazy_groupby) == 1 else "__count")
    annotated_aggregates: dict[str, str] = {count_key: "__count"}
    dropped: dict[str, str] = {}
    grouped = {spec.split(":")[0].split(".")[0] for spec in groupby}
    for spec in args["fields"]:
        if spec == "__count":
            continue
        # The whole spec must match: a prefix match would drop a typo or a second aggregate
        # ("amount:sum,tax:sum") without a word and return something other than asked.
        name, func, source = _check_field_spec(spec).groups()
        if source:
            annotated_aggregates[name] = f"{source}:{func}"
        elif func:
            annotated_aggregates[name] = f"{name}:{func}"
        elif name not in info:
            raise CompatError(
                f"invalid field {name!r} on {model}",
                remediation="check the field names with odoo_fields_get",
            )
        elif spec in annotated_groupby:
            continue  # a groupby field: classic read_group ignores it
        elif (info[name] or {}).get("aggregator"):
            annotated_aggregates[name] = f"{name}:{info[name]['aggregator']}"
        elif name in grouped:
            continue  # a later (lazy) groupby field with no aggregator: ignored too
        else:
            dropped[name] = (f"'{name}' has no default aggregator on this Odoo version; "
                             f"ask for one explicitly, e.g. '{name}:sum' or '{name}:max'")

    order = args.get("orderby") or None
    if order:
        terms = []
        for term in str(order).split(","):
            term = term.strip()
            for key, annotated in itertools.chain(
                    reversed(list(annotated_groupby.items())), annotated_aggregates.items()):
                key = key.split(":")[0]
                if term.startswith(f"{key} ") or term == key:
                    term = term.replace(key, annotated)
                    break
            terms.append(term)
        order = ",".join(terms)

    kwargs: dict[str, Any] = {
        "groupby": list(annotated_groupby.values()),
        "aggregates": list(dict.fromkeys(annotated_aggregates.values())),
    }
    for key in ("limit", "offset"):
        if key in args:
            kwargs[key] = args[key]
    if order:
        kwargs["order"] = order
    if lazy and lazy_groupby:
        # Classic lazy read_group lists the empty groups of group_expand fields
        # (e.g. kanban stages); formatted_read_group does so on request.
        kwargs["context"] = {"read_group_expand": True}
    rows = ctx.session.execute(model, "formatted_read_group", [domain], kwargs)

    groups = []
    for row in rows or []:
        group: dict[str, Any] = {}
        ranges: dict[str, Any] = {}
        extra = row.get("__extra_domain") or []
        for spec, sent in annotated_groupby.items():
            value = row.get(sent)
            name, _, granularity = sent.partition(":")
            if ftype(name.split(".")[0]) in _DATE_TYPES and granularity in _TIME_GRANULARITIES:
                if isinstance(value, (list, tuple)) and len(value) == 2:
                    bounds = _range_from(extra, name)
                    value = value[1]  # [start, label] -> label, as classic
                    if bounds is not None:
                        ranges[spec] = bounds
                elif not value:
                    ranges[spec] = False
            group[spec] = value
        for key, sent in annotated_aggregates.items():
            group[key] = row.get(sent)
        if "__fold" in row:
            group["__fold"] = row["__fold"]
        group["__domain"] = _and_domains(domain, list(extra))
        if len(lazy_groupby) < len(groupby):
            group["__context"] = {"group_by": groupby[len(lazy_groupby):]}
        if ranges:
            group["__range"] = ranges
        groups.append(group)
    result: dict[str, Any] = {"model": model, "groups": groups}
    if dropped:
        result["dropped_fields"] = dropped
    return result
