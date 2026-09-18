# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Per-tenant Odoo session: auth, version/edition facts, schema-cached reads."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from .cache import SchemaCache
from .compat import EnvFacts, probe
from .errors import ConfigError
from .transport.fallback import FallbackTransport


@dataclass
class Credentials:
    url: str
    db: str
    login: str
    secret: str

    def fingerprint(self) -> str:
        # login+db+url identify the tenant; the secret is never part of the key
        return f"{self.url}|{self.db}|{self.login}"


class OdooSession:
    """A single authenticated connection to one Odoo instance."""

    def __init__(self, creds: Credentials, *, timeout: int = 30, transport_pref: str = "auto",
                 cache_ttl: int = 300) -> None:
        if not (creds.url and creds.db and creds.login and creds.secret):
            raise ConfigError("incomplete Odoo credentials (need url, db, login, secret)")
        self.creds = creds
        self.transport = FallbackTransport(creds.url, timeout=timeout, pref=transport_pref)
        self.schema = SchemaCache(ttl=cache_ttl)
        self._uid: int | None = None
        self._facts: EnvFacts | None = None
        self._lock = threading.Lock()

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

    # -- core ORM call ------------------------------------------------------
    def execute(self, model: str, method: str, args: list[Any] | None = None,
                kwargs: dict[str, Any] | None = None) -> Any:
        return self.transport.execute_kw(
            self.creds.db, self.uid, self.creds.secret, model, method, args or [], kwargs or {}
        )

    def version_info(self) -> dict[str, Any]:
        return self.transport.version()

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

        def _compute() -> dict[str, Any]:
            return self.execute(model, "fields_get", [], {"attributes": attrs})

        key = (self.creds.fingerprint(), "fields", model, version, tuple(attrs))
        return self.schema.get_or_compute(key, _compute)

    def name_get(self, model: str, ids: list[int]) -> list[list[Any]]:
        # name_get has no useful caching across arbitrary id sets; call directly
        return self.execute(model, "name_get", [ids])
