# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Connection manager mapping a tenant fingerprint to an OdooSession.

Two modes:
  * single-tenant (stdio, default): one session built from environment config.
  * multi-tenant (HTTP): per-request ``X-Odoo-Url/Db/Login`` + ``Bearer`` secret
    resolve to (and cache) a session. Secrets are held in memory only, never
    persisted or logged.
"""

from __future__ import annotations

import threading

from .config import Settings
from .errors import ConfigError
from .session import Credentials, OdooSession


class ConnectionManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sessions: dict[str, OdooSession] = {}
        self._lock = threading.Lock()

    def _build(self, creds: Credentials) -> OdooSession:
        return OdooSession(
            creds,
            timeout=self.settings.timeout,
            transport_pref=self.settings.transport_pref,
            cache_ttl=self.settings.cache_ttl,
        )

    def get(self, creds: Credentials) -> OdooSession:
        key = creds.fingerprint()
        with self._lock:
            sess = self._sessions.get(key)
            if sess is None:
                sess = self._build(creds)
                self._sessions[key] = sess
            return sess

    def default(self) -> OdooSession:
        """Single-tenant session from environment settings."""
        s = self.settings
        if not (s.url and s.db and s.login and s.secret):
            raise ConfigError(
                "single-tenant mode needs ODOO_URL, ODOO_DB, ODOO_LOGIN and "
                "ODOO_API_KEY or ODOO_PASSWORD"
            )
        creds = Credentials(url=s.url, db=s.db, login=s.login, secret=s.secret)
        return self.get(creds)

    def from_headers(self, headers: dict[str, str]) -> OdooSession:
        """Resolve a session from HTTP headers (multi-tenant mode)."""
        lower = {k.lower(): v for k, v in headers.items()}
        url = (lower.get("x-odoo-url") or self.settings.url).rstrip("/")
        db = lower.get("x-odoo-db") or self.settings.db
        login = lower.get("x-odoo-login") or self.settings.login
        auth = lower.get("authorization", "")
        secret = auth[7:].strip() if auth.lower().startswith("bearer ") else self.settings.secret
        if not (url and db and login and secret):
            raise ConfigError(
                "multi-tenant request missing X-Odoo-Url/Db/Login or Bearer secret"
            )
        return self.get(Credentials(url=url, db=db, login=login, secret=secret))

    def connections(self) -> list[dict[str, str]]:
        with self._lock:
            return [
                {"url": s.creds.url, "db": s.creds.db, "login": s.creds.login}
                for s in self._sessions.values()
            ]
