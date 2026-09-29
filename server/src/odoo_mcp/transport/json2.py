# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""JSON-2 transport (``POST /json/2/<model>/<method>``), on the standard library.

JSON-2 is Odoo's external API from saas~18.4 and 19.0 on; it replaces
``/xmlrpc`` and ``/jsonrpc``, which Odoo 19 deprecates and Odoo 22 (Odoo Online
saas~21.1) removes. A call is one HTTP request:

  * ``Authorization: bearer <API key>``: an API key only, never a password;
  * ``X-Odoo-Database: <db>``;
  * a JSON object body of **named** arguments, plus ``ids`` for a record method
    and ``context`` (the ``json2_signatures`` table names positional args);
  * the reply is the bare result (a recordset becomes its ids), or an Odoo
    error object ``{name, message, arguments, context, debug}`` with an HTTP
    status that carries its class. Odoo rolled the call back in that case.

No cookies (Odoo refuses a session cookie together with ``X-Odoo-Database``),
no ``Accept-Language`` (it would pick the request's language) and no redirects.

Failures keep the split the other transports use, so a retry can never run a
write twice: :class:`Json2Unavailable` means the request certainly never reached
a JSON-2 handler (connect/TLS error, HTTP 3xx, 405, 415, an HTML 4xx page), and a
plain :class:`TransportError` (5xx without an Odoo error body, a timeout after
sending, a cut or non-JSON reply) means Odoo may have run it. Two subclasses of
:class:`Json2Unavailable` say more: :class:`Json2Unreachable` (the server could
not be reached at all) and :class:`Json2SignatureMismatch` (HTTP 422 from Odoo's
``inspect.signature(...).bind`` check, raised before the method runs: the
argument names do not match the model's own override of the method).

A signature mismatch on positional arguments the plugin named is corrected once
and the call is sent again (it never ran): with the signature from
``/doc-bearer`` (19.0+), or, when exactly one argument was named, with the
parameter name Odoo says is missing (saas~18.4 ``write(values)`` on
``res.company``, ``product.pricelist`` or ``mail.thread`` models,
``res.partner.default_get(default_fields)``). The corrected signature is kept
per (database, model, method).
"""

from __future__ import annotations

import gzip
import http.client
import json
import logging
import re
import urllib.error
import urllib.request
import zlib
from email.message import Message
from typing import Any

from ..errors import AuthError, CompatError, ConfigError, OdooFault, RateLimited, TransportError
from .base import parse_retry_after, tls_context
from .json2_signatures import Series, Signature, to_named
from .jsonrpc import JsonRpcUnavailable, _NoRedirect, split_userinfo

log = logging.getLogger("odoo_mcp.transport")

_MODEL_RE = re.compile(r"^[a-z0-9_.]+$")
_METHOD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# The version probes answer from memory, so a short wait is enough and a hung
# server does not cost the full RPC timeout three times.
PROBE_TIMEOUT = 30

# Parameter kinds that cannot be sent by name from a positional list.
_NOT_NAMED = {"VAR_POSITIONAL", "VAR_KEYWORD", "KEYWORD_ONLY", "POSITIONAL_ONLY"}

# /doc-bearer comes with the api_doc module, auto-installed from 19.0.
DOC_BEARER_SINCE: Series = (19, 0)

BASIC_AUTH_CONFLICT = (
    "JSON-2 cannot be used while ODOO_URL carries user:pass@ (HTTP basic auth for a "
    "gateway): both need the Authorization header, which JSON-2 uses for the API key. "
    "Move the gateway credentials elsewhere, or set ODOO_TRANSPORT_PREF=auto to use "
    "the legacy endpoints"
)


class Json2Unavailable(JsonRpcUnavailable):
    """The request never reached an Odoo JSON-2 handler: safe to retry elsewhere."""


class Json2Unreachable(Json2Unavailable):
    """Connecting or sending failed (DNS, TCP, TLS, bad URL): nothing reached Odoo.

    Unlike the other :class:`Json2Unavailable` cases this says nothing about the
    Odoo version or a proxy: the host itself did not answer.
    """


class Json2SignatureMismatch(Json2Unavailable):
    """Odoo refused the argument names before running the method (HTTP 422).

    JSON-2 binds the body to ``inspect.signature`` of the model's top override
    and answers ``UnprocessableEntity`` when that fails, so the method certainly
    did not run and the call may be sent again, named differently or over a
    legacy transport.
    """

    def __init__(self, message: str, *, missing: str | None = None) -> None:
        super().__init__(message)
        self.missing = missing  # the parameter Odoo reported as missing, if any


# The TypeError messages of inspect.Signature.bind (Python 3.8 to 3.13).
_BIND_ERROR_RE = re.compile(
    r"^(?:missing a required (?:keyword-only )?argument: '(?P<missing>\w+)'"
    r"|got an unexpected keyword argument '\w+'"
    r"|too many positional arguments"
    r"|multiple values for argument '\w+')$"
)


def check_names(model: str, method: str) -> None:
    """Refuse bad names before sending: urllib would raise InvalidURL for a space."""
    if not isinstance(model, str) or not _MODEL_RE.match(model):
        raise CompatError(
            f"invalid model name {model!r}",
            remediation="model names use lowercase letters, digits, '_' and '.', "
            "e.g. res.partner",
        )
    if not isinstance(method, str) or not _METHOD_RE.match(method):
        raise CompatError(
            f"invalid or private method name {method!r}",
            remediation="Odoo only accepts public methods over RPC: letters, digits and '_', "
            "not starting with '_'",
        )


def _json(raw: bytes) -> tuple[Any, bool]:
    try:
        return json.loads(raw.decode("utf-8")), True
    except (ValueError, UnicodeDecodeError):
        return None, False


def _is_odoo_error(data: Any) -> bool:
    return isinstance(data, dict) and "name" in data and "message" in data


def _odoo_message(data: dict[str, Any]) -> str:
    """``<name>: <message>``. ``debug`` (the server traceback) is never shown."""
    name = str(data.get("name") or "").strip()
    message = str(data.get("message") or "").strip()
    if name and message:
        return f"{name}: {message}"
    return message or name or "JSON-2 error"


def version_from_json_version(data: Any) -> dict[str, Any] | None:
    """``GET /json/version`` (19.0+) in the ``common.version()`` shape."""
    if not isinstance(data, dict) or not isinstance(data.get("version_info"), list):
        return None
    info = data["version_info"]
    serie = ".".join(str(part) for part in info[:2]) if len(info) >= 2 else None
    return {
        "server_version": data.get("version"),
        "server_version_info": info,
        "server_serie": serie,
        "protocol_version": 1,
    }


class Json2Transport:
    name = "json2"

    def __init__(self, base_url: str, timeout: int = 30) -> None:
        url, self._basic = split_userinfo(base_url.rstrip("/"))
        self.base_url = url  # never contains credentials
        self.timeout = timeout
        # The unclamped series, set by FallbackTransport once it is known; it
        # picks the right parameter names (default_get, read_group).
        self.series: Series | None = None
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=tls_context()), _NoRedirect()
        )
        # (db, model) -> (ETag, /doc-bearer payload or None when not allowed)
        self._docs: dict[tuple[str, str], tuple[str | None, dict[str, Any] | None]] = {}
        self._warned_header = False
        # (db, model, method) -> the signature a 422 bind error taught us
        self._learned: dict[tuple[str, str, str], Signature] = {}

    # -- HTTP ------------------------------------------------------------------
    def _request(
        self,
        verb: str,
        path: str,
        *,
        body: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, Message, bytes]:
        """One request. HTTP error statuses are returned, not raised."""
        data = None if body is None else json.dumps(body).encode("utf-8")
        try:
            request = urllib.request.Request(
                self.base_url + path, data=data, method=verb,
                headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
            )
            if data is not None:
                request.add_header("Content-Type", "application/json")
            for key, value in (headers or {}).items():
                request.add_unredirected_header(key, value)
            with self._opener.open(request, timeout=timeout or self.timeout) as resp:
                status, reply_headers, raw = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            status, reply_headers = exc.code, exc.headers
            try:
                raw = exc.read()
            except (OSError, http.client.HTTPException, EOFError):
                raw = b""
        except urllib.error.URLError as exc:  # connect/TLS/send failed: nothing ran
            raise Json2Unreachable(f"json2 transport error: {exc.reason}") from None
        except http.client.InvalidURL as exc:  # refused by http.client before sending
            raise Json2Unreachable(f"json2 transport error: {exc}") from None
        except (http.client.HTTPException, OSError, EOFError) as exc:
            # Sent, then the reply was cut or timed out: the call may have run.
            raise TransportError(f"json2 transport error: {type(exc).__name__}: {exc}") from None
        except ValueError as exc:  # malformed URL
            raise Json2Unreachable(f"json2 transport error: {exc}") from None
        if (reply_headers.get("Content-Encoding") or "").lower() == "gzip":
            try:
                raw = gzip.decompress(raw)
            except (OSError, EOFError, zlib.error):
                raise TransportError("json2: the gzip reply is corrupt") from None
        return status, reply_headers, raw

    def _auth_headers(self, db: str, secret: str) -> dict[str, str]:
        if self._basic:
            raise ConfigError(BASIC_AUTH_CONFLICT)
        headers = {"Authorization": f"bearer {secret}"}
        if db:
            headers["X-Odoo-Database"] = db
        return headers

    def _result(self, status: int, headers: Message, raw: bytes, db: str) -> Any:
        """Map one JSON-2 reply to its result or to the right error class."""
        ctype = (headers.get("Content-Type") or "").lower()
        data, is_json = _json(raw) if "json" in ctype else (None, False)
        if status == 429:
            raise RateLimited(
                "json2: HTTP 429 Too Many Requests",
                retry_after=parse_retry_after(headers.get("Retry-After")),
            )
        if 200 <= status < 300:
            if not is_json:
                # Sent, and something answered 2xx: Odoo may have run it.
                raise TransportError("json2: the reply is not JSON (a proxy may have answered)")
            return data
        if is_json and _is_odoo_error(data):
            message = _odoo_message(data)
            if status == 401:
                lowered = message.lower()
                if "not authenticated" in lowered:
                    # The key was sent, but Odoo saw no Authorization header.
                    if not self._warned_header:
                        log.warning("JSON-2: Odoo did not receive the Authorization header; "
                                    "a proxy in front of Odoo may drop it")
                        self._warned_header = True
                    raise Json2Unavailable(
                        "json2: HTTP 401, the Authorization header did not reach Odoo "
                        "(a proxy may drop it)"
                    )
                raise AuthError(
                    f"JSON-2 refused the API key ({message}): it is wrong, expired or "
                    "belongs to another database; create a new API key in Odoo "
                    "(Preferences > Account Security; keys expire from Odoo 18)"
                )
            bind = _BIND_ERROR_RE.match(str(data.get("message") or "").strip())
            if (status == 422 and bind
                    and str(data.get("name") or "").endswith("UnprocessableEntity")):
                # signature.bind failed before the method was called: nothing ran.
                raise Json2SignatureMismatch(f"json2: {message}", missing=bind.group("missing"))
            # Odoo ran the call and rolled it back: a definite failure, never replayed.
            raise OdooFault(message)
        if status == 404 and b"No database is selected" in raw:
            raise ConfigError(
                f"Odoo does not serve the database {db!r} on this host (it answered its "
                "'no database selected' page): check ODOO_DB and the server's dbfilter"
            )
        if status >= 500:
            raise TransportError(f"json2: HTTP {status} without an Odoo error body")
        # 3xx (an older series sends /json/* to the login page), 405, 415 or an
        # HTML 4xx page: no JSON-2 handler ran.
        kind = ctype.split(";")[0] or "no content type"
        raise Json2Unavailable(f"json2: HTTP {status} ({kind}) instead of a JSON-2 reply")

    def _call(self, db: str, secret: str, model: str, method: str, body: dict[str, Any]) -> Any:
        check_names(model, method)
        headers = self._auth_headers(db, secret)
        status, reply_headers, raw = self._request(
            "POST", f"/json/2/{model}/{method}", body=body, headers=headers
        )
        return self._result(status, reply_headers, raw, db)

    # -- version (no login, no server log line) --------------------------------
    def _probe_headers(self) -> dict[str, str]:
        return {"Authorization": self._basic} if self._basic else {}

    def version(self) -> dict[str, Any]:
        """``common.version()`` keys without a deprecated endpoint.

        1. ``POST /web/webclient/version_info``: the web client's own
           ``auth='none'`` route, 10.0 to master;
        2. ``GET /json/version``: 19.0+.
        """
        timeout = min(self.timeout, PROBE_TIMEOUT)
        problems = []
        status, headers, raw = self._request(
            "POST", "/web/webclient/version_info",
            body={"jsonrpc": "2.0", "method": "call", "params": {}, "id": 1},
            headers=self._probe_headers(), timeout=timeout,
        )
        if status == 429:
            raise RateLimited("version probe: HTTP 429 Too Many Requests",
                              retry_after=parse_retry_after(headers.get("Retry-After")))
        data, _ok = _json(raw)
        result = data.get("result") if isinstance(data, dict) else None
        if status == 200 and isinstance(result, dict) and result.get("server_version"):
            return dict(result)
        problems.append(f"/web/webclient/version_info: HTTP {status}")

        status, headers, raw = self._request(
            "GET", "/json/version", headers=self._probe_headers(), timeout=timeout
        )
        if status == 429:
            raise RateLimited("version probe: HTTP 429 Too Many Requests",
                              retry_after=parse_retry_after(headers.get("Retry-After")))
        data, _ok = _json(raw)
        payload = version_from_json_version(data) if status == 200 else None
        if payload is not None:
            return payload
        problems.append(f"/json/version: HTTP {status}")
        raise Json2Unavailable("json2 version probes failed (" + "; ".join(problems) + ")")

    # -- sign-in ---------------------------------------------------------------
    def authenticate(self, db: str, login: str, secret: str) -> int:
        """The key names its user: ``context_get`` gives the uid, then the login
        must be ODOO_LOGIN, which keeps "ODOO_LOGIN owns the credential" true."""
        try:
            context = self._call(db, secret, "res.users", "context_get", {})
            uid = context.get("uid") if isinstance(context, dict) else None
            if isinstance(uid, bool) or not isinstance(uid, int) or uid <= 0:
                raise AuthError("JSON-2 sign-in returned no user for this API key")
            rows = self._call(db, secret, "res.users", "read",
                              {"ids": [uid], "fields": ["login"]})
        except OdooFault as exc:
            raise AuthError(f"JSON-2 sign-in failed: {exc}") from exc
        owner = rows[0].get("login") if isinstance(rows, list) and rows and isinstance(
            rows[0], dict) else None
        if not isinstance(owner, str) or owner.casefold() != (login or "").casefold():
            raise AuthError(
                "the API key belongs to another Odoo user than ODOO_LOGIN: set ODOO_LOGIN "
                "to the login of the key's owner, or create a key while signed in as "
                "ODOO_LOGIN"
            )
        return uid

    # -- ORM calls -------------------------------------------------------------
    def execute_kw(
        self,
        db: str,
        uid: int,
        secret: str,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
        ids: Any = None,
    ) -> Any:
        check_names(model, method)
        key = (db, model, method)

        def introspect(m: str, name: str) -> Signature | None:
            return self.doc_signature(db, secret, m, name)

        used: list[Signature] = []
        body = to_named(model, method, args, kwargs, self.series, ids=ids,
                        introspect=introspect, signature=self._learned.get(key), used=used)
        try:
            result = self._call(db, secret, model, method, body)
        except Json2SignatureMismatch as exc:
            named_by_plugin = [name for name in body if name not in ("ids", "context")
                               and name not in (kwargs or {})]
            if not named_by_plugin:
                # The caller chose the names: report it, there is nothing to correct.
                raise OdooFault(
                    f"{exc} - JSON-2 checks the argument names against the method's "
                    "signature on this model; check the names in kwargs "
                    "(odoo_api_catalog lists them)"
                ) from None
            fixed = self._corrected(db, secret, model, method, used[0], named_by_plugin, exc)
            if fixed is None:
                raise Json2SignatureMismatch(
                    f"{exc} - the parameter names the plugin gave to the positional args of "
                    f"{model}.{method} do not match this model's signature; pass them by "
                    "name in kwargs (and record ids in ids)",
                    missing=exc.missing,
                ) from None
            log.info("JSON-2: %s.%s takes (%s); retrying with those names",
                     model, method, ", ".join(fixed.params))
            body = to_named(model, method, args, kwargs, self.series, ids=ids, signature=fixed)
            result = self._call(db, secret, model, method, body)  # a second 422 propagates
            self._learned[key] = fixed
        if (method == "create" and isinstance(body.get("vals_list"), dict)
                and isinstance(result, list) and len(result) == 1):
            return result[0]  # execute_kw returns the id for a single dict
        return result

    def _corrected(self, db: str, secret: str, model: str, method: str, used: Signature,
                   named_by_plugin: list[str],
                   exc: Json2SignatureMismatch) -> Signature | None:
        """The real signature after a bind error, or ``None`` when it cannot be known."""
        doc = self.doc_signature(db, secret, model, method)
        if doc is not None and doc.params != used.params:
            return doc
        if exc.missing and len(named_by_plugin) == 1 and exc.missing not in used.params:
            params = list(used.params)
            params[params.index(named_by_plugin[0])] = exc.missing
            return Signature(used.model_level, tuple(params), used.readonly)
        return None

    # -- /doc-bearer -------------------------------------------------------------
    def api_doc(self, db: str, secret: str, model: str, *,
                revalidate: bool = True) -> dict[str, Any] | None:
        """``GET /doc-bearer/<model>.json`` (19.0+), or ``None`` when not available.

        The page needs the ``api_doc.group_allow_doc`` group (admins), so another
        key gets 403 and ``None``. Cached per (db, model) and revalidated with the
        server's ``ETag``; ``revalidate=False`` answers from the cache when it can.
        """
        check_names(model, "doc")
        key = (db, model)
        cached = self._docs.get(key)
        if cached is not None and not revalidate:
            return cached[1]
        headers = self._auth_headers(db, secret)
        if cached is not None and cached[0]:
            headers["If-None-Match"] = cached[0]
        status, reply_headers, raw = self._request(
            "GET", f"/doc-bearer/{model}.json", headers=headers
        )
        if status == 304 and cached is not None:
            return cached[1]
        ctype = (reply_headers.get("Content-Type") or "").lower()
        data, is_json = _json(raw) if "json" in ctype else (None, False)
        not_allowed = status == 403 and is_json and _is_odoo_error(data)
        missing = status == 404 and b"No database is selected" not in raw
        if not_allowed or missing:
            self._docs[key] = (None, None)  # not an admin key, no api_doc, or no such model
            return None
        payload = self._result(status, reply_headers, raw, db)
        if not isinstance(payload, dict):
            raise TransportError("json2: /doc-bearer did not answer a JSON object")
        self._docs[key] = (reply_headers.get("ETag"), payload)
        return payload

    def doc_signature(self, db: str, secret: str, model: str, method: str) -> Signature | None:
        """A method's signature from ``/doc-bearer``, for positional args outside
        the built-in table; ``None`` when the page is not available."""
        if self.series is not None and self.series < DOC_BEARER_SINCE:
            return None
        try:
            doc = self.api_doc(db, secret, model, revalidate=False)
        except (OdooFault, Json2Unavailable):
            return None
        methods = doc.get("methods") if isinstance(doc, dict) else None
        meta = methods.get(method) if isinstance(methods, dict) else None
        if not isinstance(meta, dict):
            return None
        params = meta.get("parameters") if isinstance(meta.get("parameters"), dict) else {}
        names = tuple(
            name for name, spec in params.items()
            if not (isinstance(spec, dict) and spec.get("kind") in _NOT_NAMED)
        )
        api = meta.get("api") or ()
        return Signature("model" in api, names, readonly="readonly" in api)

    def close(self) -> None:
        """Nothing to release: each call opens and closes its own connection."""
