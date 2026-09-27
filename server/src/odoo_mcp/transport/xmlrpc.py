# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""XML-RPC transport (``/xmlrpc/2/common`` and ``/xmlrpc/2/object``).

XML-RPC is the most broadly compatible interface across Odoo 10-19 and works
with both passwords and API keys on every supported version.
"""

from __future__ import annotations

import http.client
import xml.parsers.expat
import xmlrpc.client
from typing import Any

from ..errors import AuthError, OdooFault, TransportError
from .base import tls_context


class _TimeoutTransport(xmlrpc.client.Transport):
    """Plain-HTTP transport whose connections honour the configured timeout."""

    def __init__(self, timeout: float) -> None:
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host: Any) -> Any:
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    """HTTPS transport: certificate-verifying context plus the timeout."""

    def __init__(self, timeout: float) -> None:
        super().__init__(context=tls_context())
        self._timeout = timeout

    def make_connection(self, host: Any) -> Any:
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


def _transport_error(what: str, exc: BaseException) -> TransportError:
    """Describe a failure without echoing the URL (it may carry user:pass@)."""
    if isinstance(exc, xmlrpc.client.ProtocolError):
        detail = f"HTTP {exc.errcode} {exc.errmsg}"
    else:
        detail = f"{type(exc).__name__}: {exc}"
    return TransportError(f"xmlrpc {what} failed: {detail}")


# Everything below the XML-RPC fault level that means "no usable reply".
_TRANSPORT_FAILURES = (
    OSError,
    http.client.HTTPException,
    xmlrpc.client.ProtocolError,
    xmlrpc.client.ResponseError,
    xml.parsers.expat.ExpatError,
)


class XmlRpcTransport:
    name = "xmlrpc"

    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # allow_none so Odoo methods returning None do not blow up marshalling
        self._common = xmlrpc.client.ServerProxy(
            f"{self.base_url}/xmlrpc/2/common", transport=self._transport(), allow_none=True
        )
        self._object = xmlrpc.client.ServerProxy(
            f"{self.base_url}/xmlrpc/2/object", transport=self._transport(), allow_none=True
        )

    def _transport(self) -> xmlrpc.client.Transport:
        if self.base_url.lower().startswith("https://"):
            return _TimeoutSafeTransport(self.timeout)
        return _TimeoutTransport(self.timeout)

    def version(self) -> dict[str, Any]:
        try:
            return dict(self._common.version())
        except xmlrpc.client.Fault as exc:  # pragma: no cover - network
            raise TransportError(f"xmlrpc version() failed: {exc.faultString}") from None
        except _TRANSPORT_FAILURES as exc:
            raise _transport_error("version()", exc) from None

    def authenticate(self, db: str, login: str, secret: str) -> int:
        try:
            uid = self._common.authenticate(db, login, secret, {})
        except xmlrpc.client.Fault as exc:
            raise AuthError(f"xmlrpc authenticate failed: {exc.faultString}") from exc
        except _TRANSPORT_FAILURES as exc:
            raise _transport_error("authenticate", exc) from None
        if not uid:
            raise AuthError("xmlrpc authenticate returned no uid (bad credentials/db)")
        return int(uid)

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
        try:
            return self._object.execute_kw(db, uid, secret, model, method, args, kwargs or {})
        except xmlrpc.client.Fault as exc:
            raise OdooFault(exc.faultString.strip()) from exc
        except _TRANSPORT_FAILURES as exc:
            raise _transport_error("execute_kw", exc) from None
