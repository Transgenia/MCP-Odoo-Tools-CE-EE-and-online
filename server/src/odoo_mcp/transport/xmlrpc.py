# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""XML-RPC transport (``/xmlrpc/2/common`` and ``/xmlrpc/2/object``).

XML-RPC is the most broadly compatible interface across Odoo 10-19 and works
with both passwords and API keys on every supported version.
"""

from __future__ import annotations

import xmlrpc.client
from typing import Any

from ..errors import AuthError, OdooFault, TransportError


class XmlRpcTransport:
    name = "xmlrpc"

    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # allow_none so Odoo methods returning None do not blow up marshalling
        self._common = xmlrpc.client.ServerProxy(
            f"{self.base_url}/xmlrpc/2/common", allow_none=True
        )
        self._object = xmlrpc.client.ServerProxy(
            f"{self.base_url}/xmlrpc/2/object", allow_none=True
        )

    def version(self) -> dict[str, Any]:
        try:
            return dict(self._common.version())
        except (xmlrpc.client.Fault, OSError) as exc:  # pragma: no cover - network
            raise TransportError(f"xmlrpc version() failed: {exc}") from exc

    def authenticate(self, db: str, login: str, secret: str) -> int:
        try:
            uid = self._common.authenticate(db, login, secret, {})
        except xmlrpc.client.Fault as exc:
            raise AuthError(f"xmlrpc authenticate failed: {exc.faultString}") from exc
        except OSError as exc:  # pragma: no cover - network
            raise TransportError(f"xmlrpc authenticate transport error: {exc}") from exc
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
        except OSError as exc:  # pragma: no cover - network
            raise TransportError(f"xmlrpc execute_kw transport error: {exc}") from exc
