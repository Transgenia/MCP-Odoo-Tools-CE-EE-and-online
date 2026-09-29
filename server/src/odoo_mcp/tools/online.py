# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Odoo Online tools: profile, API catalog, access check, stored documents, imports.

Odoo Online runs no custom Python, takes external API calls on Custom plans
only, asks clients to pace themselves (about one call per second), expires API
keys (18.0+) and moves to a new saas~X.Y line every few months. These tools make
that visible, and give the sanctioned bulk path (imports) a safe shape.

They behave the same over XML-RPC, JSON-RPC and JSON-2 on Odoo 10-19, degrading
per version, except the two import tools: Odoo's XML-RPC cannot marshal the
``None`` values an import result carries, so a committed import could read as
a failure there. Those calls are limited to JSON-2 and JSON-RPC and are never
replayed over XML-RPC.

Feature ideas (no code) came from other projects, named with their licences in
``docs/design/json2-online-lite.md`` section 2.5.
"""

from __future__ import annotations

import csv
import datetime
import io
from collections.abc import Callable
from typing import Any

from ..compat import has_capability, method_available, requires_edition, resolve_model
from ..compat.detect import EnvFacts, parse_version
from ..errors import CompatError, OdooFault, TransportError
from ..registry import ToolContext, obj, registry
from ..transport.json2_signatures import (
    JSON2_FIRST_SERIES,
    MODEL_SIGNATURES,
    SERIES_VARIANTS,
    SIGNATURES,
    lookup,
)

Series = tuple[int, int]

LEGACY_REMOVED: Series = (21, 1)  # Online saas~21.1; on-premise Odoo 22 is past it too
DOC_BEARER_SINCE: Series = (19, 0)
IMPORT_TRANSPORTS = ("json2", "jsonrpc")

OPERATIONS = ("read", "write", "create", "unlink")
MAX_IMPORT_ROWS = 500
MAX_IMPORT_FIELDS = 100
MAX_MESSAGES = 100
MAX_CATALOG_METHODS = 100
DEFAULT_MAX_BYTES = 1024 * 1024
HARD_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_DOC_LIMIT = 50
MAX_DOC_LIMIT = 500
KEY_EXPIRY_WARNING_HOURS = 48

# Neutral import options: Odoo's server formats (YYYY-MM-DD dates, '.' decimals)
# and no header row, so the dry run parses the rows as close as possible to what
# load() receives, and base_import stores no column mapping (it only does when
# has_headers is set).
IMPORT_OPTIONS: dict[str, Any] = {
    "quoting": '"',
    "separator": ",",
    "encoding": "utf-8",
    "has_headers": False,
    "date_format": "",
    "datetime_format": "",
    "float_thousand_separator": "",
    "float_decimal_separator": ".",
}

LEGACY_RPC = {
    "deprecated_since": "19.0",
    "removed_on_premise": "Odoo 22 (fall 2028)",
    "removed_on_odoo_online": "saas~21.1 (winter 2027)",
    "replacement": "JSON-2 (/json/2/<model>/<method>, API key only), saas~18.4 and 19.0+",
}

ONLINE_HINTS = (
    ("External API access (XML-RPC, JSON-RPC, JSON-2) needs an Odoo Online Custom plan; "
     "One App Free and Standard plans do not include it."),
    ("Pace the calls: Odoo's Acceptable Use Policy accepts about 1 call per second with no "
     "parallel calls. Prefer batch calls (odoo_search_read, odoo_import) for bulk work."),
    ("Outgoing e-mail is limited to between 5 and 200 e-mails per day, depending on the "
     "subscription; messages that notify followers count."),
    ("Only data modules can be installed (no custom Python, no Apps Store modules); Studio "
     "customizations live in the database."),
    ("API keys expire from Odoo 18: a user who is not an administrator must give a key an "
     "expiry, at most 1 day unless one of the user's groups allows longer."),
)

_DEPLOYMENT_NOTES = {
    ("saas", "version"): "the version string is an Odoo Online saas~ line",
    ("saas", "host"): "the host is *.odoo.com, which Odoo Online and Odoo.sh both use",
    ("onprem", "host"): "the host is not *.odoo.com and the series is a stable one; an Odoo "
    "Online database on its own domain looks the same",
    ("unknown", "host"): "not enough evidence",
}


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# --- shared helpers -----------------------------------------------------------

def _series(ctx: ToolContext, facts: EnvFacts) -> Series:
    """The unclamped ``(major, minor)``: a 20.0 target stays 20.0 here."""
    series = getattr(getattr(ctx.session, "transport", None), "series", None)
    if isinstance(series, tuple) and len(series) == 2:
        return series
    version_info = getattr(ctx.session, "version_info", None)
    if callable(version_info):
        major, minor, _raw = parse_version(version_info())
        return major, minor
    return facts.series


def series_label(series: Series, raw_version: str = "") -> str:
    """``19.0`` for a stable series, ``saas~19.2`` for an Odoo Online line."""
    major, minor = series
    if minor or "saas~" in (raw_version or ""):
        return f"saas~{major}.{minor}"
    return f"{major}.{minor}"


def deployment_evidence(facts: EnvFacts) -> tuple[str, str, str]:
    """``(deployment, confidence, note)``.

    ``version``: a ``saas~`` version string, which only Odoo Online runs (also
    on a custom domain); ``host``: the host name only (``*.odoo.com`` is also
    Odoo.sh); ``override``: set by the operator, when the facts carry it.
    """
    confidence = getattr(facts, "deployment_confidence", None)
    if confidence:
        note = "set by ODOO_DEPLOYMENT" if confidence == "override" else _DEPLOYMENT_NOTES.get(
            (facts.deployment, str(confidence)), "")
        return facts.deployment, str(confidence), note
    if "saas~" in (facts.raw_version or ""):
        return "saas", "version", _DEPLOYMENT_NOTES[("saas", "version")]
    deployment = facts.deployment if facts.deployment in ("saas", "onprem") else "unknown"
    return deployment, "host", _DEPLOYMENT_NOTES[(deployment, "host")]


def _field_names(ctx: ToolContext, model: str) -> set[str]:
    return set(ctx.session.fields_get(model, ["type"]) or {})


def _attempt(unavailable: dict[str, str], section: str, fn: Callable[[], Any]) -> Any:
    """Run one optional section; an Odoo refusal is recorded, not raised."""
    try:
        return fn()
    except OdooFault as exc:
        unavailable[section] = str(exc)
        return None


def _hours_until(stamp: Any) -> float | None:
    """Hours from now to an Odoo UTC datetime string (negative once past)."""
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        when = datetime.datetime.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    return round((when - _now()).total_seconds() / 3600, 1)


def _many2one(value: Any) -> Any:
    return list(value) if isinstance(value, (list, tuple)) else (value or None)


# --- odoo_online_profile -----------------------------------------------------

@registry.tool(
    "odoo_online_profile",
    "Read-only report of what matters on Odoo Online (and useful anywhere), in one call: "
    "the series and line (stable 19.0 or Online saas~19.2), edition, deployment with its "
    "evidence (deployment_confidence), the active transport, whether JSON-2 and Odoo's "
    "/doc-bearer catalog are usable, transport_notice, when /xmlrpc and /jsonrpc disappear "
    "(Odoo 22; Odoo Online saas~21.1), the signed-in user and companies, 2FA, the user's API "
    "keys with expiry (names and dates only, never key material), installed applications, "
    "imported data modules, whether Studio is installed, and Odoo Online limits (Custom "
    "plan, about 1 call/s, 5-200 e-mails/day, data modules only). Odoo 10-19; what a "
    "version lacks is null.",
    obj({}),
)
def odoo_online_profile(ctx: ToolContext, args: dict[str, Any]) -> Any:
    session = ctx.session
    uid = session.uid  # signs in: this also settles the transport
    facts = session.facts()
    transport = getattr(session, "transport", None)
    series = _series(ctx, facts)
    deployment, confidence, deployment_note = deployment_evidence(facts)
    credential = getattr(getattr(session, "creds", None), "secret_kind", None) or getattr(
        transport, "secret_kind", "unknown")
    json2_available = bool(getattr(transport, "json2_available", False))
    unavailable: dict[str, str] = {}
    hints: list[str] = []

    doc_bearer: bool | None = None
    if json2_available and series >= DOC_BEARER_SINCE:
        try:
            doc_bearer = session.api_doc("res.partner") is not None
        except (OdooFault, TransportError) as exc:
            doc_bearer = False
            unavailable["doc_bearer"] = str(exc)

    # -- the signed-in user
    def user_section() -> dict[str, Any]:
        context = session.execute("res.users", "context_get", []) or {}
        present = _field_names(ctx, "res.users")
        wanted = [f for f in ("login", "name", "company_id", "company_ids", "totp_enabled")
                  if f in present]
        rows = session.execute("res.users", "read", [[uid]], {"fields": wanted}) or [{}]
        row = rows[0] if rows else {}
        company_ids = list(row.get("company_ids") or [])
        user: dict[str, Any] = {
            "uid": uid,
            "login": row.get("login"),
            "name": row.get("name"),
            "company": _many2one(row.get("company_id")),
            "company_ids": company_ids,
            "lang": context.get("lang"),
            "tz": context.get("tz"),
            "totp_enabled": row.get("totp_enabled") if "totp_enabled" in present else None,
        }
        if len(company_ids) > 1:
            user["companies"] = session.name_get("res.company", company_ids)
        return user

    user = _attempt(unavailable, "user", user_section)

    # -- API keys: names and dates only (the model has no field with key material)
    api_keys: list[dict[str, Any]] | None = None
    if has_capability("api_key_auth", facts):
        def keys_section() -> list[dict[str, Any]]:
            present = _field_names(ctx, "res.users.apikeys")
            wanted = [f for f in ("name", "scope", "create_date", "expiration_date")
                      if f in present]
            rows = session.execute("res.users.apikeys", "search_read",
                                   [[["user_id", "=", uid]]], {"fields": wanted}) or []
            keys = []
            for row in rows:
                expiry = row.get("expiration_date") or None
                keys.append({
                    "name": row.get("name"),
                    "scope": row.get("scope") or None,
                    "create_date": row.get("create_date") or None,
                    "expiration_date": expiry,
                    "expires_in_hours": _hours_until(expiry),
                })
            return keys

        api_keys = _attempt(unavailable, "api_keys", keys_section)
        hours_left = [k["expires_in_hours"] for k in api_keys or []
                      if k["expires_in_hours"] is not None]
        soon = [h for h in hours_left if 0 <= h < KEY_EXPIRY_WARNING_HOURS]
        if soon and credential == "api_key":
            hints.append(
                f"An API key of this user expires in {min(soon)} h. If it is the key this "
                "plugin uses, create a new one (Preferences > Account Security) and update "
                "the plugin option before then."
            )
        expired = sum(1 for h in hours_left if h < 0)
        if expired:
            hints.append(f"{expired} API key(s) of this user have expired; they no longer "
                         "work and can be deleted (Preferences > Account Security).")
    else:
        unavailable["api_keys"] = "API keys exist from Odoo 14"

    # -- modules: applications, imported data modules, Studio (one query)
    def modules_section() -> dict[str, Any]:
        has_imported = "imported" in _field_names(ctx, "ir.module.module")
        either: list[Any] = [["application", "=", True], ["name", "=", "web_studio"]]
        if has_imported:
            either.append(["imported", "=", True])
        domain = [["state", "=", "installed"]] + ["|"] * (len(either) - 1) + either
        fields = ["name", "shortdesc", "application"] + (["imported"] if has_imported else [])
        rows = session.execute("ir.module.module", "search_read", [domain],
                               {"fields": fields, "order": "name"}) or []
        return {
            "applications": [{"name": r.get("name"), "title": r.get("shortdesc")}
                             for r in rows if r.get("application")],
            "imported_modules": [{"name": r.get("name"), "title": r.get("shortdesc")}
                                 for r in rows if r.get("imported")] if has_imported else None,
            "studio_installed": any(r.get("name") == "web_studio" for r in rows),
        }

    modules = _attempt(unavailable, "modules", modules_section) or {
        "applications": None, "imported_modules": None, "studio_installed": None}

    notice = getattr(transport, "transport_notice", None)
    if notice:
        hints.append(notice)
    result: dict[str, Any] = {
        "series": series_label(series, facts.raw_version),
        "version": series[0],
        "minor": series[1],
        "line": "saas" if series[1] or "saas~" in (facts.raw_version or "") else "stable",
        "raw_version": facts.raw_version,
        "edition": facts.edition,
        "deployment": deployment,
        "deployment_confidence": confidence,
        "deployment_note": deployment_note,
        "transport": getattr(transport, "active", None),
        "credential": credential,
        "json2_available": json2_available,
        "doc_bearer": doc_bearer,
        "transport_notice": notice,
        "legacy_rpc": {**LEGACY_RPC, "available_on_this_series": series < LEGACY_REMOVED},
        "user": user,
        "api_keys": api_keys,
        **modules,
        "hints": hints,
        "online_hints": list(ONLINE_HINTS),
        "online_hints_apply": deployment == "saas",
    }
    if unavailable:
        result["unavailable"] = unavailable
    return result


# --- odoo_api_catalog --------------------------------------------------------

# name_get exists up to 17.0; res.users.has_group is an @api.model method there too.
NAME_GET_REMOVED: Series = (18, 0)

def _doc_bearer_methods(doc: dict[str, Any]) -> list[dict[str, Any]]:
    methods = doc.get("methods") if isinstance(doc, dict) else None
    out = []
    for name, meta in (methods or {}).items():
        if not isinstance(meta, dict):
            continue
        params = meta.get("parameters") if isinstance(meta.get("parameters"), dict) else {}
        names = [p for p, spec in params.items()
                 if not (isinstance(spec, dict)
                         and spec.get("kind") in ("VAR_POSITIONAL", "VAR_KEYWORD"))]
        api = meta.get("api") or []
        entry: dict[str, Any] = {
            "name": name,
            "parameters": names,
            "model_level": "model" in api,
            "readonly": "readonly" in api,
        }
        if isinstance(meta.get("signature"), str):
            entry["signature"] = meta["signature"]
        out.append(entry)
    return out


def builtin_methods(model: str, series: Series, facts: EnvFacts) -> list[dict[str, Any]]:
    """The plugin's own table (``json2_signatures``) for ``model`` on ``series``.

    From saas~18.4 on, ``parameters`` are the names of the base definitions (a
    model's override may rename one; JSON-2 calls made by the plugin correct
    that). Before saas~18.4 (no JSON-2) the names were not verified for that
    series and differ for some methods (``name_search(args)``, the classic
    ``web_read_group``, overrides of ``default_get`` and ``write``), so
    ``parameters`` is ``None`` there and only the flags are given; ``name_get``
    is listed where it exists (up to 17.0).
    """
    verified = series >= JSON2_FIRST_SERIES
    point = max(series, JSON2_FIRST_SERIES)
    names = set(SIGNATURES) | set(SERIES_VARIANTS) | {
        method for (owner, method) in MODEL_SIGNATURES if owner == model}
    out = []
    for name in sorted(names):
        if name not in SERIES_VARIANTS and not method_available(name, facts):
            continue
        if name == "name_get" and series < NAME_GET_REMOVED:
            out.append({"name": name, "parameters": None, "model_level": False,
                        "readonly": True})
            continue
        try:
            signature = lookup(model, name, point)
        except CompatError:  # known not to exist on this series
            continue
        if signature is None:
            continue
        model_level = signature.model_level
        if (model, name) == ("res.users", "has_group") and series < NAME_GET_REMOVED:
            model_level = True  # an @api.model method on 16.0-17.0
        out.append({
            "name": name,
            "parameters": list(signature.params) if verified else None,
            "model_level": model_level,
            "readonly": signature.readonly,
        })
    return out


@registry.tool(
    "odoo_api_catalog",
    "Read-only. List a model's public methods with their parameter names in order, whether "
    "each is model-level (takes no record ids) and whether it is read-only, for JSON-2 "
    "(Odoo 19+) and odoo_execute's 'kwargs' + 'ids' form. On Odoo 19.0+ with an "
    "administrator's API key it reads Odoo's own per-database catalog (/doc-bearer, cached "
    "with its ETag): this model's exact names, custom and Studio methods included. "
    "Otherwise it returns the plugin's built-in table of the methods it knows: the base "
    "names from saas~18.4 on (a model may rename a parameter), and no names (parameters "
    "null) before saas~18.4, where odoo_execute takes positional 'args'. 'source' says "
    "which, and 'note' why. 'method' filters names by substring. At most 100 methods; "
    "fields are in odoo_fields_get.",
    obj(
        {
            "model": {"type": "string", "description": "technical model name, e.g. res.partner"},
            "method": {
                "type": "string",
                "description": "optional case-insensitive substring of the method names",
            },
        },
        required=["model"],
    ),
)
def odoo_api_catalog(ctx: ToolContext, args: dict[str, Any]) -> Any:
    session = ctx.session
    _ = session.uid
    facts = session.facts()
    model = resolve_model(args["model"], facts)
    requires_edition(model, facts)
    series = _series(ctx, facts)
    label = series_label(series, facts.raw_version)
    transport = getattr(session, "transport", None)

    doc: dict[str, Any] | None = None
    reason = ""
    if series < DOC_BEARER_SINCE:
        reason = f"Odoo's /doc-bearer catalog exists from Odoo 19.0; this server runs {label}"
    elif not getattr(transport, "json2_available", False):
        reason = ("/doc-bearer needs an API key (ODOO_API_KEY) and no user:pass@ in "
                  "ODOO_URL")
    else:
        try:
            doc = session.api_doc(model)
        except (OdooFault, TransportError) as exc:
            reason = f"/doc-bearer failed ({exc})"
        if doc is None and not reason:
            reason = ("/doc-bearer refused this API key: it needs an administrator's key "
                      "(group api_doc.group_allow_doc)")

    if doc is not None:
        source = "doc-bearer"
        methods = _doc_bearer_methods(doc)
        note = ("Odoo's own catalog for this database (/doc-bearer). JSON-2 takes these "
                "parameters by name; pass record ids as 'ids' unless model_level is true.")
    else:
        # fields_get answers any internal user (ir.model needs the Access Rights
        # group on 19.0) and refuses an unknown model on every version.
        try:
            _field_names(ctx, model)
        except OdooFault as exc:
            if "exist" not in str(exc):
                raise
            raise CompatError(
                f"model {model!r} does not exist on this database",
                remediation="check the technical name with odoo_list_models",
            ) from exc
        source = "builtin"
        methods = builtin_methods(model, series, facts)
        note = (f"{reason}. Showing the plugin's built-in table of the methods it knows; "
                "methods added by modules or Studio are not in it.")
        if series < JSON2_FIRST_SERIES:
            note += (f" Odoo {label} has no JSON-2: pass positional 'args' to odoo_execute "
                     "(execute_kw order). Parameter names are not given (parameters is "
                     "null) because they differ on this series (e.g. name_search takes "
                     "'args', web_read_group the classic arguments, and models override "
                     "default_get and write with other names); web_read and the "
                     "web_search_read specification need 17+.")
        else:
            note += (" Parameter names are those of the base definitions in the Odoo "
                     "source of saas~18.4 and newer; this model's override may rename one "
                     "(on saas~18.4 res.company and product.pricelist take write(values), "
                     "res.partner default_get(default_fields)). JSON-2 calls made by the "
                     "plugin with positional args correct such names by themselves.")

    needle = (args.get("method") or "").strip().lower()
    if needle:
        methods = [m for m in methods if needle in m["name"].lower()]
    methods.sort(key=lambda m: m["name"])
    total = len(methods)
    return {
        "model": model,
        "series": label,
        "source": source,
        "count": total,
        "methods": methods[:MAX_CATALOG_METHODS],
        "truncated": total > MAX_CATALOG_METHODS,
        "note": note,
    }


# --- odoo_access_check -------------------------------------------------------

@registry.tool(
    "odoo_access_check",
    "Read-only. Check what the signed-in Odoo user (the owner of the configured credential) "
    "may do on a model: read, write, create and unlink, or the subset in 'operations', plus "
    "export_allowed (group base.group_allow_export, Odoo 16+). Model level (access rights) "
    "by default; with 'ids' on Odoo 18+ the record rules of those records count too. Uses "
    "has_access on Odoo 18+ and check_access_rights on 10-17. Changes nothing.",
    obj(
        {
            "model": {"type": "string", "description": "technical model name, e.g. sale.order"},
            "operations": {
                "type": "array",
                "items": {"type": "string", "enum": list(OPERATIONS)},
                "minItems": 1,
                "description": "default: all four",
            },
            "ids": {
                "type": "array",
                "items": {"type": "integer"},
                "maxItems": 1000,
                "description": "optional record ids for a record-level check (Odoo 18+)",
            },
        },
        required=["model"],
    ),
)
def odoo_access_check(ctx: ToolContext, args: dict[str, Any]) -> Any:
    session = ctx.session
    uid = session.uid
    facts = session.facts()
    model = resolve_model(args["model"], facts)
    requires_edition(model, facts)
    operations = list(dict.fromkeys(args.get("operations") or OPERATIONS))
    ids = [int(i) for i in args.get("ids") or []]
    record_level = method_available("has_access", facts)
    notes: list[str] = []

    access: dict[str, bool] = {}
    for operation in operations:
        if record_level:
            allowed = session.execute(model, "has_access", [operation], ids=ids)
        else:
            allowed = session.execute(model, "check_access_rights", [operation],
                                      {"raise_exception": False})
        access[operation] = bool(allowed)
    if ids and not record_level:
        notes.append("Record-level checks need Odoo 18+: these are model-level access rights "
                     "only; record rules were not evaluated.")

    export_allowed: bool | None = None
    if facts.version >= 16:
        try:
            if facts.version >= 18:  # a record method from 18.0
                export_allowed = bool(session.execute(
                    "res.users", "has_group", ["base.group_allow_export"], ids=[uid]))
            else:  # @api.model on 16-17: checks the current user
                export_allowed = bool(session.execute(
                    "res.users", "has_group", ["base.group_allow_export"]))
        except OdooFault as exc:
            notes.append(f"export_allowed could not be checked: {exc}")
    else:
        notes.append("Before Odoo 16 no group restricts exports: a user who can read a model "
                     "can export it.")
    if not all(access.values()):
        notes.append("A refused operation comes from access rights (ir.model.access) or, at "
                     "record level, record rules (ir.rule) of this user's groups; an "
                     "administrator changes them in Settings > Users & Companies.")
    result: dict[str, Any] = {
        "model": model,
        "uid": uid,
        "level": "record" if ids and record_level else "model",
        "method": "has_access" if record_level else "check_access_rights",
        "access": access,
        "export_allowed": export_allowed,
    }
    if ids:
        result["ids"] = ids
    if notes:
        result["notes"] = notes
    return result


# --- odoo_record_documents ---------------------------------------------------

_ATTACHMENT_FIELDS = ["name", "mimetype", "file_size", "create_date", "type"]


def _document(row: dict[str, Any], main_id: Any, invoice_pdf_id: Any) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "mimetype": row.get("mimetype") or None,
        "file_size": row.get("file_size"),
        "create_date": row.get("create_date"),
        "type": row.get("type") or None,
        "is_main_attachment": bool(main_id) and row.get("id") == main_id,
        "is_invoice_pdf": bool(invoice_pdf_id) and row.get("id") == invoice_pdf_id,
    }


def _m2o_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@registry.tool(
    "odoo_record_documents",
    "Read-only. List the files attached to one record (id, name, mimetype, file_size in "
    "bytes, create_date), flagging its main attachment and, on invoices (Odoo 17+), the "
    "stored invoice PDF. With attachment_id and include_content=true it also returns that "
    "file base64-encoded, only if it belongs to this record and its size is at most "
    "max_bytes (default 1048576 = 1 MiB, at most 5 MiB). Use it for PDFs on Odoo 14+, "
    "where reports cannot be rendered over RPC: it returns documents Odoo already stored "
    "(e.g. an invoice PDF made when the invoice was sent or printed). Odoo 10-19.",
    obj(
        {
            "model": {"type": "string", "description": "technical model name, e.g. account.move"},
            "res_id": {"type": "integer", "description": "the record's id"},
            "attachment_id": {
                "type": "integer",
                "description": "one attachment of this record (an id from the listing)",
            },
            "include_content": {
                "type": "boolean",
                "default": False,
                "description": "return attachment_id's file as base64 (needs attachment_id)",
            },
            "max_bytes": {
                "type": "integer",
                "default": DEFAULT_MAX_BYTES,
                "description": "largest file returned, in bytes (at most 5242880)",
            },
            "limit": {
                "type": "integer",
                "default": DEFAULT_DOC_LIMIT,
                "description": "largest number of attachments listed, newest first "
                "(at most 500)",
            },
        },
        required=["model", "res_id"],
    ),
)
def odoo_record_documents(ctx: ToolContext, args: dict[str, Any]) -> Any:
    session = ctx.session
    facts = session.facts()
    model = resolve_model(args["model"], facts)
    requires_edition(model, facts)
    res_id = int(args["res_id"])
    attachment_id = args.get("attachment_id")
    include_content = bool(args.get("include_content", False))
    if include_content and attachment_id is None:
        raise CompatError(
            "include_content needs attachment_id",
            remediation="list the documents first, then ask for one attachment_id",
        )
    notes: list[str] = []
    max_bytes = int(args.get("max_bytes", DEFAULT_MAX_BYTES))
    if max_bytes > HARD_MAX_BYTES or max_bytes < 1:
        max_bytes = min(max(max_bytes, 1), HARD_MAX_BYTES)
        notes.append(f"max_bytes was limited to {max_bytes}")
    limit = min(max(int(args.get("limit", DEFAULT_DOC_LIMIT)), 1), MAX_DOC_LIMIT)

    # Flags: the record's main attachment, and an invoice's stored PDF (17+).
    present = _field_names(ctx, model)
    flag_fields = [f for f in ("message_main_attachment_id", "invoice_pdf_report_id")
                   if f in present]
    main_id = invoice_pdf_id = None
    if flag_fields:
        rows = session.execute(model, "read", [[res_id]], {"fields": flag_fields})
        if not rows:
            raise CompatError(f"{model} record {res_id} does not exist",
                              remediation="check the id with odoo_search")
        main_id = _m2o_id(rows[0].get("message_main_attachment_id"))
        invoice_pdf_id = _m2o_id(rows[0].get("invoice_pdf_report_id"))

    listed = session.execute(
        "ir.attachment", "search_read",
        [[["res_model", "=", model], ["res_id", "=", res_id]]],
        {"fields": _ATTACHMENT_FIELDS, "limit": limit, "order": "create_date desc, id desc"},
    ) or []
    documents = [_document(row, main_id, invoice_pdf_id) for row in listed]
    known = {doc["id"] for doc in documents}
    # A file stored in a binary field (the invoice PDF) is hidden from a plain
    # search; read it by id.
    extra_ids = [i for i in (invoice_pdf_id, main_id) if i and i not in known]
    if extra_ids:
        for row in session.execute("ir.attachment", "read", [list(dict.fromkeys(extra_ids))],
                                   {"fields": _ATTACHMENT_FIELDS}) or []:
            documents.append(_document(row, main_id, invoice_pdf_id))
    result: dict[str, Any] = {
        "model": model,
        "res_id": res_id,
        "count": len(documents),
        "documents": documents,
        "main_attachment_id": main_id,
        "invoice_pdf_attachment_id": invoice_pdf_id,
    }
    if len(listed) >= limit:
        notes.append(f"the listing stops at limit={limit}; there may be more attachments")

    if attachment_id is not None:
        attachment_id = int(attachment_id)
        rows = session.execute("ir.attachment", "read", [[attachment_id]],
                               {"fields": _ATTACHMENT_FIELDS + ["res_model", "res_id"]}) or []
        row = rows[0] if rows else None
        if row is None or row.get("res_model") != model or row.get("res_id") != res_id:
            raise CompatError(
                f"attachment {attachment_id} does not belong to {model} record {res_id}",
                remediation="pick an id from this record's documents listing",
            )
        attachment = _document(row, main_id, invoice_pdf_id)
        if include_content:
            size = row.get("file_size") or 0
            if row.get("type") == "url":
                attachment["content_skipped"] = "a URL attachment has no stored file"
            elif size > max_bytes:
                attachment["content_skipped"] = (
                    f"the file has {size} bytes, more than max_bytes={max_bytes}")
            else:
                data = session.execute("ir.attachment", "read", [[attachment_id]],
                                       {"fields": ["datas"]}) or [{}]
                attachment["content_base64"] = data[0].get("datas") or ""
        result["attachment"] = attachment
    if notes:
        result["notes"] = notes
    return result


# --- imports ---------------------------------------------------------------

_IMPORT_FIELDS_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
    "minItems": 1,
    "maxItems": MAX_IMPORT_FIELDS,
    "description": "load() column names, e.g. [\"name\", \"email\", \"country_id\"]; "
    "'field/id' takes an external id, 'id' holds the record's own external id",
}
_IMPORT_ROWS_SCHEMA = {
    "type": "array",
    "items": {"type": "array", "items": {"type": "string"}},
    "minItems": 1,
    "maxItems": MAX_IMPORT_ROWS,
    "description": "one list of strings per record, in the order of 'fields' (CSV cells: "
    "dates YYYY-MM-DD, numbers with '.' decimals, many2one by name or with field/id)",
}


def _check_rows(fields: list[str], rows: list[list[str]]) -> None:
    for index, row in enumerate(rows):
        if len(row) != len(fields):
            raise CompatError(
                f"row {index} has {len(row)} value(s) but 'fields' has {len(fields)}",
                remediation="give every row exactly one string per field, '' for empty",
            )
        if not any(cell.strip() for cell in row):
            raise CompatError(
                f"row {index} is empty",
                remediation="remove empty rows; Odoo's importer skips them, so the row "
                "numbers of its messages would shift",
            )


def _json_transport(ctx: ToolContext, tool: str) -> None:
    """Refuse up front when the session runs on XML-RPC."""
    _ = ctx.session.uid  # the sign-in settles which transport is used
    active = str(getattr(getattr(ctx.session, "transport", None), "active", "") or "")
    if active.split("(")[0] == "xmlrpc":
        raise CompatError(
            f"{tool} needs JSON-RPC or JSON-2, and this session uses XML-RPC: Odoo's XML-RPC "
            "cannot return the empty (None) values an import result carries, so a saved "
            "import could be reported as a failure",
            remediation="set ODOO_TRANSPORT_PREF=auto (or json2 with an API key on Odoo 19+); "
            "JSON-RPC exists from Odoo 12, and a proxy in front of Odoo must let /jsonrpc or "
            "/json/2 through",
        )


_MESSAGE_KEYS = ("type", "message", "rows", "record", "field", "field_name", "value")


def _compact(message: Any) -> Any:
    """Keep what explains a row; drop ``moreinfo`` when it is a UI window action."""
    if not isinstance(message, dict):
        return message
    out = {key: message[key] for key in _MESSAGE_KEYS if key in message}
    if isinstance(message.get("moreinfo"), str):
        out["moreinfo"] = message["moreinfo"]
    return out


def _messages(result: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    messages = [_compact(m) for m in result.get("messages") or []]
    counts = {
        "errors": sum(1 for m in messages if isinstance(m, dict) and m.get("type") == "error"),
        "warnings": sum(1 for m in messages
                        if isinstance(m, dict) and m.get("type") == "warning"),
    }
    extra: dict[str, Any] = dict(counts)
    if len(messages) > MAX_MESSAGES:
        extra["messages_truncated"] = len(messages) - MAX_MESSAGES
        messages = messages[:MAX_MESSAGES]
    return messages, extra


_ROWS_NOTE = "rows.from and rows.to in messages are 0-based indexes into 'rows'"


@registry.tool(
    "odoo_import_preview",
    "Dry-run an import with Odoo's own importer (base_import, Odoo 16-19): returns the "
    "per-row errors and warnings Odoo would report and would_import, the number of records "
    "it would create or update. Odoo rolls the run back, but it can still consume sequence "
    "numbers and trigger effects outside the database (e.g. webhooks of automated actions), "
    "so it is refused in read-only mode (ODOO_READONLY). Same 'fields' and 'rows' as "
    "odoo_import, at most 500 rows. Needs JSON-RPC or JSON-2 (not XML-RPC). It never "
    "imports: call odoo_import only after the user confirms. (write operation)",
    obj(
        {
            "model": {"type": "string", "description": "technical model name, e.g. res.partner"},
            "fields": _IMPORT_FIELDS_SCHEMA,
            "rows": _IMPORT_ROWS_SCHEMA,
        },
        required=["model", "fields", "rows"],
    ),
    read_only=False,
)
def odoo_import_preview(ctx: ToolContext, args: dict[str, Any]) -> Any:
    session = ctx.session
    facts = session.facts()
    model = resolve_model(args["model"], facts)
    requires_edition(model, facts)
    fields, rows = list(args["fields"]), [list(r) for r in args["rows"]]
    _check_rows(fields, rows)
    if facts.version < 16:
        raise CompatError(
            f"odoo_import_preview needs Odoo 16+ (base_import.execute_import with a dry run); "
            f"this server runs {facts.raw_version or facts.version}",
            remediation="try the rows with odoo_import on a sandbox or test copy first",
        )
    _json_transport(ctx, "odoo_import_preview")
    if not session.module_installed("base_import"):
        raise CompatError("the base_import module is not installed on this database",
                          remediation="install it (Apps), or use odoo_import directly")

    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    wizard = session.execute(
        "base_import.import", "create",
        [{"res_model": model, "file": buffer.getvalue(), "file_type": "text/csv",
          "file_name": "odoo-tools-import-preview.csv"}],
        transports=IMPORT_TRANSPORTS,
    )
    wizard_id = wizard[0] if isinstance(wizard, list) else wizard
    try:
        result = session.execute(
            "base_import.import", "execute_import",
            [[wizard_id], fields, list(fields), dict(IMPORT_OPTIONS)], {"dryrun": True},
            transports=IMPORT_TRANSPORTS,
        ) or {}
    finally:
        try:  # the wizard is a transient record Odoo vacuums anyway
            session.execute("base_import.import", "unlink", [[wizard_id]],
                            transports=IMPORT_TRANSPORTS)
        except Exception:  # noqa: S110 - best effort cleanup, never hides the result
            pass
    ids = result.get("ids") if isinstance(result, dict) else None
    messages, extra = _messages(result if isinstance(result, dict) else {})
    would_import = len(ids) if isinstance(ids, list) else 0
    return {
        "model": model,
        "dry_run": True,
        "rows": len(rows),
        "would_import": would_import,
        "ok": would_import > 0 and extra["errors"] == 0,
        **extra,
        "messages": messages,
        "note": ("Nothing was saved: Odoo rolled the dry run back. It may still have consumed "
                 "sequence numbers and run effects outside the database (e.g. webhooks of "
                 "automated actions). " + _ROWS_NOTE + "."),
    }


@registry.tool(
    "odoo_import",
    "Import rows into a model in one atomic call with Odoo's load(): either every row is "
    "saved or nothing is, and the errors say why. Returns the ids of the created or updated "
    "records, their count and Odoo's messages. An 'id' column holds external ids and "
    "upserts: a row whose external id already exists UPDATES that record instead of "
    "creating one. At most 500 rows per call. Needs JSON-RPC or JSON-2 (Odoo 12+), not "
    "XML-RPC. Show the user what will change first (odoo_import_preview on 16+) and wait "
    "for confirmation; it is refused in read-only mode (ODOO_READONLY). (write operation)",
    obj(
        {
            "model": {"type": "string", "description": "technical model name, e.g. res.partner"},
            "fields": _IMPORT_FIELDS_SCHEMA,
            "rows": _IMPORT_ROWS_SCHEMA,
        },
        required=["model", "fields", "rows"],
    ),
    read_only=False,
)
def odoo_import(ctx: ToolContext, args: dict[str, Any]) -> Any:
    session = ctx.session
    facts = session.facts()
    model = resolve_model(args["model"], facts)
    requires_edition(model, facts)
    fields, rows = list(args["fields"]), [list(r) for r in args["rows"]]
    _check_rows(fields, rows)
    _json_transport(ctx, "odoo_import")
    result = session.execute(model, "load", [fields, rows], transports=IMPORT_TRANSPORTS) or {}
    ids = result.get("ids") if isinstance(result, dict) else None
    ids = [i for i in ids if isinstance(i, int)] if isinstance(ids, list) else []
    messages, extra = _messages(result if isinstance(result, dict) else {})
    saved = bool(ids)
    out: dict[str, Any] = {
        "model": model,
        "ok": saved and extra["errors"] == 0,
        "ids": ids,
        "count": len(ids),
        **extra,
        "messages": messages,
    }
    if saved:
        out["note"] = f"Saved {len(ids)} record(s). " + _ROWS_NOTE + "."
    else:
        out["note"] = ("Nothing was saved: load() is all-or-nothing and reported the errors "
                       "in messages. " + _ROWS_NOTE + ".")
    return out
