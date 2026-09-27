# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Transport that prefers one interface and transparently falls back.

Preference:
  * ``auto``    -> try JSON-RPC first, fall back to XML-RPC on api-key rejection
                   or when JSON-RPC is unusable.
  * ``jsonrpc`` -> JSON-RPC only.
  * ``xmlrpc``  -> XML-RPC only.

The api-key-on-/jsonrpc caveat (Odoo 17+) is the primary reason auto mode
exists; when it triggers we log a single warning and pin XML-RPC for the rest
of the transport's life so we don't pay the failed round-trip repeatedly.

A call is replayed over XML-RPC only when that cannot run it twice: always for
``version``/``authenticate`` and for ``execute_kw`` of read methods (see
``READ_METHODS``), but for any other ``execute_kw`` only when the JSON-RPC
request certainly never reached Odoo (:class:`JsonRpcUnavailable`). After a
timeout, HTTP 5xx or a garbled reply a write may already have committed, so
the error is raised instead of risking a duplicate create/write. When JSON-RPC
fails and XML-RPC then answers, XML-RPC is pinned for the rest of the session.
"""

from __future__ import annotations

import logging
from typing import Any

from ..errors import TransportError
from .jsonrpc import ApiKeyRejected, JsonRpcTransport, JsonRpcUnavailable
from .xmlrpc import XmlRpcTransport

log = logging.getLogger("odoo_mcp.transport")

# ORM methods that only read, so replaying them over XML-RPC is always safe.
READ_METHODS = frozenset(
    {
        "search", "search_read", "search_count", "read", "read_group", "fields_get",
        "name_search", "name_get", "default_get", "check_access_rights", "has_group",
        "web_search_read", "web_read", "get_views", "fields_view_get", "export_data",
    }
)


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
        # execute_kw args: (db, uid, secret, model, method, ...)
        replayable = op != "execute_kw" or (len(fn_args) > 4 and fn_args[4] in READ_METHODS)
        for kind in self._order():
            transport = self._jsonrpc() if kind == "jsonrpc" else self._xmlrpc()
            try:
                result = getattr(transport, fn_name)(*fn_args)
                if kind == "xmlrpc" and last_exc is not None:
                    # JSON-RPC just failed where XML-RPC works: stop retrying it.
                    self._pin_xmlrpc(reason=f"JSON-RPC failed ({last_exc})")
                return result
            except ApiKeyRejected as exc:
                last_exc = exc
                self._pin_xmlrpc(reason=f"JSON-RPC rejected the API key ({exc})")
                continue
            except JsonRpcUnavailable as exc:
                last_exc = exc
                # nothing reached Odoo: safe to retry, and JSON-RPC is not usable here
                self._pin_xmlrpc(reason=f"JSON-RPC unavailable ({exc})")
                continue
            except TransportError as exc:
                last_exc = exc
                if not replayable:
                    # A write with an unknown outcome (timeout, 5xx, cut reply): never replay.
                    raise TransportError(
                        f"{exc} - the call may or may not have been applied in Odoo; "
                        "check before retrying"
                    ) from exc
                continue  # idempotent (version/authenticate/reads): try the next one
        assert last_exc is not None
        raise last_exc

    def _pin_xmlrpc(self, reason: str) -> None:
        if self.pref == "jsonrpc":
            return  # the operator forced JSON-RPC: report errors, never switch
        if not self._warned_fallback:
            log.warning("falling back to XML-RPC: %s", reason)
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
