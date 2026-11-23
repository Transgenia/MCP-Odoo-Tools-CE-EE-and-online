# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Per-tenant Odoo session: auth, version/edition facts, schema-cached reads."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
from dataclasses import dataclass, field
from typing import Any

from .cache import SchemaCache
from .compat import EnvFacts, probe
from .errors import ConfigError
from .transport.fallback import FallbackTransport

log = logging.getLogger(__name__)

# Per process, never persisted or logged: it keys the HMAC of the secret in
# Credentials.session_key(), so a key from one process means nothing in another.
_SESSION_SALT = secrets.token_bytes(32)

# Without a "lang" in the context Odoo answers translatable fields in en_US, the
# language of the source text, whatever the user's own language. The session adds
# the default language (ODOO_DEFAULT_LANG) to these read methods only; writes and
# every other method are sent as the caller wrote them.
LANG_READ_METHODS = frozenset(
    {
        "read", "search_read", "search", "search_count", "name_search", "name_get",
        "web_read", "web_search_read", "web_name_search", "read_group",
        "formatted_read_group", "web_read_group", "export_data", "fields_get",
        "search_fetch", "fetch",
    }
)
# Odoo 10 to 12 also read a context passed positionally; a second one by name
# would reach the method as an unexpected keyword. From 13 on only kwargs count.
_KWARGS_CONTEXT_ONLY_SINCE = 13


@dataclass
class Credentials:
    url: str
    db: str
    login: str
    # kept out of repr() so a traceback, log line or debugger never shows it
    secret: str = field(repr=False)
    # "api_key" (ODOO_API_KEY) or "password": JSON-2 accepts API keys only, so
    # the transport policy needs to know. Not part of the fingerprint.
    secret_kind: str = field(default="password", repr=False)

    def fingerprint(self) -> str:
        # login+db+url identify the tenant; the secret is never part of the key
        return f"{self.url}|{self.db}|{self.login}"

    def session_key(self) -> str:
        """The key a session is cached under: the fingerprint, the credential
        kind and a per-process HMAC over the whole connection identity and the
        secret. The same url, db and login with another secret is another
        session, so a caller who knows them but not the secret never reuses an
        authenticated one. The secret itself is never part of the key.

        The HMAC covers url, db, login and secret_kind as well as the secret, each
        length-framed, so two credentials whose ``url|db|login`` strings collide
        only because a component contains ``|`` (e.g. ``"host|db1"`` + ``"x"`` vs
        ``"host"`` + ``"db1|x"``) still key apart; ``fingerprint()`` is unchanged,
        so SchemaCache and the transport tests keep using it."""
        parts = (self.url, self.db, self.login, self.secret_kind, self.secret)
        material = "".join(f"{len(part)}\x00{part}\x00" for part in parts)
        tag = hmac.new(_SESSION_SALT, material.encode("utf-8", "surrogatepass"),
                       hashlib.sha256).hexdigest()[:32]
        return f"{self.fingerprint()}|{self.secret_kind}|{tag}"


class OdooSession:
    """A single authenticated connection to one Odoo instance."""

    def __init__(self, creds: Credentials, *, timeout: int = 30, transport_pref: str = "auto",
                 cache_ttl: int = 300, default_lang: str = "user") -> None:
        if not (creds.url and creds.db and creds.login and creds.secret):
            raise ConfigError("incomplete Odoo credentials (need url, db, login, secret)")
        self.creds = creds
        self.transport = FallbackTransport(
            creds.url, timeout=timeout, pref=transport_pref, secret_kind=creds.secret_kind
        )
        self.schema = SchemaCache(ttl=cache_ttl)
        self._uid: int | None = None
        self._facts: EnvFacts | None = None
        # Reentrant: facts() holds the lock while probe() may call
        # module_installed() -> execute() -> uid, which takes it again.
        self._lock = threading.RLock()
        # "user", "off" or a language code (config.default_lang_setting); the
        # language itself is known once the sign-in resolved it.
        self.default_lang_mode = default_lang
        self._lang: str | None = None

    # -- auth ---------------------------------------------------------------
    @property
    def uid(self) -> int:
        if self._uid is None:
            with self._lock:
                if self._uid is None:
                    uid = self.transport.authenticate(
                        self.creds.db, self.creds.login, self.creds.secret
                    )
                    self._lang = self._resolve_lang(uid)
                    self._uid = uid
        return self._uid

    @property
    def default_lang(self) -> str | None:
        """The language reads get when the caller sets none, once signed in."""
        return self._lang

    def _resolve_lang(self, uid: int) -> str | None:
        """The default read language, once per sign-in. Never raises: on any
        error reads keep Odoo's own default (en_US), as before."""
        mode = self.default_lang_mode
        if mode == "off":
            return None
        db, secret = self.creds.db, self.creds.secret
        try:
            if mode == "user":
                context = getattr(self.transport, "signin_context", None)
                if not isinstance(context, dict) or "lang" not in context:
                    context = self.transport.execute_kw(
                        db, uid, secret, "res.users", "context_get", [], {})
                lang = context.get("lang") if isinstance(context, dict) else None
                return lang if isinstance(lang, str) and lang else None
            active = self.transport.execute_kw(
                db, uid, secret, "res.lang", "search_count", [[["code", "=", mode]]], {})
        except Exception as exc:  # a default must never break the sign-in
            log.warning("default language not resolved, reads stay in en_US: %s", exc)
            return None
        if not active:
            log.warning("ODOO_DEFAULT_LANG=%s is not an active language in this Odoo; "
                        "reads stay in en_US", mode)
            return None
        return mode

    def _with_default_lang(self, method: str, args: list[Any],
                           kwargs: dict[str, Any]) -> dict[str, Any]:
        """``kwargs`` with the default language in its context, for a read whose
        caller set no ``lang`` (an explicit one, ``False`` included, wins). The
        caller's dict is never changed."""
        lang = self._lang
        # en_US is what Odoo reads without a lang: nothing to add, nothing changes.
        if not lang or lang == "en_US" or method not in LANG_READ_METHODS:
            return kwargs
        context = kwargs.get("context")
        if context is None:
            context = {}
        elif not isinstance(context, dict) or "lang" in context:
            return kwargs
        facts = self._facts
        if any(isinstance(arg, dict) for arg in args) and (
                facts is None or facts.version < _KWARGS_CONTEXT_ONLY_SINCE):
            return kwargs  # may be a positional context (Odoo 10 to 12): leave it alone
        return {**kwargs, "context": {**context, "lang": lang}}

    @property
    def authenticated(self) -> bool:
        """Whether the sign-in succeeded. Never contacts Odoo (local diagnostics)."""
        return self._uid is not None

    def known_facts(self) -> EnvFacts | None:
        """The version/edition/deployment facts once probed, else ``None``. Never
        contacts Odoo (local diagnostics)."""
        return self._facts

    # -- core ORM call ------------------------------------------------------
    def execute(self, model: str, method: str, args: list[Any] | None = None,
                kwargs: dict[str, Any] | None = None, *, ids: list[int] | None = None,
                transports: tuple[str, ...] | None = None) -> Any:
        """``model.method(*args, **kwargs)``; ``ids`` are the records of a record
        method when given apart from ``args`` (``odoo_execute``): JSON-2 sends
        them as ``"ids"``, the legacy transports as the first positional arg.
        ``transports`` limits the call to those transport kinds (e.g.
        ``("json2", "jsonrpc")``); it is never replayed over another one.
        A read without ``lang`` in its context gets the default language
        (``ODOO_DEFAULT_LANG``, the Odoo user's own by default)."""
        extra: dict[str, Any] = {}
        if ids is not None:
            extra["ids"] = ids
        if transports is not None:
            extra["transports"] = tuple(transports)
        uid = self.uid  # signs in first, which resolves the default language
        args = args or []
        kwargs = self._with_default_lang(method, args, kwargs or {})
        return self.transport.execute_kw(
            self.creds.db, uid, self.creds.secret, model, method, args, kwargs, **extra,
        )

    def version_info(self) -> dict[str, Any]:
        return self.transport.version()

    def api_doc(self, model: str) -> dict[str, Any] | None:
        """Odoo's ``/doc-bearer/<model>.json`` (19.0+, an administrator's API
        key), or ``None`` where it is not available to this credential."""
        fetch = getattr(self.transport, "api_doc", None)
        if fetch is None:
            return None
        return fetch(self.creds.db, self.creds.secret, model)

    # -- environment facts (version/edition/deployment), cached -------------
    def facts(self) -> EnvFacts:
        if self._facts is None:
            with self._lock:
                if self._facts is None:
                    vinfo = self.version_info()
                    self._facts = probe(self.creds.url, vinfo, self.module_installed)
        return self._facts

    def module_installed(self, name: str) -> bool:
        def _compute() -> bool:
            count = self.execute(
                "ir.module.module",
                "search_count",
                [[["name", "=", name], ["state", "=", "installed"]]],
            )
            return bool(count)

        key = (self.creds.fingerprint(), "module", name)
        return bool(self.schema.get_or_compute(key, _compute))

    # -- schema helpers (cached) -------------------------------------------
    def fields_get(self, model: str, attributes: list[str] | None = None) -> dict[str, Any]:
        attrs = attributes or ["string", "type", "required", "readonly", "relation"]
        version = self.facts().version
        fingerprint = self.creds.fingerprint()
        # The generation makes post-write invalidations race-safe: a fill that
        # started before odoo_add_field lands under the old generation key.
        gen = self.schema.generation(fingerprint, model)

        def _compute() -> dict[str, Any]:
            return self.execute(model, "fields_get", [], {"attributes": attrs})

        key = (fingerprint, "fields", model, version, gen, tuple(attrs))
        return self.schema.get_or_compute(key, _compute)

    def name_get(self, model: str, ids: list[int]) -> list[list[Any]]:
        """``[[id, display name], ...]`` on every version.

        The ``name_get`` method is gone in Odoo 18 (deprecated in 17), while the
        ``display_name`` field reads the same name on 10-19. No caching: the id
        sets are arbitrary.
        """
        rows = self.execute(model, "read", [ids], {"fields": ["display_name"]})
        return [[row["id"], row["display_name"]] for row in rows]

    def invalidate_fields(self, model: str) -> None:
        """Drop cached ``fields_get`` entries for ``model`` (best-effort)."""
        try:
            self.schema.invalidate_fields(self.creds.fingerprint(), model)
        except Exception:  # noqa: S110 — cache invalidation must not fail writes
            pass
