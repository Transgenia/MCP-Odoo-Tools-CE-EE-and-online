# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Connection manager mapping a credential's session key to an OdooSession.

The stdio server is single-tenant: one session built from environment config.
Sessions are cached by ``Credentials.session_key()`` (url, db, login and a
per-process HMAC of the secret), so another secret never reuses a session.
Secrets are held in memory only, never persisted or logged. A remote HTTP mode
will resolve sessions from an authenticated identity, never from client-chosen
headers; it needs its own design and is not built.
"""

from __future__ import annotations

import threading

from .config import Settings, _without_userinfo
from .errors import ConfigError
from .session import Credentials, OdooSession


class ConnectionManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sessions: dict[str, OdooSession] = {}
        self._tool_calls: dict[str, int] = {}
        self._lock = threading.Lock()

    def _build(self, creds: Credentials) -> OdooSession:
        return OdooSession(
            creds,
            timeout=self.settings.timeout,
            transport_pref=self.settings.transport_pref,
            cache_ttl=self.settings.cache_ttl,
        )

    def get(self, creds: Credentials) -> OdooSession:
        key = creds.session_key()
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
        creds = Credentials(url=s.url, db=s.db, login=s.login, secret=s.secret,
                            secret_kind="api_key" if s.api_key else "password")
        return self.get(creds)

    def connections(self) -> list[dict[str, str]]:
        # The userinfo of ODOO_URL (basic auth in front of Odoo) is a credential: the
        # transport, CredsView, Settings.redacted() and the audit all strip it, so the
        # odoo_connections tool must not hand it back either (it is read-only and
        # visible under every profile, readonly included).
        with self._lock:
            return [
                {"url": _without_userinfo(s.creds.url), "db": s.creds.db, "login": s.creds.login}
                for s in self._sessions.values()
            ]

    def record_tool_call(self, name: str) -> None:
        """In-memory per-tool invocation counter (feeds the opt-in preview only)."""
        with self._lock:
            self._tool_calls[name] = self._tool_calls.get(name, 0) + 1

    def tool_calls_snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._tool_calls)
