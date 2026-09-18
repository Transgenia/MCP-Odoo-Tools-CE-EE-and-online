# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Transport that prefers one interface and transparently falls back.

Preference:
  * ``auto``    -> try JSON-RPC first, fall back to XML-RPC on api-key rejection
                   or transport error.
  * ``jsonrpc`` -> JSON-RPC only.
  * ``xmlrpc``  -> XML-RPC only.

The api-key-on-/jsonrpc caveat (Odoo 17+) is the primary reason auto mode
exists; when it triggers we log a single warning and pin XML-RPC for the rest
of the transport's life so we don't pay the failed round-trip repeatedly.
"""

from __future__ import annotations

import logging
from typing import Any

from ..errors import TransportError
from .jsonrpc import ApiKeyRejected, JsonRpcTransport
from .xmlrpc import XmlRpcTransport

log = logging.getLogger("odoo_mcp.transport")


class FallbackTransport:
    name = "fallback"

    def __init__(self, base_url: str, timeout: int = 30, pref: str = "auto") -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.pref = pref
        self._xml: XmlRpcTransport | None = None
        self._json: JsonRpcTransport | None = None
        self._pinned: str | None = None  # once set, stop trying the other one
        self._warned_fallback = False

        if pref == "xmlrpc":
            self._pinned = "xmlrpc"
        elif pref == "jsonrpc":
            self._pinned = "jsonrpc"

    # -- lazy transport builders -------------------------------------------
    def _xmlrpc(self) -> XmlRpcTransport:
        if self._xml is None:
            self._xml = XmlRpcTransport(self.base_url, self.timeout)
        return self._xml

    def _jsonrpc(self) -> JsonRpcTransport:
        if self._json is None:
            self._json = JsonRpcTransport(self.base_url, self.timeout)
        return self._json

    def _order(self) -> list[str]:
        if self._pinned:
            return [self._pinned]
        # auto: json first, xml fallback
        return ["jsonrpc", "xmlrpc"]

    def _run(self, op: str, fn_name: str, *fn_args: Any) -> Any:
        last_exc: Exception | None = None
        for kind in self._order():
            transport = self._jsonrpc() if kind == "jsonrpc" else self._xmlrpc()
            try:
                result = getattr(transport, fn_name)(*fn_args)
                if self._pinned is None and kind == "jsonrpc":
                    # success on preferred transport; keep auto behavior
                    pass
                return result
            except ApiKeyRejected as exc:
                last_exc = exc
                self._pin_xmlrpc(reason=str(exc))
                continue
            except TransportError as exc:
                last_exc = exc
                # transport-level problem; try the next candidate if any
                continue
        assert last_exc is not None
        raise last_exc

    def _pin_xmlrpc(self, reason: str) -> None:
        if not self._warned_fallback:
            log.warning(
                "JSON-RPC rejected API key on %s; falling back to XML-RPC (%s)",
                self.base_url,
                reason,
            )
            self._warned_fallback = True
        self._pinned = "xmlrpc"

    # -- Transport protocol -------------------------------------------------
    def version(self) -> dict[str, Any]:
        return self._run("version", "version")

    def authenticate(self, db: str, login: str, secret: str) -> int:
        return self._run("authenticate", "authenticate", db, login, secret)

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
        return self._run(
            "execute_kw", "execute_kw", db, uid, secret, model, method, args, kwargs
        )

    @property
    def active(self) -> str:
        """Which transport will currently be used (for diagnostics)."""
        return self._pinned or "jsonrpc(auto)"
