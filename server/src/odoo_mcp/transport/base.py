# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Transport abstraction over Odoo's RPC interfaces."""

from __future__ import annotations

import datetime
import email.utils
import os
import ssl
import time
import urllib.parse
from typing import Any, Protocol, runtime_checkable

# What a malformed ODOO_URL is reported as, instead of the parser's own text: that text quotes
# the whole network location, so a gateway's user:pass@ would reach the model and the logs.
URL_UNREADABLE = ("the Odoo URL cannot be read: write it as https://your-host; if it has a "
                  "user:pass@ part, write each special character of the password as %XX "
                  "(# as %23, / as %2F, ? as %3F)")


def hides_user_info(url: str) -> bool:
    """True when ``url`` may carry a ``user:pass@`` part that no parser can set apart.

    Two shapes. The parser refuses the URL and its network location holds an ``@`` or a
    non-ASCII character (normalization can turn one into ``@``). Or the parser finds no user
    information although an ``@`` follows the scheme: a password written with a raw ``/``,
    ``?`` or ``#`` ends the network location early, so the start of the password reads as the
    host or the port. A message or a display that quotes such a URL would quote the password.
    The test is deliberately wide: an ``@`` in the path, the query or the fragment with no
    readable user information (``https://host/@me``) is refused too, because nothing tells it
    from a password cut short, and an Odoo base URL has no use for one.
    """
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        authority = url.partition("://")[2]
        for delimiter in "/?#":
            authority = authority.partition(delimiter)[0]
        return "@" in authority or not authority.isascii()
    if parts.username is not None or parts.password is not None:
        return False
    return "@" in (url.partition("://")[2] or url)


# Waits for an HTTP 429 (seconds): the server's Retry-After, capped, or a default.
RETRY_AFTER_DEFAULT = 10.0
RETRY_AFTER_MAX = 30.0


def parse_retry_after(value: str | None, *, now: float | None = None) -> float | None:
    """Seconds to wait from a ``Retry-After`` header (delta-seconds or HTTP date).

    Returns ``None`` when the header is absent or unreadable, so the caller can
    apply its default. Never negative.
    """
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:  # pragma: no cover - some Python versions return None for junk
        return None
    if when.tzinfo is None:  # "-0000" dates are naive: RFC 7231 dates are GMT
        when = when.replace(tzinfo=datetime.timezone.utc)
    current = time.time() if now is None else now
    return max(0.0, when.timestamp() - current)


def retry_delay(retry_after: float | None) -> float:
    """The wait before retrying a rate-limited read: bounded, with a default."""
    if retry_after is None:
        return RETRY_AFTER_DEFAULT
    return min(max(0.0, retry_after), RETRY_AFTER_MAX)

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
