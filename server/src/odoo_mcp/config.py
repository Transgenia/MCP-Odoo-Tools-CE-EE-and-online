# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Environment-first configuration. Secrets are never logged."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

TRANSPORT_CHOICES = ("auto", "jsonrpc", "xmlrpc")


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
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
        pref = (os.environ.get("ODOO_TRANSPORT_PREF") or "auto").strip().lower()
        if pref not in TRANSPORT_CHOICES:
            pref = "auto"
        return cls(
            url=(os.environ.get("ODOO_URL") or "").rstrip("/"),
            db=os.environ.get("ODOO_DB") or "",
            login=os.environ.get("ODOO_LOGIN") or os.environ.get("ODOO_USER") or "",
            password=os.environ.get("ODOO_PASSWORD") or "",
            api_key=os.environ.get("ODOO_API_KEY") or "",
            transport_pref=pref,
            timeout=_get_int("ODOO_TIMEOUT", 30),
            multitenant=_get_bool("ODOO_MULTITENANT", False),
            cache_ttl=_get_int("ODOO_CACHE_TTL", 300),
            metrics=_get_bool("ODOO_METRICS", False),
            metrics_port=_get_int("ODOO_METRICS_PORT", 8085),
            otel_endpoint=os.environ.get("ODOO_OTEL_ENDPOINT") or "",
            readonly=_get_bool("ODOO_READONLY", False),
            http_bearer=os.environ.get("ODOO_HTTP_BEARER") or "",
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
