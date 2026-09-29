# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Transport selection: JSON-2, JSON-RPC and XML-RPC, with a safe fallback.

``ODOO_TRANSPORT_PREF``:
  * ``auto`` (default) decides from the target's **unclamped** series S, the
    credential kind K (an API key or a password) and U (``user:pass@`` in
    ODOO_URL). "Legacy" means JSON-RPC, then XML-RPC:

    - S < saas~18.4: legacy, as before;
    - saas~18.4 <= S < saas~21.1 with an API key and no U: JSON-2, then legacy;
      JSON-2 is pinned after the first successful sign-in;
    - the same range with a password or U: legacy, plus a deprecation notice
      from 19.0 (every legacy call logs a warning on the Odoo server);
    - S >= saas~21.1 (Odoo Online saas~21.1, on-premise Odoo 22), where the
      legacy endpoints are gone: JSON-2 only with an API key, else ConfigError.
  * ``json2``: JSON-2 only, never switches; ConfigError for a password or U.
  * ``jsonrpc`` / ``xmlrpc``: that transport only, never switches; the notice
    applies from 19.0 and ConfigError from saas~21.1.

Version detection costs no login and no server log line in ``auto``/``json2``:
the web client's ``/web/webclient/version_info``, then ``GET /json/version``,
then the legacy ``common.version`` (the first probe of ``jsonrpc``/``xmlrpc``).
The payload is cached, so ``session.facts()`` makes no second call.

A call is replayed on the next transport only when that cannot run it twice:
always for ``version``/``authenticate`` and for reads (``READ_METHODS``), but
for any other method only when the request certainly never reached Odoo
(:class:`JsonRpcUnavailable`, which includes :class:`Json2Unavailable`). After
a timeout, an HTTP 5xx or a garbled reply a write may already have committed,
so the error is raised instead of risking a duplicate. An Odoo fault is never
replayed. HTTP 429 (:class:`RateLimited`) never switches transport: reads wait
for ``Retry-After`` and retry the same transport, writes are reported. When
one transport fails and another answers, the one that answered is pinned for
the rest of the session, with a single warning.

A JSON-2 signature mismatch (:class:`Json2SignatureMismatch`: HTTP 422 from
Odoo's bind check, the method never ran) that the JSON-2 transport cannot
correct is sent over the legacy transports in ``auto`` while they exist, for
that call only: JSON-2 stays pinned.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Collection
from typing import Any

from ..errors import CompatError, ConfigError, RateLimited, TransportError
from .base import retry_delay
from .json2 import Json2SignatureMismatch, Json2Transport, Json2Unavailable, Json2Unreachable
from .jsonrpc import ApiKeyRejected, JsonRpcTransport, JsonRpcUnavailable, split_userinfo
from .xmlrpc import XmlRpcTransport

log = logging.getLogger("odoo_mcp.transport")

Series = tuple[int, int]

KINDS = ("json2", "jsonrpc", "xmlrpc")
LEGACY = ("jsonrpc", "xmlrpc")
LABELS = {"json2": "JSON-2", "jsonrpc": "JSON-RPC", "xmlrpc": "XML-RPC"}

JSON2_SINCE: Series = (18, 4)  # saas~18.4, then 19.0
NOTICE_SINCE: Series = (19, 0)  # the legacy endpoints are deprecated from 19.0
LEGACY_REMOVED: Series = (21, 1)  # Online saas~21.1; on-premise 22.0 is past it too
DOC_BEARER_SINCE: Series = (19, 0)

RATE_LIMIT_TRIES = 3  # per call and transport, for idempotent operations only

# ORM methods that only read, so replaying them on another transport is safe.
READ_METHODS = frozenset(
    {
        "search", "search_read", "search_count", "read", "read_group", "fields_get",
        "name_search", "name_get", "default_get", "check_access_rights", "has_group",
        "web_search_read", "web_read", "get_views", "fields_view_get", "export_data",
        "formatted_read_group", "web_read_group", "context_get", "has_access",
        "has_groups", "get_field_translations",
    }
)

DEPRECATION = (
    "Odoo 19 deprecates /xmlrpc and /jsonrpc; Odoo 22 (Odoo Online saas~21.1) removes "
    "them, and each call logs a deprecation warning on your Odoo server."
)
_API_KEY_HINT = "Create an API key and set ODOO_API_KEY to switch to JSON-2."
_BASIC_HINT = (
    "Basic auth in ODOO_URL uses the Authorization header that JSON-2 needs; move the "
    "gateway credentials elsewhere."
)
_PREF_HINT = "Set ODOO_TRANSPORT_PREF=auto or json2."

_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?")


def series_of(payload: Any) -> Series | None:
    """The unclamped ``(major, minor)`` of a version payload, or ``None``.

    ``server_version_info`` is ``[19, 0, ...]`` on a stable series and
    ``["saas~18", 4, ...]`` on an Odoo Online line.
    """
    if not isinstance(payload, dict):
        return None
    info = payload.get("server_version_info")
    if isinstance(info, (list, tuple)) and info:
        major = re.search(r"\d+", str(info[0]))
        if major:
            minor = info[1] if len(info) > 1 and isinstance(info[1], int) else 0
            return int(major.group(0)), minor
    match = _VERSION_RE.search(str(payload.get("server_version") or ""))
    if match:
        return int(match.group(1)), int(match.group(2) or 0)
    return None


def _label(series: Series) -> str:
    return f"{series[0]}.{series[1]}"


def select_order(pref: str, series: Series | None, secret_kind: str,
                 userinfo: bool) -> tuple[str, ...]:
    """The transports to try, in order. Raises :class:`ConfigError`.

    ``series=None`` (not known yet) only checks what needs no network.
    """
    api_key = secret_kind == "api_key"
    if pref == "json2":
        if not api_key:
            raise ConfigError(
                "ODOO_TRANSPORT_PREF=json2 needs an API key (JSON-2 refuses passwords): "
                "set ODOO_API_KEY, or use ODOO_TRANSPORT_PREF=auto"
            )
        if userinfo:
            raise ConfigError(
                "ODOO_TRANSPORT_PREF=json2 cannot be used while ODOO_URL carries "
                f"user:pass@. {_BASIC_HINT} Or use ODOO_TRANSPORT_PREF=auto"
            )
        if series is not None and series < JSON2_SINCE:
            raise ConfigError(
                "ODOO_TRANSPORT_PREF=json2 needs Odoo saas~18.4 / 19.0 or newer; this "
                f"server runs {_label(series)}. Set ODOO_TRANSPORT_PREF=auto"
            )
        return ("json2",)
    if series is not None and series >= LEGACY_REMOVED and (
            pref in LEGACY or not api_key or userinfo):
        steps = []
        if not api_key:
            steps.append("set ODOO_API_KEY")
        if userinfo:
            steps.append("remove user:pass@ from ODOO_URL")
        if pref in LEGACY:
            steps.append("set ODOO_TRANSPORT_PREF=auto or json2")
        raise ConfigError(
            f"Odoo {_label(series)} has no /xmlrpc or /jsonrpc endpoint (removed in Odoo 22 "
            "and Odoo Online saas~21.1); only JSON-2 works, with an API key: "
            + ", ".join(steps)
        )
    if pref in LEGACY:
        return (pref,)
    if series is None or series < JSON2_SINCE or not api_key or userinfo:
        return LEGACY
    if series >= LEGACY_REMOVED:
        return ("json2",)
    return KINDS


def deprecation_notice(pref: str, series: Series | None, secret_kind: str, userinfo: bool,
                       kind: str | None, reason: str | None = None) -> str | None:
    """The notice while a legacy transport is in use on 19.0+, else ``None``."""
    if series is None or series < NOTICE_SINCE or kind not in LEGACY:
        return None
    hints = []
    if pref in LEGACY:
        hints.append(_PREF_HINT)
    if secret_kind != "api_key":
        hints.append(_API_KEY_HINT)
    elif userinfo:
        hints.append(_BASIC_HINT)
    elif pref == "auto":
        detail = f" ({reason})" if reason else ""
        hints.append(
            f"JSON-2 was tried and is not usable here{detail}; check that any proxy in "
            "front of Odoo forwards /json/2 and the Authorization header."
        )
    return " ".join([DEPRECATION, *hints])


Call = Callable[[Any, str], Any]


class FallbackTransport:
    name = "fallback"

    def __init__(self, base_url: str, timeout: int = 30, pref: str = "auto",
                 secret_kind: str = "password", *,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.pref = pref if pref in (*KINDS, "auto") else "auto"
        self.secret_kind = secret_kind
        self.userinfo = split_userinfo(self.base_url)[1] is not None
        self._xml: XmlRpcTransport | None = None
        self._json: JsonRpcTransport | None = None
        self._j2: Json2Transport | None = None
        self._pinned: str | None = None  # set by a fallback or a JSON-2 sign-in
        self._frozen: tuple[str, ...] | None = None  # the auto order, fixed at sign-in
        self._version_info: dict[str, Any] | None = None
        self._series: Series | None = None
        self._detect_tried = False
        self._fallback_reason: str | None = None
        self._warned_fallback = False
        self._notice_logged = False
        self._sleep = sleep

    # -- lazy transport builders -------------------------------------------
    def _xmlrpc(self) -> XmlRpcTransport:
        if self._xml is None:
            self._xml = XmlRpcTransport(self.base_url, self.timeout)
        return self._xml

    def _jsonrpc(self) -> JsonRpcTransport:
        if self._json is None:
            self._json = JsonRpcTransport(self.base_url, self.timeout)
        return self._json

    def _json2(self) -> Json2Transport:
        if self._j2 is None:
            self._j2 = Json2Transport(self.base_url, self.timeout)
            self._j2.series = self._series
        return self._j2

    def _get(self, kind: str) -> Any:
        if kind == "json2":
            return self._json2()
        return self._jsonrpc() if kind == "jsonrpc" else self._xmlrpc()

    # -- version and policy -------------------------------------------------
    @property
    def series(self) -> Series | None:
        """The target's unclamped ``(major, minor)``, once known."""
        return self._series

    def _remember_version(self, payload: dict[str, Any]) -> None:
        self._version_info = dict(payload) if isinstance(payload, dict) else {}
        self._series = series_of(payload)
        if self._j2 is not None:
            self._j2.series = self._series

    def version(self) -> dict[str, Any]:
        """The ``common.version()`` payload, probed once and cached."""
        if self._version_info is None:
            web_first = self.pref in ("auto", "json2")
            probes: list[tuple[str, ...]] = [("json2",), LEGACY if web_first else (self.pref,)]
            if not web_first:
                probes.reverse()  # jsonrpc/xmlrpc keep common.version as the first probe
            errors: list[TransportError] = []
            for kinds in probes:
                try:
                    _kind, payload = self._run("version", kinds, lambda t, _k: t.version(),
                                               replayable=True)
                except RateLimited:
                    raise
                except TransportError as exc:
                    errors.append(exc)
                    continue
                self._remember_version(payload)
                break
            else:
                # auto reports the legacy probe's error (as before); json2 its own.
                raise errors[-1] if self.pref == "auto" else errors[0]
        return dict(self._version_info or {})

    def _detect(self, *, retry: bool = False) -> None:
        """Learn the series if not known yet; a failure leaves it unknown.

        Calls probe once; a sign-in (``retry``) probes again after a failure.
        """
        if self._version_info is not None or (self._detect_tried and not retry):
            return
        self._detect_tried = True
        try:
            self.version()
        except RateLimited:
            raise
        except TransportError:
            pass  # the sign-in or the call that follows reports the real problem

    def _needs_series(self) -> bool:
        return self.pref == "json2" or (
            self.pref == "auto" and self.secret_kind == "api_key" and not self.userinfo)

    def _order(self) -> tuple[str, ...]:
        if self._pinned:
            return (self._pinned,)
        if self._frozen:
            return self._frozen
        if self.pref == "json2":  # credential checks first: no network for a bad config
            select_order("json2", None, self.secret_kind, self.userinfo)
        if self._series is None and self._needs_series():
            self._detect()
        return select_order(self.pref, self._series, self.secret_kind, self.userinfo)

    def _tentative_kind(self) -> str:
        if self._pinned:
            return self._pinned
        if self.pref != "auto":
            return self.pref
        if self._frozen:
            return self._frozen[0]
        try:
            return select_order(self.pref, self._series, self.secret_kind, self.userinfo)[0]
        except ConfigError:
            return "json2"

    # -- the replay rules ---------------------------------------------------
    def _attempt(self, transport: Any, kind: str, call: Call, replayable: bool) -> Any:
        tries = 0
        while True:
            try:
                return call(transport, kind)
            except RateLimited as exc:
                tries += 1
                if not replayable:
                    raise RateLimited(
                        f"{exc} - Odoo refused the call (HTTP 429, rate limited); retry later",
                        retry_after=exc.retry_after,
                    ) from exc
                if tries >= RATE_LIMIT_TRIES:
                    raise RateLimited(
                        f"{exc} - still rate limited after {tries} tries; retry later",
                        retry_after=exc.retry_after,
                    ) from exc
                self._sleep(retry_delay(exc.retry_after))

    def _run(self, op: str, kinds: tuple[str, ...], call: Call,
             replayable: bool, *, pin: bool = True) -> tuple[str, Any]:
        last_exc: TransportError | None = None
        last_kind = ""
        for kind in kinds:
            transport = self._get(kind)
            try:
                result = self._attempt(transport, kind, call, replayable)
            except RateLimited:
                raise  # never switch transport on a 429
            except (ApiKeyRejected, JsonRpcUnavailable) as exc:
                last_exc, last_kind = exc, kind  # nothing reached Odoo: safe to go on
                continue
            except TransportError as exc:
                last_exc, last_kind = exc, kind
                if not replayable:
                    # A write with an unknown outcome (timeout, 5xx, cut reply): never replay.
                    raise TransportError(
                        f"{exc} - the call may or may not have been applied in Odoo; "
                        "check before retrying"
                    ) from exc
                continue  # idempotent (version/authenticate/reads): try the next one
            if op != "version":
                # A signature mismatch says nothing about JSON-2 working here: no pin.
                if pin and last_exc is not None and not isinstance(
                        last_exc, Json2SignatureMismatch):
                    self._pin(kind, reason=f"{LABELS[last_kind]} failed ({last_exc})")
                self._after_success(kind)
            return kind, result
        assert last_exc is not None
        if self.pref == "json2" and isinstance(last_exc, Json2Unreachable):
            raise Json2Unreachable(
                f"{last_exc} - the Odoo server could not be reached: check ODOO_URL "
                "(scheme, host, port) and that this machine can reach it (network, "
                "DNS, TLS)"
            ) from last_exc
        if self.pref == "json2" and isinstance(last_exc, Json2Unavailable) and not isinstance(
                last_exc, Json2SignatureMismatch):
            raise Json2Unavailable(
                f"{last_exc} - JSON-2 needs Odoo saas~18.4 / 19.0 or newer, or a proxy "
                "blocks /json/2; set ODOO_TRANSPORT_PREF=auto to use the legacy endpoints"
            ) from last_exc
        raise last_exc

    def _pin(self, kind: str, reason: str) -> None:
        if self.pref != "auto":
            return  # the operator chose the transport: report errors, never switch
        if not self._warned_fallback:
            log.warning("falling back to %s: %s", LABELS[kind], reason)
            self._warned_fallback = True
        self._fallback_reason = reason
        self._pinned = kind

    def _after_success(self, kind: str) -> None:
        if self._notice_logged or kind not in LEGACY:
            return
        notice = self.transport_notice
        if notice:
            log.warning("%s", notice)
            self._notice_logged = True

    # -- Transport protocol -------------------------------------------------
    def authenticate(self, db: str, login: str, secret: str) -> int:
        if self.pref == "json2":
            select_order("json2", None, self.secret_kind, self.userinfo)
        # The series decides the order, the notice and the saas~21.1 error.
        self._detect(retry=True)
        kinds = self._order()
        kind, uid = self._run(
            "authenticate", kinds, lambda t, _k: t.authenticate(db, login, secret),
            replayable=True,
        )
        if self.pref == "auto" and not self._pinned:
            if kind == "json2":
                self._pinned = "json2"
            else:
                self._frozen = kinds
        return uid

    def execute_kw(
        self,
        db: str,
        uid: int,
        secret: str,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
        ids: Any = None,
        *,
        transports: Collection[str] | None = None,
    ) -> Any:
        """``model.method`` over the active transport.

        ``ids`` (optional) are the records of a record method: JSON-2 sends them
        as ``"ids"``, the legacy transports as the first positional argument.
        ``transports`` (optional) limits the call to those kinds: it is never
        sent or replayed over another one (e.g. imports, whose results XML-RPC
        cannot marshal), and a :class:`CompatError` says so when none is left.
        """
        kinds = self._order()
        if transports is not None:
            allowed = tuple(kind for kind in kinds if kind in transports)
            if not allowed:
                wanted = " or ".join(LABELS.get(kind, kind) for kind in transports)
                raise CompatError(
                    f"{model}.{method} needs {wanted}; this session uses "
                    + " / ".join(LABELS[kind] for kind in kinds),
                    remediation="set ODOO_TRANSPORT_PREF=auto (JSON-RPC exists from Odoo 12, "
                    "JSON-2 from saas~18.4 / 19.0 with an API key), and let /jsonrpc and "
                    "/json/2 through any proxy in front of Odoo",
                )
            kinds = allowed

        def call(transport: Any, kind: str) -> Any:
            if kind == "json2":
                if ids is None:
                    return transport.execute_kw(db, uid, secret, model, method, args, kwargs)
                return transport.execute_kw(db, uid, secret, model, method, args, kwargs,
                                            ids=ids)
            positional = list(args or [])
            if ids is not None:
                positional = [ids, *positional]
            return transport.execute_kw(db, uid, secret, model, method, positional, kwargs)

        replayable = method in READ_METHODS
        try:
            return self._run("execute_kw", kinds, call, replayable=replayable)[1]
        except Json2SignatureMismatch:
            legacy = self._legacy_for_mismatch(kinds, transports)
            if not legacy:
                raise
            log.warning("JSON-2 refused the argument names of %s.%s (the method did not "
                        "run); sending this call over %s", model, method, LABELS[legacy[0]])
            # The JSON-2 attempt never ran, so this is the first execution; JSON-2
            # stays pinned for the next calls.
            return self._run("execute_kw", legacy, call, replayable=replayable, pin=False)[1]

    def _legacy_for_mismatch(self, kinds: tuple[str, ...],
                             transports: Collection[str] | None) -> tuple[str, ...]:
        """The legacy transports ``auto`` may use after a JSON-2 signature mismatch."""
        if self.pref != "auto" or self._series is None:
            return ()
        if self._series >= LEGACY_REMOVED:
            return ()
        return tuple(kind for kind in LEGACY if kind not in kinds
                     and (transports is None or kind in transports))

    def api_doc(self, db: str, secret: str, model: str) -> dict[str, Any] | None:
        """``/doc-bearer/<model>.json`` when this target and credential allow it."""
        if not (self._series is not None and self._series >= DOC_BEARER_SINCE
                and self.secret_kind == "api_key" and not self.userinfo):
            return None
        return self._json2().api_doc(db, secret, model)

    # -- diagnostics --------------------------------------------------------
    @property
    def json2_available(self) -> bool:
        """Whether JSON-2 can serve this target with this credential."""
        return (self._series is not None and self._series >= JSON2_SINCE
                and self.secret_kind == "api_key" and not self.userinfo)

    @property
    def transport_notice(self) -> str | None:
        """The deprecation notice while a legacy transport is used on 19.0+."""
        return deprecation_notice(self.pref, self._series, self.secret_kind, self.userinfo,
                                  self._tentative_kind(), self._fallback_reason)

    @property
    def active(self) -> str:
        """Which transport will currently be used (for diagnostics).

        ``json2``, ``jsonrpc`` or ``xmlrpc`` once pinned or forced; before that
        ``<first to try>(auto)``, e.g. ``jsonrpc(auto)``.
        """
        if self._pinned:
            return self._pinned
        if self.pref != "auto":
            return self.pref
        if self._frozen:
            return f"{self._frozen[0]}(auto)"
        if self._series is None:
            return "jsonrpc(auto)"
        return f"{self._tentative_kind()}(auto)"
