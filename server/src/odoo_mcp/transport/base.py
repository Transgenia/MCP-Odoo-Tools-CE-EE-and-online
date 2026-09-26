# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Transport abstraction over Odoo's RPC interfaces."""

from __future__ import annotations

import ssl
from typing import Any, Protocol, runtime_checkable


def tls_context() -> ssl.SSLContext:
    """Certificate-verifying TLS context shared by both transports.

    Always trusts the system store (and honours ``SSL_CERT_FILE``). When the
    optional ``certifi`` package happens to be installed its CA bundle is added
    too, which helps Python builds that ship without a usable trust store.
    Nothing is installed or downloaded for this.
    """
    ctx = ssl.create_default_context()
    try:
        import certifi  # type: ignore[import-not-found]
    except ImportError:
        return ctx
    try:
        ctx.load_verify_locations(cafile=certifi.where())
    except (OSError, ssl.SSLError):  # pragma: no cover - broken certifi install
        pass
    return ctx


@runtime_checkable
class Transport(Protocol):
    """A transport talks to a single Odoo base URL.

    Implementations wrap either XML-RPC (`/xmlrpc/2/*`) or JSON-RPC
    (`/jsonrpc`). All methods are synchronous; the MCP layer runs them on a
    worker thread so the stdio reader stays responsive.
    """

    name: str

    def version(self) -> dict[str, Any]:
        """Return the raw ``common.version()`` payload."""
        ...

    def authenticate(self, db: str, login: str, secret: str) -> int:
        """Return the numeric uid, or raise :class:`AuthError`."""
        ...

    def execute_kw(
        self,
        db: str,
        uid: int,
        secret: str,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Invoke ``model.method(*args, **kwargs)`` via ``object.execute_kw``."""
        ...
