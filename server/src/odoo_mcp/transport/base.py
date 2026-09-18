# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Transport abstraction over Odoo's RPC interfaces."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Transport(Protocol):
    """A transport talks to a single Odoo base URL.

    Implementations wrap either XML-RPC (`/xmlrpc/2/*`) or JSON-RPC
    (`/jsonrpc`). All methods are synchronous; the MCP layer runs them in a
    worker thread so the event loop stays responsive.
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
