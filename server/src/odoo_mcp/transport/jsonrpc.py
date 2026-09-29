# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""JSON-RPC transport (``/jsonrpc``), on the standard library (``urllib``).

Faster and friendlier to modern tooling. Odoo accepts API keys on ``/jsonrpc``
exactly as on ``/xmlrpc/2`` (both go through ``dispatch_rpc``, 14-19; checked
live on 18.0), but a reverse proxy or gateway in front of Odoo can block or
alter ``/jsonrpc``. When it refuses the credentials the FallbackTransport
retries over XML-RPC. Both endpoints are deprecated in Odoo 19 and scheduled
for removal in Odoo 22.

Failures are split in two so a retry can never run a write twice:
:class:`JsonRpcUnavailable` means the request certainly never reached an Odoo
JSON-RPC handler (connection or TLS failure, HTTP 3xx/4xx), while a plain
:class:`TransportError` (HTTP 5xx, a timeout while waiting, a cut connection,
a 2xx reply that is not JSON-RPC) means Odoo may already have run the call.
HTTP 429 is :class:`RateLimited`: the request was refused for now.
"""

from __future__ import annotations

import base64
import gzip
import http.client
import itertools
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..errors import AuthError, OdooFault, RateLimited, TransportError
from .base import parse_retry_after, tls_context

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


class JsonRpcUnavailable(TransportError):
    """The request never reached an Odoo JSON-RPC handler: safe to retry elsewhere."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirected POST would be replayed as a body-less GET, possibly to another
    host, and whatever it returned taken as the RPC result: refuse instead."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def split_userinfo(url: str) -> tuple[str, str | None]:
    """Return ``(url_without_userinfo, basic_auth_header_or_None)``.

    ``https://user:pass@host`` is valid in ODOO_URL (HTTP basic auth in front of
    Odoo); urllib cannot use it directly and would echo it in errors.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        has_userinfo = parts.username is not None or parts.password is not None
    except ValueError:  # malformed URL: the request below reports it cleanly
        return url, None
    if not has_userinfo:
        return url, None
    user = urllib.parse.unquote(parts.username or "")
    password = urllib.parse.unquote(parts.password or "")
    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    netloc = parts.netloc.rpartition("@")[2]
    return urllib.parse.urlunsplit(parts._replace(netloc=netloc)), f"Basic {token}"


class JsonRpcTransport:
    name = "jsonrpc"

    def __init__(self, base_url: str, timeout: int = 30) -> None:
        url, self._auth = split_userinfo(base_url.rstrip("/"))
        self.base_url = url  # never contains credentials
        self.timeout = timeout
        self._ids = itertools.count(1)
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=tls_context()), _NoRedirect()
        )

    def _call(self, service: str, method: str, args: list[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": next(self._ids),
        }
        try:
            request = urllib.request.Request(
                f"{self.base_url}/jsonrpc",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                },
                method="POST",
            )
            if self._auth:
                request.add_unredirected_header("Authorization", self._auth)
            with self._opener.open(request, timeout=self.timeout) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    body = gzip.decompress(body)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:  # rate limited: refused, never a reason to switch transport
                raise RateLimited(
                    "jsonrpc: HTTP 429 Too Many Requests",
                    retry_after=parse_retry_after(exc.headers.get("Retry-After")),
                ) from None
            if 300 <= exc.code < 500:  # redirect or rejected before Odoo ran anything
                raise JsonRpcUnavailable(f"jsonrpc: HTTP {exc.code} {exc.reason}") from None
            raise TransportError(f"jsonrpc: HTTP {exc.code} {exc.reason}") from None
        except urllib.error.URLError as exc:  # connect/TLS/send failed: nothing ran
            raise JsonRpcUnavailable(f"jsonrpc transport error: {exc.reason}") from None
        except (http.client.HTTPException, OSError, EOFError) as exc:
            # Sent, then the reply was cut or timed out: the call may have run.
            raise TransportError(f"jsonrpc transport error: {type(exc).__name__}: {exc}") from None
        except ValueError as exc:  # malformed URL
            raise JsonRpcUnavailable(f"jsonrpc transport error: {exc}") from None

        try:
            data = json.loads(body.decode("utf-8"))
        except ValueError:
            data = None
        if not isinstance(data, dict):
            # The request was sent and something answered 2xx: Odoo may have run
            # the call (a proxy can replace a good reply), so this is uncertain.
            raise TransportError("jsonrpc: the reply is not a JSON-RPC object")

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
