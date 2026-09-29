# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Positional-to-named argument table for Odoo's JSON-2 API.

``POST /json/2/<model>/<method>`` takes a JSON object of **named** arguments
only, plus ``ids`` (the records a record method runs on) and ``context``. The
plugin's call sites, and ``odoo_execute`` callers, pass ``execute_kw``-style
positional ``args``; this table gives each method's parameter names so the
JSON-2 transport can name them. It is DATA: the names were read from the public
Odoo source of every series that has JSON-2 (saas~18.4, 19.0, saas~19.1 to
saas~19.4, 20.0/master: ``odoo/orm/models.py``, ``addons/web/models/models.py``,
``res_users.py``, ``base_import.py``) and are recorded as facts, not code.

They are the names of the **base** definitions. JSON-2 binds the body to the
model's own top override, and an override may rename a parameter: on saas~18.4
``write(self, values)`` on ``res.company``, ``product.pricelist`` and every
``mail.thread`` model, and ``res.partner.default_get(self, default_fields)``;
an installed addon may do the same on any series. The transport then gets an
HTTP 422 from the bind check (the method did not run) and corrects the names
(see ``Json2Transport.execute_kw``); ``auto`` falls back to a legacy transport
for that call when it cannot.

Conventions:
  * ``model_level`` marks an ``@api.model`` method: it takes no ``ids``, and
    JSON-2 refuses the call when ids are sent (HTTP 422).
  * For any other method the first positional argument is the ids.
  * ``params`` are the parameter names after ``self`` (and after the ids), in
    order.
  * Series use the ``(major, minor)`` points of ``compat``: saas~18.4 is
    ``(18, 4)``, 19.0 is ``(19, 0)``. A variant applies from ``since``
    (inclusive) up to ``until`` (exclusive); a ``None`` signature means the
    method does not exist in that range.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

from ..errors import CompatError

Series = tuple[int, int]

# The oldest series with JSON-2, and the series assumed when none is known.
JSON2_FIRST_SERIES: Series = (18, 4)
DEFAULT_SERIES: Series = (19, 0)


@dataclass(frozen=True)
class Signature:
    model_level: bool
    params: tuple[str, ...]
    readonly: bool = False  # @api.readonly (informational)


@dataclass(frozen=True)
class Variant:
    since: Series
    until: Series | None
    signature: Signature | None
    note: str = ""


M, R = True, False  # @api.model vs record method

# Methods defined on every model (BaseModel and the web module's additions).
SIGNATURES: dict[str, Signature] = {
    "search": Signature(M, ("domain", "offset", "limit", "order"), readonly=True),
    "search_read": Signature(M, ("domain", "fields", "offset", "limit", "order"), readonly=True),
    "search_count": Signature(M, ("domain", "limit"), readonly=True),
    "read": Signature(R, ("fields", "load"), readonly=True),
    "fields_get": Signature(M, ("allfields", "attributes")),
    "create": Signature(M, ("vals_list",)),
    "write": Signature(R, ("vals",)),
    "unlink": Signature(R, ()),
    "copy": Signature(R, ("default",)),
    "name_search": Signature(M, ("name", "domain", "operator", "limit"), readonly=True),
    "name_create": Signature(M, ("name",)),
    "formatted_read_group": Signature(
        M, ("domain", "groupby", "aggregates", "having", "offset", "limit", "order"),
        readonly=True,
    ),
    # Its keyword-only options (auto_unfold, opening_info, ...) go in kwargs.
    "web_read_group": Signature(
        M, ("domain", "groupby", "aggregates", "limit", "offset", "order"), readonly=True
    ),
    "web_search_read": Signature(
        M, ("domain", "specification", "offset", "limit", "order", "count_limit"),
        readonly=True,
    ),
    "web_read": Signature(R, ("specification",), readonly=True),
    "has_access": Signature(R, ("operation",)),
    "get_field_translations": Signature(R, ("field_name", "langs")),
    "update_field_translations": Signature(R, ("field_name", "translations", "source_lang")),
    "export_data": Signature(R, ("fields_to_export",)),
    "load": Signature(M, ("fields", "data")),
    "action_archive": Signature(R, ()),
    "action_unarchive": Signature(R, ()),
}

# Methods of one model only, keyed by (model, method).
MODEL_SIGNATURES: dict[tuple[str, str], Signature] = {
    ("res.users", "context_get"): Signature(M, ()),
    # A record method on 18.0+ (16-17 had an @api.model variant; JSON-2 starts at saas~18.4).
    ("res.users", "has_group"): Signature(R, ("group_ext_id",), readonly=True),
    ("res.users", "has_groups"): Signature(R, ("group_spec",), readonly=True),
    ("base_import.import", "execute_import"): Signature(
        R, ("fields", "columns", "options", "dryrun")
    ),
}

# Methods whose name or parameters differ between JSON-2 series.
SERIES_VARIANTS: dict[str, tuple[Variant, ...]] = {
    "default_get": (
        Variant((18, 4), (19, 0), Signature(M, ("fields_list",))),
        Variant((19, 0), None, Signature(M, ("fields",))),
    ),
    "read_group": (
        Variant(
            (18, 4), (19, 1),
            Signature(M, ("domain", "fields", "groupby", "offset", "limit", "orderby", "lazy"),
                      readonly=True),
            "the classic read_group, deprecated in 19.0",
        ),
        Variant(
            (19, 1), (20, 0), None,
            "read_group does not exist on Odoo Online saas~19.1 to saas~19.4; "
            "use formatted_read_group (odoo_read_group does)",
        ),
        Variant(
            (20, 0), None,
            Signature(M, ("domain", "groupby", "aggregates", "having", "offset", "limit",
                          "order")),
            "20.0 reuses the name with the _read_group signature and returns tuples",
        ),
    ),
    "check_access_rights": (
        Variant((18, 4), (19, 1), Signature(M, ("operation", "raise_exception"))),
        Variant((19, 1), None, None,
                "check_access_rights was removed in saas~19.1; use has_access"),
    ),
    "name_get": (
        Variant((18, 4), None, None,
                "name_get does not exist since Odoo 18; read the display_name field"),
    ),
}

Introspector = Callable[[str, str], Optional[Signature]]


def _variant(method: str, series: Series) -> Variant | None:
    for variant in SERIES_VARIANTS.get(method, ()):
        if variant.since <= series and (variant.until is None or series < variant.until):
            return variant
    return None


def lookup(model: str, method: str, series: Series | None = None) -> Signature | None:
    """The signature of ``model.method`` on ``series``, or ``None`` when unknown.

    Raises :class:`CompatError` when the method is known NOT to exist on that
    series (e.g. ``read_group`` on saas~19.1 to saas~19.4).
    """
    point = series or DEFAULT_SERIES
    specific = MODEL_SIGNATURES.get((model, method))
    if specific is not None:
        return specific
    variant = _variant(method, point)
    if variant is not None:
        if variant.signature is None:
            raise CompatError(
                f"{model}.{method} does not exist on this Odoo series "
                f"({point[0]}.{point[1]})",
                remediation=variant.note,
            )
        return variant.signature
    return SIGNATURES.get(method)


def as_ids(value: Any) -> Any:
    """``5`` -> ``[5]``; lists and tuples -> a list; anything else is left for Odoo."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    return value


def to_named(
    model: str,
    method: str,
    args: list[Any] | None,
    kwargs: dict[str, Any] | None,
    series: Series | None = None,
    *,
    ids: Any = None,
    introspect: Introspector | None = None,
    signature: Signature | None = None,
    used: list[Signature] | None = None,
) -> dict[str, Any]:
    """Map an ``execute_kw`` call to a JSON-2 body.

    ``ids`` given explicitly (``odoo_execute``'s top-level argument) are sent
    as-is and every positional arg is a parameter after them; otherwise a record
    method's first positional arg is the ids. ``kwargs['context']`` becomes the
    top-level ``context``. Positional args of a method outside the table need
    ``introspect(model, method)`` (``/doc-bearer``); without a signature the call
    is refused with a :class:`CompatError` that asks for named arguments.

    ``signature`` (optional) replaces the table and the introspection, e.g. the
    signature a JSON-2 bind error taught the transport; the signature that named
    the positional args is appended to ``used`` when given.
    """
    named = dict(kwargs or {})
    context = named.pop("context", None)
    positional = list(args or [])
    body: dict[str, Any] = {}
    if ids is not None:
        body["ids"] = as_ids(ids)
    if signature is None:
        signature = lookup(model, method, series)  # raises for a method gone on this series
    if positional:
        if signature is None and introspect is not None:
            signature = introspect(model, method)
        if signature is None:
            raise CompatError(
                f"{model}.{method}: JSON-2 takes named arguments only, and this method's "
                "parameter names are unknown to the plugin",
                remediation='pass the arguments by name in "kwargs" and the record ids in '
                '"ids", e.g. {"ids": [7], "kwargs": {"default": {"name": "Copy"}}}',
            )
        if not signature.model_level and ids is None:
            body["ids"] = as_ids(positional.pop(0))
        if len(positional) > len(signature.params):
            raise CompatError(
                f"{model}.{method}: {len(positional)} positional argument(s) given, the "
                f"method takes {len(signature.params)} after the ids "
                f"({', '.join(signature.params) or 'none'})",
                remediation="check the arguments, or pass them by name in kwargs",
            )
        body.update(zip(signature.params, positional))
        if used is not None:
            used.append(signature)
    for key, value in named.items():
        if key in body:
            raise CompatError(
                f"{model}.{method}: argument '{key}' is given twice (positionally and by name)",
                remediation="pass each argument once",
            )
        body[key] = value
    if context is not None:
        body["context"] = context
    return body
