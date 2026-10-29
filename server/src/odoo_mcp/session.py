# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Per-tenant Odoo session: auth, version/edition facts, schema-cached reads."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass, field
from typing import Any

from .cache import SchemaCache
from .compat import EnvFacts, probe
from .errors import ConfigError
from .transport.fallback import FallbackTransport

# Per process, never persisted or logged: it keys the HMAC of the secret in
# Credentials.session_key(), so a key from one process means nothing in another.
_SESSION_SALT = secrets.token_bytes(32)


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
                 cache_ttl: int = 300) -> None:
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

    # -- auth ---------------------------------------------------------------
    @property
    def uid(self) -> int:
        if self._uid is None:
            with self._lock:
                if self._uid is None:
                    self._uid = self.transport.authenticate(
                        self.creds.db, self.creds.login, self.creds.secret
                    )
        return self._uid

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
        ``("json2", "jsonrpc")``); it is never replayed over another one."""
        extra: dict[str, Any] = {}
        if ids is not None:
            extra["ids"] = ids
        if transports is not None:
            extra["transports"] = tuple(transports)
        return self.transport.execute_kw(
            self.creds.db, self.uid, self.creds.secret, model, method, args or [],
            kwargs or {}, **extra,
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
