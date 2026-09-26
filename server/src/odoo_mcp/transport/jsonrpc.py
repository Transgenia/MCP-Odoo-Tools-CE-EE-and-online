# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""JSON-RPC transport (``/jsonrpc``).

Faster and friendlier to modern tooling, but note the well-known caveat this
server guards against: on Odoo 17+ the ``/jsonrpc`` endpoint rejects API keys
for ``execute_kw`` (only passwords work there). The FallbackTransport detects
that and transparently retries over XML-RPC.
"""

from __future__ import annotations

import itertools
import json
import urllib.error
import urllib.request
from typing import Any

from ..errors import AuthError, OdooFault, TransportError
from .base import tls_context

# Raised so FallbackTransport knows this specific failure is recoverable by
# switching transports rather than a genuine application error.
API_KEY_MARKERS = (
    "api key",
    "api-key",
    "apikey",
    "expected singleton",  # some versions surface odd faults for key auth
)


class ApiKeyRejected(TransportError):
    """`/jsonrpc` refused an API key; caller should fall back to XML-RPC."""


class JsonRpcTransport:
    name = "jsonrpc"

    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._ids = itertools.count(1)
        self._tls = tls_context()

    def _call(self, service: str, method: str, args: list[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": next(self._ids),
        }
        request = urllib.request.Request(
            f"{self.base_url}/jsonrpc",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            # HTTP errors (4xx/5xx) raise HTTPError, a URLError subclass.
            with urllib.request.urlopen(  # URL is the configured Odoo base URL
                request, timeout=self.timeout, context=self._tls
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise TransportError(f"jsonrpc transport error: {exc}") from exc
        if not isinstance(data, dict):
            raise TransportError("jsonrpc transport error: response is not a JSON object")

        if "error" in data:
            err = data["error"]
            message = _flatten_error(err)
            if any(marker in message.lower() for marker in API_KEY_MARKERS):
                raise ApiKeyRejected(message)
            raise OdooFault(message)
        return data.get("result")

    def version(self) -> dict[str, Any]:
        return dict(self._call("common", "version", []))

    def authenticate(self, db: str, login: str, secret: str) -> int:
        try:
            uid = self._call("common", "authenticate", [db, login, secret, {}])
        except OdooFault as exc:
            raise AuthError(str(exc)) from exc
        if not uid:
            raise AuthError("jsonrpc authenticate returned no uid (bad credentials/db)")
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
        return self._call(
            "object", "execute_kw", [db, uid, secret, model, method, args, kwargs or {}]
        )

    def close(self) -> None:
        """Nothing to release: each call opens and closes its own connection."""


def _flatten_error(err: Any) -> str:
    if isinstance(err, dict):
        parts = [str(err.get("message", "")).strip()]
        data = err.get("data")
        if isinstance(data, dict):
            dbg = data.get("message") or data.get("debug") or ""
            if dbg:
                parts.append(str(dbg).strip().splitlines()[-1])
        return " | ".join(p for p in parts if p) or "jsonrpc error"
    return str(err)
