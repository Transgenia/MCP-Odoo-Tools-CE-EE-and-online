# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""How the policy reads an Odoo call: method classes, argument shapes, field paths.

Pure functions over the arguments a tool or ``odoo_execute`` sends, with no Odoo
metadata, so a call is read the same way before it is sent (Layer A, the
declared accesses) and while it is sent (Layer B, the guarded session).

``ARG_SHAPES`` names each argument as Odoo binds it. The names are those of
``transport/json2_signatures.SIGNATURES`` (the base definitions), plus the older
keywords some series still take (``args`` for a domain, ``fields_list``,
``orderby``, ``lazy``). A call the table cannot read with certainty (an unknown
keyword, too many positional arguments, a domain that is not a domain) raises
:class:`ShapeError`, which the guard turns into the ``shape`` refusal: the
policy never guesses what an argument means.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .tiers import INSPECT, NOTE_SUBTYPE

# Checked for every transport, as Odoo does: lowercase model names, and public
# methods only (a leading "_" is private and refused over RPC).
MODEL_NAME = re.compile(r"[a-z0-9_.]{1,128}")
METHOD_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}")


def valid_model(name: Any) -> bool:
    return isinstance(name, str) and MODEL_NAME.fullmatch(name) is not None


def valid_method(name: Any) -> bool:
    return isinstance(name, str) and METHOD_NAME.fullmatch(name) is not None


# --- method classes ------------------------------------------------------------
# INSPECT_METHODS | READ_METHODS equals transport.fallback.READ_METHODS (a test
# keeps them equal), so what the policy treats as a read is exactly what the
# transport may replay as one.
#
# Two public BaseModel methods are classed by what they do to records, not by
# their names: copy_data returns the values copy() would give a duplicate (rows
# keyed by field name), so it is a read and its result is redacted as one;
# update(values) assigns the fields of the records, which writes the stored
# ones, so it is a write and its values are checked as write's are.
INSPECT_METHODS = frozenset({"fields_get", "fields_view_get", "get_views", "check_access_rights",
                             "has_access", "has_group", "has_groups", "context_get"})
READ_METHODS = frozenset({"search", "search_read", "search_count", "read", "read_group",
                          "formatted_read_group", "web_read_group", "web_search_read", "web_read",
                          "name_search", "name_get", "default_get", "get_field_translations",
                          "export_data", "copy_data",
                          # Public methods that return record data or filter it but were
                          # classed "call", so their domains and fields escaped the 4.11 /
                          # 6.6 checks and their results escaped redaction (same class of
                          # defect as copy_data/update). search_fetch and fetch (17+) read
                          # like search_read/read; search_panel_* and read_progress_bar are
                          # read oracles over a field's comodel.
                          "search_fetch", "fetch", "read_progress_bar",
                          "search_panel_select_range", "search_panel_select_multi_range",
                          # The open-class readers found by the full inventory: web_name_search
                          # (16+, the web client's name_search: a domain oracle and a dotted
                          # leaf that hops into a sealed comodel, returning field values),
                          # read_grouping_sets / formatted_read_grouping_sets (18+ pivot
                          # read_group, whose domain AND grouping sets are oracles), and
                          # filtered_domain (BaseModel, every series: a domain over the held
                          # records, a weaker oracle that still leaks a withheld field).
                          "web_name_search", "read_grouping_sets", "formatted_read_grouping_sets",
                          "filtered_domain"})
CREATE_METHODS = frozenset({"create", "name_create", "copy"})
WRITE_METHODS = frozenset({"write", "update", "update_field_translations", "action_archive",
                           "action_unarchive", "toggle_active"})
CREATE_WRITE_METHODS = frozenset({"load", "web_save"})
UNLINK_METHODS = frozenset({"unlink"})
# Any other public method is "call" only.

METHOD_CLASSES: tuple[tuple[str, frozenset[str]], ...] = (
    ("inspect", INSPECT_METHODS),
    ("read", READ_METHODS),
    ("create", CREATE_METHODS),
    ("write", WRITE_METHODS),
    ("create_write", CREATE_WRITE_METHODS),
    ("unlink", UNLINK_METHODS),
)
CLASS_OPS: dict[str, tuple[str, ...]] = {
    "inspect": (INSPECT,),
    "read": ("read",),
    "create": ("create",),
    "write": ("write",),
    "create_write": ("create", "write"),
    "unlink": ("unlink",),
    "call": ("call",),
}
# The classes whose arguments are checked: every method in them has a shape.
VALUE_CHECKED = frozenset({"read", "create", "write", "create_write", "unlink"})


def method_class(method: str) -> str:
    for name, methods in METHOD_CLASSES:
        if method in methods:
            return name
    return "call"


def method_ops(method: str) -> tuple[str, ...]:
    """The operations a method needs, besides ``call`` when ``odoo_execute`` sends it."""
    return CLASS_OPS[method_class(method)]


# --- argument shapes -----------------------------------------------------------
# What an argument holds. None: nothing the policy checks (limit, offset, a name).
DOMAIN = "domain"  # a search domain: the field paths of its leaves
HAVING = "having"  # a domain over aggregates ('amount:sum', '__count')
FIELDS = "fields"  # a list of field names
TERMS = "terms"  # groupby and aggregate terms: 'f', 'f:month', 'f:sum', 'name:sum(f)'
GROUPING_SETS = "grouping_sets"  # read_grouping_sets: a list of groupby-term lists
PROGRESS_BAR = "progress_bar"  # read_progress_bar's progress_bar: its 'field' and 'sum_field'
ORDER = "order"  # an order clause: 'name desc, partner_id.name'
SPEC = "specification"  # a web_read specification, nested through "fields"
ONCHANGE_SPEC = "onchange_specification"  # onchange's fields_spec (17+ web_read form, or the
#                                           pre-17 flat field_onchange map)
GROUPBY_SPEC = "groupby_specification"  # {groupby field: specification of its records}
EXPORT = "export"  # export_data paths: 'partner_id/name', 'id'
COLUMNS = "columns"  # load() columns, the same syntax as export paths
VALUES = "values"  # a dict of field values, or a list of them (create)
FIELD = "field"  # one field name (the translation methods)


@dataclass(frozen=True)
class ArgShape:
    """How Odoo binds the arguments of one method."""

    record: bool  # a record method: the legacy positional form passes the ids first
    params: tuple[tuple[str, str | None], ...] = ()  # (name, role) after the ids, in order
    keywords: Mapping[str, str | None] = field(default_factory=dict)  # by name only
    aliases: Mapping[str, str] = field(default_factory=dict)  # older keyword -> a name above
    # The positional arguments read: fewer than params where the positions differ
    # between series (read_group on 20.0, web_read_group from saas~18.4).
    positional: int | None = None
    # Accept keywords the table does not name instead of failing closed: for the web
    # client's search_panel readers, whose trailing options (hierarchize, group_by,
    # group_domain) drift between series and name only comodel-scoped data, while the
    # arguments that matter (the field and the domains over the model) stay listed and
    # checked. A method that writes or whose every keyword is an oracle never sets it.
    open_keywords: bool = False

    def role(self, name: str) -> str | None:
        for param, role in self.params:
            if param == name:
                return role
        return self.keywords.get(name)

    def knows(self, name: str) -> bool:
        return name in self.keywords or any(param == name for param, _role in self.params)


ARG_SHAPES: dict[str, ArgShape] = {
    # reads
    "search": ArgShape(False, (("domain", DOMAIN), ("offset", None), ("limit", None),
                               ("order", ORDER)),
                       keywords={"count": None}, aliases={"args": "domain"}),
    "search_count": ArgShape(False, (("domain", DOMAIN), ("limit", None)),
                             aliases={"args": "domain"}),
    "search_read": ArgShape(False, (("domain", DOMAIN), ("fields", FIELDS), ("offset", None),
                                    ("limit", None), ("order", ORDER)),
                            keywords={"load": None}),
    "read": ArgShape(True, (("fields", FIELDS), ("load", None))),
    # The classic signature; 20.0 reuses the name with (domain, groupby, aggregates,
    # having, ...), so only the first three positions (all field references) are read.
    "read_group": ArgShape(False, (("domain", DOMAIN), ("fields", TERMS), ("groupby", TERMS),
                                   ("offset", None), ("limit", None), ("orderby", ORDER),
                                   ("lazy", None)),
                           keywords={"aggregates": TERMS, "having": HAVING, "order": ORDER},
                           positional=3),
    "formatted_read_group": ArgShape(False, (("domain", DOMAIN), ("groupby", TERMS),
                                             ("aggregates", TERMS), ("having", HAVING),
                                             ("offset", None), ("limit", None),
                                             ("order", ORDER))),
    # Positions after the domain differ: (fields, groupby, ...) up to 18.0,
    # (groupby, aggregates, ...) from saas~18.4.
    "web_read_group": ArgShape(False, (("domain", DOMAIN), ("groupby", TERMS),
                                       ("aggregates", TERMS), ("limit", None), ("offset", None),
                                       ("order", ORDER)),
                               keywords={"fields": TERMS, "orderby": ORDER, "lazy": None,
                                         "expand": None, "expand_limit": None,
                                         "expand_orderby": ORDER, "auto_unfold": None,
                                         "unfold_read_specification": SPEC,
                                         "unfold_read_default_limit": None,
                                         "groupby_read_specification": GROUPBY_SPEC},
                               positional=1),
    "web_search_read": ArgShape(False, (("domain", DOMAIN), ("specification", SPEC),
                                        ("offset", None), ("limit", None), ("order", ORDER),
                                        ("count_limit", None))),
    "web_read": ArgShape(True, (("specification", SPEC),)),
    "name_search": ArgShape(False, (("name", None), ("domain", DOMAIN), ("operator", None),
                                    ("limit", None)),
                            aliases={"args": "domain"}),
    "name_get": ArgShape(True),
    "default_get": ArgShape(False, (("fields", FIELDS),), aliases={"fields_list": "fields"}),
    "get_field_translations": ArgShape(True, (("field_name", FIELD), ("langs", None))),
    "export_data": ArgShape(True, (("fields_to_export", EXPORT), ("raw_data", None))),
    # ``default`` only overrides values of the answer: copy_data writes nothing.
    "copy_data": ArgShape(True, (("default", None),)),
    # 17+: search_read / read with the records fetched into cache. Same field
    # references, so the same domain and field checks apply.
    "search_fetch": ArgShape(False, (("domain", DOMAIN), ("field_names", FIELDS),
                                     ("offset", None), ("limit", None), ("order", ORDER))),
    "fetch": ArgShape(True, (("field_names", FIELDS),)),
    # Read oracles over a field's comodel: the guard also requires ``read`` on the
    # comodel of ``field_name`` (design 4.5/6.6). The domain kwargs are checked;
    # an unlisted kwarg fails closed (rule ``shape``).
    # The domains over the model (category/search/comodel/filter) are checked; the
    # trailing options a series adds (hierarchize, group_by, and group_domain, which is
    # a plain domain in some series and a {group: domain} dict in others, both over the
    # comodel) are accepted and not checked (open_keywords), so mirroring a real kanban
    # search panel through odoo_execute is not refused with rule shape for an unlisted
    # keyword. The field_name comodel read is enforced by the guard (design 4.5).
    "search_panel_select_range": ArgShape(
        False, (("field_name", FIELD),),
        keywords={"category_domain": DOMAIN, "search_domain": DOMAIN, "comodel_domain": DOMAIN,
                  "filter_domain": DOMAIN, "enable_counters": None,
                  "expand": None, "limit": None, "set_count": None}, open_keywords=True),
    "search_panel_select_multi_range": ArgShape(
        False, (("field_name", FIELD),),
        keywords={"category_domain": DOMAIN, "search_domain": DOMAIN, "comodel_domain": DOMAIN,
                  "filter_domain": DOMAIN, "enable_counters": None,
                  "expand": None, "limit": None, "set_count": None}, open_keywords=True),
    # read_progress_bar(domain, group_by, progress_bar): group_by AND the bucket
    # field progress_bar['field'] (plus any sum_field) are grouping dimensions over
    # the matched records, so each is the same oracle read_group's groupby is
    # (design 4.11); the progress-bar dict is parsed by progress_bar_paths.
    "read_progress_bar": ArgShape(False, (("domain", DOMAIN), ("group_by", TERMS),
                                          ("progress_bar", PROGRESS_BAR))),
    # web_name_search(name, specification, domain=None, operator='ilike', limit=100):
    # the web client's name_search, which reads field values through its
    # specification and filters through its domain. As the web module binds them the
    # specification is the SECOND argument and the domain the third (the same order
    # web_search_read uses: the query argument, then the specification). Both are
    # read positionally: the specification is a read spec over the model's fields and
    # the domain a withheld-field oracle whose dotted leaf hops into a sealed
    # comodel. A series whose web_name_search omits the specification can still pass
    # the domain by name; a positional domain is then read as a specification and
    # fails closed (rule ``shape``), never silently skipped.
    "web_name_search": ArgShape(False, (("name", None), ("specification", SPEC),
                                        ("domain", DOMAIN), ("operator", None),
                                        ("limit", None)),
                                aliases={"args": "domain"}),
    # read_grouping_sets / formatted_read_grouping_sets (18+): read_group for pivots.
    # The domain is an oracle, and every term of every grouping set is a groupby
    # oracle over a withheld field (design 4.11), parsed by grouping_sets_paths.
    "read_grouping_sets": ArgShape(False, (("domain", DOMAIN), ("grouping_sets", GROUPING_SETS),
                                           ("aggregates", TERMS), ("having", HAVING)),
                                   keywords={"offset": None, "limit": None, "order": ORDER}),
    "formatted_read_grouping_sets": ArgShape(
        False, (("domain", DOMAIN), ("grouping_sets", GROUPING_SETS), ("aggregates", TERMS),
                ("having", HAVING)),
        keywords={"offset": None, "limit": None, "order": ORDER}),
    # filtered_domain(domain): a record method that returns the subset of the held
    # records matching the domain, in memory. A weaker oracle (it filters only the
    # ids the caller already holds) but it still leaks a withheld field one guess at
    # a time, so its domain is read like any other.
    "filtered_domain": ArgShape(True, (("domain", DOMAIN),)),
    # onchange(values, field_names, fields_spec) on 17+ (the pre-17 names are field_name and
    # field_onchange): a write-nothing simulation, class "call". Only the specification is
    # read, for the contexts nested in it (a list default hidden there is refused) and its
    # read paths; its values are the record's existing lines and are NOT checked as a write
    # (the call-class backstop scans them without expanding, design 4.7). Read by name and
    # positionally; open_keywords lets the pre-17 keyword names pass without a shape refusal,
    # and the flat pre-17 spec collects nothing.
    "onchange": ArgShape(True, (("values", None), ("field_names", None),
                                ("fields_spec", ONCHANGE_SPEC)), open_keywords=True),
    # writes
    "create": ArgShape(False, (("vals_list", VALUES),), aliases={"vals": "vals_list"}),
    "name_create": ArgShape(False, (("name", None),)),
    "copy": ArgShape(True, (("default", VALUES),)),
    "write": ArgShape(True, (("vals", VALUES),), aliases={"values": "vals"}),
    "update": ArgShape(True, (("values", VALUES),)),
    "update_field_translations": ArgShape(True, (("field_name", FIELD), ("translations", None),
                                                 ("source_lang", None))),
    "action_archive": ArgShape(True),
    "action_unarchive": ArgShape(True),
    "toggle_active": ArgShape(True),
    "load": ArgShape(False, (("fields", COLUMNS), ("data", None))),
    "web_save": ArgShape(True, (("vals", VALUES), ("specification", SPEC), ("next_id", None))),
    "unlink": ArgShape(True),
}


class ShapeError(ValueError):
    """The arguments of a call cannot be read with certainty (rule ``shape``).

    ``detail`` names only validated tokens (method and parameter names), never
    an argument value.
    """

    def __init__(self, method: str, detail: str) -> None:
        super().__init__(f"{method}: {detail}")
        self.method = method
        self.detail = detail


@dataclass
class CallArgs:
    """The parts of one call the policy checks, named as Odoo binds them."""

    method: str
    cls: str
    ids: Any = None  # the records of a record method, as given
    named: dict[str, Any] = field(default_factory=dict)  # parameter name -> value
    # Every field path the call filters, reads, groups or sorts on, or names
    # (the translation field), as segments: ("partner_id", "country_id").
    paths: list[tuple[str, ...]] = field(default_factory=list)
    values: list[dict[str, Any]] = field(default_factory=list)  # the values it writes
    # load() columns as (segments, reference): "order_line/product_id/id" is
    # (("order_line", "product_id"), True), a reference to an existing record.
    columns: list[tuple[tuple[str, ...], bool]] = field(default_factory=list)
    # kwargs["context"] and the contexts nested in a specification.
    contexts: list[Any] = field(default_factory=list)


_NO_IDS = object()
_KEYWORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


def _token(name: Any) -> str:
    """An argument name for a message: echoed only when it is a plain identifier."""
    return f"'{name}'" if isinstance(name, str) and _KEYWORD.fullmatch(name) else "of that name"


def extract(method: str, args: Any = None, kwargs: Any = None, *, ids: Any = _NO_IDS) -> CallArgs:
    """Name the arguments of ``model.method(*args, **kwargs)`` by ``ARG_SHAPES``.

    ``ids`` is the separate record-ids argument (``odoo_execute``'s ``ids``, the
    JSON-2 ``ids``); without it the first positional argument of a record method
    is the ids, as in ``execute_kw``. A method outside the table (an inspect or a
    business method) has nothing to check and comes back with no parts.
    """
    if args is None:
        args = []
    if kwargs is None:
        kwargs = {}
    if not isinstance(args, (list, tuple)):
        raise ShapeError(method, "the positional arguments are not a list")
    if not isinstance(kwargs, Mapping):
        raise ShapeError(method, "the keyword arguments are not an object")
    positional, keywords = list(args), dict(kwargs)
    out = CallArgs(method, method_class(method))
    if "context" in keywords:
        out.contexts.append(keywords.pop("context"))
    shape = ARG_SHAPES.get(method)
    if shape is None:
        if out.cls in VALUE_CHECKED:  # every such method has a row (a test checks it)
            raise ShapeError(method, "has no argument table")
        out.ids = None if ids is _NO_IDS else ids
        return out
    if ids is not _NO_IDS:
        if not shape.record:
            raise ShapeError(method, "is a model method and takes no ids")
        out.ids = ids
    elif shape.record and positional:
        out.ids = positional.pop(0)
    limit = len(shape.params) if shape.positional is None else shape.positional
    if len(positional) > limit:
        raise ShapeError(method, f"takes at most {limit} positional argument(s) after the ids; "
                         "pass the others by name")
    for (name, _role), value in zip(shape.params, positional):
        out.named[name] = value
    for key, value in keywords.items():
        name = shape.aliases.get(key, key)
        if not isinstance(name, str) or not shape.knows(name):
            if shape.open_keywords and isinstance(key, str) and _KEYWORD.fullmatch(key):
                continue  # a trailing option the reader takes but the policy need not check
            raise ShapeError(method, f"takes no keyword {_token(key)}")
        if name in out.named:
            raise ShapeError(method, f"argument '{name}' is given twice")
        out.named[name] = value
    for name, value in out.named.items():
        _collect(out, shape.role(name), value)
    return out


def named_parts(label: str, arguments: Mapping[str, Any],
                roles: Mapping[str, str | None]) -> CallArgs:
    """The parts of a dedicated tool's arguments, read by the same parsers as an
    RPC: ``roles`` maps the tool's argument names to what they hold (a domain, a
    field list, values...). ``label`` names the tool in a ShapeError."""
    out = CallArgs(label, "tool")
    for name, value in arguments.items():
        role = roles.get(name)
        if role is not None:
            out.named[name] = value
            _collect(out, role, value)
    return out


def _collect(out: CallArgs, role: str | None, value: Any) -> None:
    method = out.method
    if role is None:
        return
    if role == DOMAIN:
        out.paths.extend(domain_paths(value, method=method))
    elif role == HAVING:
        out.paths.extend(domain_paths(value, method=method, aggregates=True))
    elif role == FIELDS:
        out.paths.extend(field_paths(value, method=method))
    elif role == TERMS:
        out.paths.extend(term_paths(value, method=method))
    elif role == GROUPING_SETS:
        out.paths.extend(grouping_sets_paths(value, method=method))
    elif role == PROGRESS_BAR:
        out.paths.extend(progress_bar_paths(value, method=method))
    elif role == ORDER:
        out.paths.extend(order_paths(value, method=method))
    elif role == SPEC:
        out.paths.extend(specification_paths(value, method=method, contexts=out.contexts))
    elif role == ONCHANGE_SPEC:
        out.paths.extend(onchange_spec_paths(value, method=method, contexts=out.contexts))
    elif role == GROUPBY_SPEC:
        out.paths.extend(groupby_specification_paths(value, method=method,
                                                     contexts=out.contexts))
    elif role == EXPORT:
        out.paths.extend(names for names, _reference in column_paths(value, method=method))
    elif role == COLUMNS:
        out.columns.extend(column_paths(value, method=method))
    elif role == FIELD:
        if not isinstance(value, str):
            raise ShapeError(method, "the field name is not text")
        out.paths.extend(field_paths([value], method=method))
    elif role == VALUES:
        out.values.extend(value_dicts(value, method=method))
    else:  # pragma: no cover - a role without a parser is a bug in the table
        raise ShapeError(method, f"no parser for '{role}'")


# --- path parsers ----------------------------------------------------------------
MAX_DEPTH = 4  # nested any/not any sub-domains and specifications
_SEGMENT = re.compile(r"[A-Za-z0-9_]+")
_PATH = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*")
_AGGREGATE_PATH = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*(?::[A-Za-z0-9_]+)?")
# 'f', 'f:agg' or 'name:agg(f)', dotted paths allowed. Matched at the start only,
# as Odoo's own read_group parser does: Odoo reads that prefix and ignores the rest.
_TERM = re.compile(r"([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)"
                   r"(?::([A-Za-z0-9_]+)(?:\(([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)\))?)?")
_ORDER_REF = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*(?::[A-Za-z0-9_]+)?")
_ORDER_WORDS = frozenset({"asc", "desc", "nulls", "first", "last"})
_DOMAIN_OPERATORS = frozenset({"&", "|", "!"})
_SUBDOMAIN_OPERATORS = frozenset({"any", "not any", "any!", "not any!"})
_SPEC_KEYS = frozenset({"fields", "context", "limit", "order"})


def _split(path: str) -> tuple[str, ...]:
    return tuple(path.split("."))


def domain_paths(domain: Any, *, method: str = "domain", prefix: tuple[str, ...] = (),
                 depth: int = 0, aggregates: bool = False) -> list[tuple[str, ...]]:
    """Every field path a domain filters on; ``any`` / ``not any`` sub-domains
    are read on the comodel, so their paths continue the leaf's path.

    ``aggregates``: a ``having`` domain, whose leaves name aggregates
    (``amount:sum``, ``__count``).
    """
    if domain is None or domain is False:
        return []
    if not isinstance(domain, (list, tuple)):
        raise ShapeError(method, "a domain is not a list")
    if depth > MAX_DEPTH:
        raise ShapeError(method, "a domain nests any/not any too deeply")
    paths: list[tuple[str, ...]] = []
    for term in domain:
        if isinstance(term, str):
            if term in _DOMAIN_OPERATORS:
                continue
            raise ShapeError(method, "a domain holds an unknown operator")
        if not isinstance(term, (list, tuple)) or len(term) != 3:
            raise ShapeError(method, "a domain term is not [field, operator, value]")
        left, operator, right = term
        if isinstance(left, int) and not isinstance(left, bool) and left in (0, 1):
            continue  # Odoo's TRUE_LEAF (1, '=', 1) and FALSE_LEAF (0, '=', 1)
        pattern = _AGGREGATE_PATH if aggregates else _PATH
        if not isinstance(left, str) or not pattern.fullmatch(left):
            raise ShapeError(method, "a domain term does not start with a field path")
        if not isinstance(operator, str):
            raise ShapeError(method, "a domain operator is not text")
        path = prefix + _split(left.split(":")[0])
        paths.append(path)
        if operator.strip().lower() in _SUBDOMAIN_OPERATORS:
            if aggregates:
                raise ShapeError(method, "a having domain cannot hold any/not any")
            paths.extend(domain_paths(right, method=method, prefix=path, depth=depth + 1))
    return paths


def domain_conjuncts(domain: Any) -> list[list[Any]] | None:
    """The terms the top level of a prefix-notation domain ANDs together, nested
    ``'&'`` opened: ``['&', A, '|', B, C]`` gives ``[[A], ['|', B, C]]``. ``None``
    when the domain is not a well-formed list of terms."""
    if not isinstance(domain, (list, tuple)):
        return None
    tokens = list(domain)
    terms: list[list[Any]] = []
    i = 0
    while i < len(tokens):
        start, need = i, 1
        while need and i < len(tokens):
            token = tokens[i]
            i += 1
            if isinstance(token, str) and token in ("&", "|"):
                need += 1
            elif not (isinstance(token, str) and token == "!"):
                need -= 1
        if need:
            return None
        term = tokens[start:i]
        if isinstance(term[0], str) and term[0] == "&":
            inner = domain_conjuncts(term[1:])
            if inner is None:
                return None
            terms.extend(inner)
        else:
            terms.append(term)
    return terms


def field_paths(fields: Any, *, method: str = "fields") -> list[tuple[str, ...]]:
    if fields is None or fields is False:
        return []
    if not isinstance(fields, (list, tuple)):
        raise ShapeError(method, "a field list is not a list")
    paths = []
    for name in fields:
        if not isinstance(name, str) or not _PATH.fullmatch(name):
            raise ShapeError(method, "a field list holds something that is not a field name")
        paths.append(_split(name))
    return paths


def term_paths(terms: Any, *, method: str = "terms") -> list[tuple[str, ...]]:
    """groupby and aggregate terms: the field each one reads (``__count`` reads none)."""
    if terms is None or terms is False:
        return []
    if isinstance(terms, str):
        terms = [terms]  # read_group takes one groupby as a string
    if not isinstance(terms, (list, tuple)):
        raise ShapeError(method, "a groupby or aggregate list is not a list")
    paths = []
    for term in terms:
        match = _TERM.match(term) if isinstance(term, str) else None
        if match is None:
            raise ShapeError(method, "a groupby or aggregate term is not 'field[:function]'")
        name, _function, source = match.groups()
        if source:
            paths.append(_split(source))
        elif name != "__count":
            paths.append(_split(name))
    return paths


def grouping_sets_paths(sets: Any, *, method: str = "grouping_sets") -> list[tuple[str, ...]]:
    """``read_grouping_sets``' ``grouping_sets``: a list of groupby-term lists. Every
    term of every set reads a field, so the oracle is refused whatever set it hides in.
    A term that is not ``'field[:function]'`` fails closed (rule ``shape``)."""
    if sets is None or sets is False:
        return []
    if not isinstance(sets, (list, tuple)):
        raise ShapeError(method, "the grouping sets are not a list")
    paths: list[tuple[str, ...]] = []
    for one in sets:
        paths.extend(term_paths(one, method=method))
    return paths


def progress_bar_paths(bar: Any, *, method: str = "progress_bar") -> list[tuple[str, ...]]:
    """``read_progress_bar``'s ``progress_bar``: its records are bucketed by the distinct
    values of ``bar['field']`` (a second grouping dimension) and summed over
    ``bar['sum_field']`` when given, so both read a field and are checked as a groupby
    is. A ``field`` that is not a field name fails closed (rule ``shape``)."""
    if bar is None or bar is False:
        return []
    if not isinstance(bar, Mapping):
        raise ShapeError(method, "a progress bar is not an object")
    paths: list[tuple[str, ...]] = []
    for key in ("field", "sum_field"):
        value = bar.get(key)
        if value is None or value is False:
            continue  # sum_field is optional and the web client sends it as false
        if not isinstance(value, str) or not _PATH.fullmatch(value):
            raise ShapeError(method, "a progress bar field is not a field name")
        paths.append(_split(value))
    return paths


def order_paths(order: Any, *, method: str = "order") -> list[tuple[str, ...]]:
    """``'name desc, partner_id.name asc nulls last'`` -> the field path of each term."""
    if order is None or order is False or order == "":
        return []
    if not isinstance(order, str):
        raise ShapeError(method, "an order is not text")
    paths = []
    for term in order.split(","):
        words = term.split()
        if not words:
            raise ShapeError(method, "an order has an empty term")
        ref = words[0]
        if len(ref) > 2 and ref.startswith('"') and ref.endswith('"'):
            ref = ref[1:-1]
        if not _ORDER_REF.fullmatch(ref) or any(w.lower() not in _ORDER_WORDS for w in words[1:]):
            raise ShapeError(method, "an order term is not 'field [asc|desc] [nulls first|last]'")
        paths.append(_split(ref.split(":")[0]))
    return paths


def specification_paths(spec: Any, *, method: str = "specification",
                        prefix: tuple[str, ...] = (), depth: int = 0,
                        contexts: list[Any] | None = None) -> list[tuple[str, ...]]:
    """A web_read specification ``{field: {"fields": {...}, "order": ..., "context": ...}}``,
    walked at every depth; the nested contexts are appended to ``contexts``."""
    if spec is None:
        return []
    if not isinstance(spec, Mapping):
        raise ShapeError(method, "a specification is not an object")
    if depth > MAX_DEPTH:
        raise ShapeError(method, "a specification nests too deeply")
    paths: list[tuple[str, ...]] = []
    for name, sub in spec.items():
        if not isinstance(name, str) or not _SEGMENT.fullmatch(name):
            raise ShapeError(method, "a specification key is not a field name")
        path = prefix + (name,)
        paths.append(path)
        if sub is None:
            continue
        if not isinstance(sub, Mapping) or set(sub) - _SPEC_KEYS:
            raise ShapeError(method, "a specification entry holds keys other than fields, "
                             "context, limit and order")
        if "fields" in sub:
            paths.extend(specification_paths(sub["fields"], method=method, prefix=path,
                                             depth=depth + 1, contexts=contexts))
        if "order" in sub:
            paths.extend(path + term for term in order_paths(sub["order"], method=method))
        if "context" in sub and contexts is not None:
            contexts.append(sub["context"])
    return paths


def onchange_spec_paths(spec: Any, *, method: str = "onchange",
                        contexts: list[Any] | None = None) -> list[tuple[str, ...]]:
    """``onchange``'s fourth argument. Odoo 17+ passes ``fields_spec``, a web_read
    specification ``{field: {"fields": {...}, "context": {...}}}`` whose nested contexts
    must be collected like any other (a list default hidden in one is refused). Odoo 10-16
    passes ``field_onchange``, a flat ``{dotted field path: marker}`` map with no nested
    context, which is not a specification.

    A context can sit only inside an entry object, so any spec that carries one has a
    Mapping (or ``None``) value and is walked as a 17+ specification; a spec whose values are
    all plain markers is the pre-17 flat form and carries nothing to collect. ``onchange``
    writes nothing and stays class ``call``, and the flat form never fails closed here."""
    if not isinstance(spec, Mapping):
        return []
    if any(sub is None or isinstance(sub, Mapping) for sub in spec.values()):
        return specification_paths(spec, method=method, contexts=contexts)
    return []


def groupby_specification_paths(spec: Any, *, method: str = "groupby_specification",
                                contexts: list[Any] | None = None) -> list[tuple[str, ...]]:
    """``{groupby field: specification of the grouped records}``."""
    if spec is None:
        return []
    if not isinstance(spec, Mapping):
        raise ShapeError(method, "a groupby specification is not an object")
    paths: list[tuple[str, ...]] = []
    for name, sub in spec.items():
        heads = term_paths([name], method=method)
        if len(heads) != 1:
            raise ShapeError(method, "a groupby specification key is not a field")
        paths.extend(heads)
        paths.extend(specification_paths(sub, method=method, prefix=heads[0], depth=1,
                                         contexts=contexts))
    return paths


def column_paths(columns: Any, *, method: str = "columns") -> list[tuple[tuple[str, ...], bool]]:
    """export_data and load() column paths: ``'order_line/product_id/id'`` is
    ``(("order_line", "product_id"), True)``; a trailing ``id`` or ``.id`` is a
    reference to an existing record, not a field."""
    if columns is None:
        return []
    if not isinstance(columns, (list, tuple)):
        raise ShapeError(method, "the column paths are not a list")
    out = []
    for column in columns:
        if not isinstance(column, str) or not column:
            raise ShapeError(method, "a column path is not text")
        segments = column.split("/")
        reference = segments[-1] in ("id", ".id")
        names = tuple(segments[:-1] if reference else segments)
        if not all(_SEGMENT.fullmatch(name) for name in names):
            raise ShapeError(method, "a column path segment is not a field name")
        out.append((names, reference))
    return out


def value_dicts(value: Any, *, method: str = "values") -> list[dict[str, Any]]:
    """The values a write sends: a dict, a list of dicts (create), or nothing (copy)."""
    if value is None or value is False:
        return []
    items = [value] if isinstance(value, Mapping) else value
    if not isinstance(items, (list, tuple)) or not all(isinstance(v, Mapping) for v in items):
        raise ShapeError(method, "the values are not an object or a list of objects")
    out = []
    for item in items:
        if not all(isinstance(key, str) and _SEGMENT.fullmatch(key) for key in item):
            raise ShapeError(method, "a values key is not a field name")
        out.append(dict(item))
    return out


# --- the internal-note allowance (4.7) -------------------------------------------

def _ids_only(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, (list, tuple)) and all(
        isinstance(i, int) and not isinstance(i, bool) for i in value)


def is_internal_note(method: str, args: Any = None, kwargs: Any = None, *,
                     ids_given: bool = False) -> bool:
    """``message_post`` as a plain internal note, which notifies nobody by e-mail.

    All of these must hold: ``subtype_xmlid`` (13+) or ``subtype`` (10-12) is
    ``mail.mt_note`` and no ``subtype_id`` is given; there are no
    ``partner_ids``; ``message_type`` is absent or ``comment``; and no
    positional argument is given besides the record ids, which come first in
    the legacy positional form.
    """
    if method != "message_post":
        return False
    if args is None:
        args = []
    if kwargs is None:
        kwargs = {}
    if not isinstance(args, (list, tuple)) or not isinstance(kwargs, Mapping):
        return False
    positional = list(args)
    if not ids_given and positional and _ids_only(positional[0]):
        positional.pop(0)
    if positional:
        return False
    subtypes = [kwargs[key] for key in ("subtype_xmlid", "subtype") if key in kwargs]
    if not subtypes or any(subtype != NOTE_SUBTYPE for subtype in subtypes):
        return False
    if "subtype_id" in kwargs or kwargs.get("partner_ids"):
        return False
    return kwargs.get("message_type", "comment") == "comment"
