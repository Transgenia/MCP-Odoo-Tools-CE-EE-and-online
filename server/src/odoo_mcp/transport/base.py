# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Transport abstraction over Odoo's RPC interfaces."""

from __future__ import annotations

import os
import ssl
from typing import Any, Protocol, runtime_checkable

# Well-known CA bundles maintained by the OS (macOS, Debian/Ubuntu, RHEL/Fedora).
_OS_CA_BUNDLES = (
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
)


def tls_context() -> ssl.SSLContext:
    """Certificate-verifying TLS context shared by both transports.

    Always trusts the interpreter's default store (and honours
    ``SSL_CERT_FILE``). Some Python builds ship with no CA file of their own
    (python.org macOS installers before "Install Certificates"); for those the
    OS bundle is loaded instead. The optional ``certifi`` package is added when
    it happens to be installed. Nothing is installed or downloaded for this.
    """
    ctx = ssl.create_default_context()
    if not os.environ.get("SSL_CERT_FILE") and ssl.get_default_verify_paths().cafile is None:
        for bundle in _OS_CA_BUNDLES:
            if os.path.isfile(bundle):
                try:
                    ctx.load_verify_locations(cafile=bundle)
                    break
                except (OSError, ssl.SSLError):  # pragma: no cover - unreadable bundle
                    continue
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
