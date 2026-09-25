# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Environment-first configuration. Secrets are never logged."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

TRANSPORT_CHOICES = ("auto", "jsonrpc", "xmlrpc")

# A plugin host that leaves a manifest reference unresolved (e.g. an unset
# optional ``${user_config.odoo_password}``) would otherwise hand the literal
# placeholder to the server, which would then be used as a URL or credential.
_UNRESOLVED_PLACEHOLDER = re.compile(r"^\$\{[^}]*\}$")


def _env(name: str) -> str:
    """Read an env var verbatim, treating unresolved ``${...}`` values as unset.

    The value is not stripped: credentials may legitimately start or end with
    whitespace, so only the placeholder check uses a stripped copy.
    """
    raw = os.environ.get(name) or ""
    if _UNRESOLVED_PLACEHOLDER.match(raw.strip()):
        return ""
    return raw


def _get_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _get_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    """Server-wide settings, loaded from the process environment."""

    url: str = ""
    db: str = ""
    login: str = ""
    password: str = ""
    api_key: str = ""
    transport_pref: str = "auto"
    timeout: int = 30
    multitenant: bool = False
    cache_ttl: int = 300
    metrics: bool = False
    metrics_port: int = 8085
    otel_endpoint: str = ""
    # Read-only kill-switch for demos and least-privilege runs: when true the
    # server refuses every non-read-only tool before touching Odoo.
    readonly: bool = False
    # Optional bearer expected on the HTTP transport (multi-tenant deployments).
    http_bearer: str = ""

    extra: dict = field(default_factory=dict)

    @property
    def secret(self) -> str:
        """Preferred credential: api_key beats password when present."""
        return self.api_key or self.password

    @classmethod
    def from_env(cls) -> Settings:
        pref = (_env("ODOO_TRANSPORT_PREF").strip() or "auto").lower()
        if pref not in TRANSPORT_CHOICES:
            pref = "auto"
        return cls(
            url=_env("ODOO_URL").rstrip("/"),
            db=_env("ODOO_DB"),
            login=_env("ODOO_LOGIN") or _env("ODOO_USER"),
            password=_env("ODOO_PASSWORD"),
            api_key=_env("ODOO_API_KEY"),
            transport_pref=pref,
            timeout=_get_int("ODOO_TIMEOUT", 30),
            multitenant=_get_bool("ODOO_MULTITENANT", False),
            cache_ttl=_get_int("ODOO_CACHE_TTL", 300),
            metrics=_get_bool("ODOO_METRICS", False),
            metrics_port=_get_int("ODOO_METRICS_PORT", 8085),
            otel_endpoint=_env("ODOO_OTEL_ENDPOINT"),
            readonly=_get_bool("ODOO_READONLY", False),
            http_bearer=_env("ODOO_HTTP_BEARER"),
        )

    def redacted(self) -> dict:
        """A log-safe view: no secrets."""
        return {
            "url": self.url,
            "db": self.db,
            "login": self.login,
            "transport_pref": self.transport_pref,
            "timeout": self.timeout,
            "multitenant": self.multitenant,
            "cache_ttl": self.cache_ttl,
            "metrics": self.metrics,
            "otel": bool(self.otel_endpoint),
            "readonly": self.readonly,
            "has_secret": bool(self.secret),
        }

    def __repr__(self) -> str:
        # Security: never expose password/api_key via repr() or logging.
        return f"Settings({self.redacted()!r})"

    __str__ = __repr__
