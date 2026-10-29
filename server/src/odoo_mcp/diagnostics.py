# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Local diagnostics: a small, metadata-only record of what the server did.

When the Odoo tools do not work, support needs to see what happened on the user's
machine: whether the server started, how it was set up (never with which values),
whether it reached Odoo, and how it ended. The server writes that, one JSON object
per line, to ``server.jsonl`` in the folder ``ODOO_DIAG_DIR`` names (the plugin
passes ``${CLAUDE_PLUGIN_DATA}/diagnostics``). The SessionStart hook writes its own
``hook.jsonl`` in the same folder, so the two never write the same file.

Allowlist only (``SERVER_RECORDS``, ``HOOK_RECORDS``): every key of every event has
a check, and a value that fails it is left out, or written as ``other``. A line
never holds the Odoo URL or host, the database, the login, the API key, the
password, the HTTP bearer, the policy file path, record data, a domain, an id, a
field value, a tool argument or an exception's message text. An error is written
as a fixed category (``CATEGORIES``) plus the HTTP status when there is one; a
crash as the exception class name plus the (module, function, line) of its frames
inside ``odoo_mcp``.

Events of the server:
  * ``start``: plugin, Python and OS versions, the transport preference, Read-only
    mode, the permission policy (profile and digest; locked with its E-code), which
    required settings are present (booleans), the kind of credential, the audit
    mode, and the ``CLAUDE_CODE_ENTRYPOINT`` token;
  * ``connect``: the first connection outcome of the session (the transport used,
    the Odoo major version, edition and deployment; or the error category and
    HTTP status), and one more when a session that failed signs in later;
  * ``crash``: an unexpected exception, at most ``CRASH_LIMIT`` per process;
  * ``stop``: uptime in seconds, tool calls, and errors by category.

The files: UTF-8 (ASCII in practice), every line shorter than 2 KB; the folder is
created 0700 and each file 0600 on POSIX, and a looser file is tightened before it
is written to, as the audit does; once a file reaches 256 KiB it is renamed
``<name>.1`` (replacing an older one) and a new one starts. ``ODOO_DIAG_DIR`` unset
or ``off`` writes nothing, and so does a value that is not an absolute path (an
unresolved ``${...}``). Diagnostics never raise into the server: a failure is
logged at debug level and the line is dropped.

``run_stdio.py --diagnose`` (``diagnose_main``) prints the support report a user can
paste to support. It reads these files and the audit, and never contacts Odoo.
"""

from __future__ import annotations

import datetime
import gzip
import http.client
import json
import logging
import os
import platform
import re
import socket
import ssl
import stat
import threading
import time
import urllib.error
import xml.parsers.expat
import xmlrpc.client
import zlib
from collections.abc import Iterable, Mapping
from typing import Any, Callable

from . import __version__ as PLUGIN_VERSION
from .config import Settings
from .errors import (
    AuthError,
    ConfigError,
    OdooFault,
    PolicyConfigError,
    PolicyError,
    TransportError,
)
from .policy.model import PROFILES

try:  # POSIX only: Windows appends without the lock
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

log = logging.getLogger("odoo_mcp.diagnostics")

DIAG_VERSION = 1
SERVER_FILE = "server.jsonl"
HOOK_FILE = "hook.jsonl"
CONTAINER_MARKER = "container-mode"  # /odoo-tools:deploy-local, container mode
LINE_LIMIT = 2048  # bytes, the newline included: every line is shorter than this
ROTATE_AT = 256 * 1024  # bytes: a file this large is renamed <name>.1 before the next line
TAIL_BYTES = 64 * 1024  # how much of the end of a file a reader looks at
CRASH_LIMIT = 10  # crash records per process
FRAME_LIMIT = 8  # frames per crash record, the innermost ones
REPORT_SERVER_EVENTS, REPORT_HOOK_EVENTS, AUDIT_DAYS = 5, 3, 7
AUDIT_READ_LIMIT = 64 * 1024 * 1024  # bytes of audit files one report reads at most
_AUDIT_LINE_LIMIT = 1024 * 1024
HEADER = "odoo-tools support report (no keys, URLs, logins or record data)"

CATEGORIES = ("config", "auth", "access", "network", "timeout", "tls", "http", "protocol",
              "policy", "other")
CRASH_PLACES = ("serve", "loop", "request", "policy", "tool")
SOURCES = ("startup", "resume", "clear", "compact")  # SessionStart sources
TRANSPORTS = ("json2", "jsonrpc", "xmlrpc")
TRANSPORT_PREFS = ("auto", *TRANSPORTS)

_TS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+~-]{0,31}")
_OS_PART = re.compile(r"[0-9A-Za-z][0-9A-Za-z_.+~-]{0,63}")
ENTRYPOINT = re.compile(r"[A-Za-z0-9_.-]{1,32}")
_DIGEST = re.compile(r"[0-9a-f]{12}")
_E_CODE = re.compile(r"E[0-9]{1,2}")
_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_MODULE = re.compile(r"odoo_mcp(?:\.[a-z_][a-z0-9_]{0,47}){0,4}")
_FUNCTION = re.compile(r"[A-Za-z_<][A-Za-z0-9_<>]{0,63}")
_SESSION_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
_SERVER_LAST = re.compile(r"none|ok|locked(?::E[0-9]{1,2})?|" + "|".join(CATEGORIES))
_RULE = re.compile(r"[A-Za-z0-9_.:*\-]{1,100}")
_HTTP_STATUS = re.compile(r"\bHTTP ([1-5][0-9]{2})\b")
_AUDIT_STATUSES = ("ok", "error", "refused", "invalid")


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# --- the allowlist -----------------------------------------------------------------------

_DROP = object()  # what a check returns for a value that is left out
Check = Callable[[Any], Any]


def _one_of(*values: str) -> Check:
    allowed = frozenset(values)
    return lambda value: value if isinstance(value, str) and value in allowed else _DROP


def _matching(pattern: re.Pattern[str], *, other: str | None = None) -> Check:
    def check(value: Any) -> Any:
        if isinstance(value, str) and pattern.fullmatch(value):
            return value
        return other if other is not None and isinstance(value, str) else _DROP
    return check


def _flag(value: Any) -> Any:
    return value if isinstance(value, bool) else _DROP


def _number(low: int, high: int) -> Check:
    def check(value: Any) -> Any:
        ok = isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
        return value if ok else _DROP
    return check


def _object(fields: Mapping[str, Check]) -> Check:
    return lambda value: _clean_fields(fields, value) if isinstance(value, dict) else _DROP


def _counts(keys: Iterable[str]) -> Check:
    allowed = tuple(keys)
    count = _number(0, 10**12)

    def check(value: Any) -> Any:
        if not isinstance(value, dict):
            return _DROP
        return {key: value[key] for key in allowed
                if key in value and count(value[key]) is not _DROP}
    return check


def _frames(value: Any) -> Any:
    if not isinstance(value, list):
        return _DROP
    line = _number(1, 10**7)
    return [[item[0], item[1], item[2]] for item in value[-FRAME_LIMIT:]
            if isinstance(item, (list, tuple)) and len(item) == 3
            and isinstance(item[0], str) and _MODULE.fullmatch(item[0])
            and isinstance(item[1], str) and _FUNCTION.fullmatch(item[1])
            and line(item[2]) is not _DROP]


def _common(event: str, *, pid: bool) -> dict[str, Check]:
    fields: dict[str, Check] = {"v": _number(DIAG_VERSION, DIAG_VERSION), "ts": _matching(_TS),
                                "event": _one_of(event)}
    if pid:
        fields["pid"] = _number(1, 2**32)
    return fields


_OS = {"system": _matching(_OS_PART, other="other"),
       "release": _matching(_OS_PART, other="other"),
       "machine": _matching(_OS_PART, other="other")}
_PLATFORM = {"plugin": _matching(_VERSION, other="other"), "os": _object(_OS),
             "python": _matching(_VERSION, other="other")}

# What each event of server.jsonl may hold, in the order it is written.
SERVER_RECORDS: dict[str, dict[str, Check]] = {
    "start": {
        **_common("start", pid=True),
        **_PLATFORM,
        "transport": _one_of(*TRANSPORT_PREFS),
        "readonly": _flag,
        "policy": _object({"profile": _one_of(*PROFILES, "unknown"), "digest": _matching(_DIGEST),
                           "locked": _flag, "code": _matching(_E_CODE)}),
        "settings": _object({"url": _flag, "db": _flag, "login": _flag}),
        "credential": _one_of("api_key", "password", "none"),
        "audit": _one_of("file", "stderr", "off"),
        "entrypoint": _matching(ENTRYPOINT, other="other"),
    },
    "connect": {
        **_common("connect", pid=True),
        "ok": _flag,
        "transport": _one_of(*TRANSPORTS, "unknown"),
        "odoo_major": _number(1, 99),
        "edition": _one_of("community", "enterprise", "unknown"),
        "deployment": _one_of("onprem", "saas", "unknown"),
        "category": _one_of(*CATEGORIES),
        "status": _number(100, 599),
    },
    "crash": {
        **_common("crash", pid=True),
        "where": _one_of(*CRASH_PLACES),
        "error": _matching(_CLASS, other="other"),
        "frames": _frames,
    },
    "stop": {
        **_common("stop", pid=True),
        "uptime_s": _number(0, 10**10),
        "calls": _number(0, 10**12),
        "errors": _counts(CATEGORIES),
    },
}

# What hooks/session_start.py writes to hook.jsonl. The hook is self-contained (it
# imports nothing from this package); the tests check that it writes nothing else.
HOOK_RECORDS: dict[str, dict[str, Check]] = {
    "session_start": {
        **_common("session_start", pid=False),
        "source": _one_of(*SOURCES, "other"),
        "session_id": _matching(_SESSION_ID, other="other"),
        **_PLATFORM,
        "entrypoint": _matching(ENTRYPOINT, other="other"),
        "server_last": _matching(_SERVER_LAST),
        "age_h": _number(0, 10**7),
        "container": _flag,
    },
}


def _clean_fields(fields: Mapping[str, Check], obj: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, check in fields.items():
        if key in obj:
            value = check(obj[key])
            if value is not _DROP:
                out[key] = value
    return out


def clean_record(records: Mapping[str, Mapping[str, Check]], obj: Any) -> dict[str, Any] | None:
    """``obj`` reduced to what its event's allowlist accepts, in the written key order;
    ``None`` when it is not a record of a known event and of this version."""
    if not isinstance(obj, dict):
        return None
    event, version = obj.get("event"), obj.get("v")
    fields = records.get(event) if isinstance(event, str) else None
    if fields is None or isinstance(version, bool) or version != DIAG_VERSION:
        return None
    out = _clean_fields(fields, obj)
    return out if "ts" in out else None


def _dumps(record: Mapping[str, Any]) -> bytes:
    return json.dumps(record, ensure_ascii=True, separators=(",", ":"),
                      allow_nan=False).encode("ascii")


def encode_record(records: Mapping[str, Mapping[str, Check]], obj: Any) -> bytes | None:
    """The line for ``obj`` (without its newline), allowlisted and shorter than
    ``LINE_LIMIT`` with the newline; a crash drops its outermost frames to fit.
    ``None`` when nothing valid is left."""
    record = clean_record(records, obj)
    if record is None:
        return None
    data = _dumps(record)
    frames = record.get("frames")
    while len(data) + 1 >= LINE_LIMIT and frames:
        frames.pop(0)
        data = _dumps(record)
    return data if len(data) + 1 < LINE_LIMIT else None


# --- values ------------------------------------------------------------------------------

def entrypoint_token(raw: str | None) -> str | None:
    """``CLAUDE_CODE_ENTRYPOINT`` as written: itself when it is a short plain token,
    ``other`` when it is anything else, ``None`` (left out) when it is unset."""
    if raw is None:
        return None
    return raw if ENTRYPOINT.fullmatch(raw) else "other"


def _os_part(value: Any) -> str:
    if not value:
        return "unknown"
    return value if isinstance(value, str) and _OS_PART.fullmatch(value) else "other"


def os_info() -> dict[str, str]:
    return {"system": _os_part(platform.system()), "release": _os_part(platform.release()),
            "machine": _os_part(platform.machine())}


def policy_info(policy: Any) -> dict[str, Any]:
    """The profile, and the digest or (locked) the E-code; never the file path."""
    locked = bool(getattr(policy, "locked", False))
    name = getattr(policy, "profile_name", None)
    info: dict[str, Any] = {"profile": name if isinstance(name, str) and name in PROFILES
                            else "unknown", "locked": locked}
    if locked:
        info["code"] = getattr(policy, "error_code", None)
    else:
        info["digest"] = getattr(policy, "digest", None)
    return info


def start_record(settings: Any, policy: Any, audit_mode: str,
                 environ: Mapping[str, str]) -> dict[str, Any]:
    """The ``start`` event: whether each setting is present, never its value."""
    record: dict[str, Any] = {
        "event": "start",
        "plugin": PLUGIN_VERSION,
        "python": platform.python_version(),
        "os": os_info(),
        "transport": getattr(settings, "transport_pref", None),
        "readonly": bool(getattr(settings, "readonly", False)),
        "policy": policy_info(policy),
        "settings": {name: bool(getattr(settings, name, "")) for name in ("url", "db", "login")},
        "credential": ("api_key" if getattr(settings, "api_key", "") else
                       "password" if getattr(settings, "password", "") else "none"),
        "audit": audit_mode,
    }
    entrypoint = entrypoint_token(environ.get("CLAUDE_CODE_ENTRYPOINT"))
    if entrypoint is not None:
        record["entrypoint"] = entrypoint
    return record


def connect_record(session: Any) -> dict[str, Any]:
    """A successful ``connect``, from what the signed-in session already knows: it
    never contacts Odoo. The edition is ``unknown`` until a tool probed it."""
    transport = getattr(session, "transport", None)
    kind = str(getattr(transport, "active", "") or "").split("(", 1)[0]  # "jsonrpc(auto)"
    known = getattr(session, "known_facts", None)
    facts = known() if callable(known) else None
    series = getattr(transport, "series", None)
    if isinstance(series, tuple) and series and isinstance(series[0], int):
        major = series[0]  # unclamped: Odoo 22 says 22, where the facts say 19
    else:
        major = getattr(facts, "version", None)
    deployment = getattr(facts, "deployment", None)
    if deployment is None:
        from .compat.detect import detect_deployment  # pure: the host name only

        url = getattr(getattr(session, "creds", None), "url", "")
        deployment = detect_deployment(url) if isinstance(url, str) and url else "unknown"
    return {"event": "connect", "ok": True, "transport": kind if kind in TRANSPORTS else "unknown",
            "odoo_major": major, "edition": getattr(facts, "edition", None) or "unknown",
            "deployment": deployment}


def connect_failure_record(failure: BaseException) -> dict[str, Any]:
    category, status = error_category(failure)
    record: dict[str, Any] = {"event": "connect", "ok": False, "category": category}
    if status is not None:
        record["status"] = status
    return record


_PACKAGE = os.path.dirname(os.path.abspath(__file__))


def _module_of(filename: str) -> str | None:
    """``odoo_mcp.tools.crud`` for a file of this package, else ``None``."""
    try:
        path = os.path.abspath(filename)
    except (TypeError, ValueError):
        return None
    prefix = _PACKAGE + os.sep
    if not os.path.normcase(path).startswith(os.path.normcase(prefix)) or not path.endswith(
            ".py"):
        return None
    parts = ["odoo_mcp", *path[len(prefix):-3].split(os.sep)]
    if parts[-1] == "__init__":
        parts.pop()
    module = ".".join(parts)
    return module if _MODULE.fullmatch(module) else None


def crash_frames(exc: BaseException, limit: int = FRAME_LIMIT) -> list[list[Any]]:
    """(module, function, line) of the traceback's frames inside ``odoo_mcp``, the
    innermost ``limit``; no source line, no local variable, no message."""
    frames: list[list[Any]] = []
    tb = exc.__traceback__
    while tb is not None:
        code = tb.tb_frame.f_code
        module = _module_of(code.co_filename)
        if module is not None:
            frames.append([module, code.co_name, tb.tb_lineno])
        tb = tb.tb_next
    return frames[-limit:] if limit > 0 else []


# --- error categories --------------------------------------------------------------------

# Odoo's XML-RPC fault codes for AccessDenied (3) and AccessError (4).
_ACCESS_FAULT_CODES = (3, 4)
_ACCESS_NAMES = ("AccessError", "AccessDenied")
_PROTOCOL_ERRORS = (xmlrpc.client.ResponseError, xml.parsers.expat.ExpatError, zlib.error,
                    gzip.BadGzipFile, UnicodeError, json.JSONDecodeError)
_NETWORK_ERRORS = (ConnectionError, socket.gaierror, socket.herror, EOFError,
                   http.client.IncompleteRead)


def _chain(exc: BaseException, limit: int = 16) -> list[BaseException]:
    """``exc``, its causes and contexts (``raise ... from None`` keeps the context),
    and the reason of a ``URLError``, without repeats."""
    out: list[BaseException] = []
    todo: list[Any] = [exc]
    seen: set[int] = set()
    while todo and len(out) < limit:
        current = todo.pop(0)
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        out.append(current)
        if isinstance(current, urllib.error.URLError) and not isinstance(
                current, urllib.error.HTTPError):
            todo.append(current.reason)
        todo.extend((current.__cause__, current.__context__))
    return out


def _http_status(chain: list[BaseException]) -> int | None:
    for item in chain:
        code = (item.code if isinstance(item, urllib.error.HTTPError) else
                item.errcode if isinstance(item, xmlrpc.client.ProtocolError) else None)
        if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599:
            return code
    for item in chain:  # JSON-2 keeps the status in the transport's own message only
        if isinstance(item, TransportError):
            match = _HTTP_STATUS.search(str(item))
            if match:
                return int(match.group(1))
    return None


def _access_fault(chain: list[BaseException]) -> bool:
    for item in chain:
        name = item.odoo_name if isinstance(item, OdooFault) else None
        if isinstance(name, str) and name.rsplit(".", 1)[-1] in _ACCESS_NAMES:
            return True
        if isinstance(item, xmlrpc.client.Fault) and item.faultCode in _ACCESS_FAULT_CODES:
            return True
    return False


def _transport_category(chain: list[BaseException], status: int | None) -> str:
    def seen(kinds: Any) -> bool:
        return any(isinstance(item, kinds) for item in chain)

    if seen((ssl.SSLError, ssl.CertificateError)):
        return "tls"
    if seen((socket.timeout, TimeoutError)):
        return "timeout"
    if seen(_NETWORK_ERRORS):
        return "network"
    if seen(_PROTOCOL_ERRORS):
        return "protocol"
    url_text = any(isinstance(item, urllib.error.URLError) and not isinstance(
        item, urllib.error.HTTPError) and isinstance(item.reason, str) for item in chain)
    if url_text or seen(ValueError):  # a malformed ODOO_URL, refused before sending
        return "config"
    if status is not None:
        return "http"
    if any(isinstance(item, OSError) and not isinstance(item, urllib.error.HTTPError)
           for item in chain):
        return "network"
    return "protocol"  # a reply that is not what the protocol promises


def error_category(exc: BaseException) -> tuple[str, int | None]:
    """The fixed category of an error and the HTTP status behind it, when there is one.
    It looks at classes, codes and the transports' own ``HTTP <status>``; it never
    returns, logs or keeps any text of the error."""
    try:
        chain = _chain(exc)
        status = _http_status(chain)
        if isinstance(exc, (PolicyError, PolicyConfigError)):
            return "policy", status
        if isinstance(exc, ConfigError):
            return "config", status
        if isinstance(exc, AuthError):
            return "auth", status
        if isinstance(exc, OdooFault):
            return ("access" if _access_fault(chain) else "other"), status
        if isinstance(exc, TransportError):
            return _transport_category(chain, status), status
        return "other", status
    except Exception:  # classifying must never fail a call
        return "other", None


def _connection_failure(exc: BaseException) -> bool:
    """An error that says the session could not connect, not that one call failed."""
    return isinstance(exc, (ConfigError, AuthError, TransportError)) and not isinstance(
        exc, PolicyConfigError)


# --- the files ---------------------------------------------------------------------------

def folder_state(raw: str | None) -> tuple[str, str | None]:
    """``("folder", path)`` for an absolute folder, else the state and ``None``:
    ``not set``, ``off``, ``stderr`` or ``not an absolute path``."""
    text = (raw or "").strip()
    if not text:
        return "not set", None
    lowered = text.lower()
    if lowered in ("off", "stderr"):
        return lowered, None
    path = os.path.expanduser(text)
    if "${" in path or not os.path.isabs(path):
        return "not an absolute path", None
    return "folder", path


def folder(raw: str | None) -> str | None:
    """The diagnostics folder ``ODOO_DIAG_DIR`` names, or ``None`` when it is off."""
    state, path = folder_state(raw)
    return path if state == "folder" else None


def _open_for_append(path: str) -> int:
    flags = (os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_CLOEXEC", 0))
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"{os.path.basename(path)} is not a regular file")
        # 0o600 applies only to a file os.open creates: a looser one (a copy, a
        # restored backup) is tightened before anything is appended, as the audit does.
        if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
            try:
                os.fchmod(fd, 0o600)
            except OSError:  # not the owner: the line is still written
                pass
    except BaseException:
        os.close(fd)
        raise
    return fd


def _still_named(path: str, info: os.stat_result) -> bool:
    """Whether ``path`` still names the open file (another process may have rotated it)."""
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino)


def _write_all(fd: int, data: bytes) -> None:
    while data:
        written = os.write(fd, data)
        data = data[written:]


def append_line(directory: str, name: str, data: bytes, *, rotate_at: int = ROTATE_AT) -> None:
    """Append ``data`` (one line with its newline) to ``directory/name``, which is first
    renamed ``name.1`` when it has reached ``rotate_at`` bytes. Under an exclusive
    ``flock`` where the platform has it, so two processes keep whole lines and rotate
    once. Raises ``OSError``."""
    os.makedirs(directory, mode=0o700, exist_ok=True)
    path = os.path.join(directory, name)
    rotate = True
    for _attempt in range(4):
        fd = _open_for_append(path)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            info = os.fstat(fd)
            if not _still_named(path, info):
                continue  # rotated by another process while this one waited: reopen
            if rotate and info.st_size >= rotate_at:
                rotate = False
                if fcntl is None:  # Windows renames a file only once it is closed
                    os.close(fd)
                    fd = -1
                try:
                    os.replace(path, path + ".1")
                    replaced = True
                except OSError:  # e.g. name.1 is a folder: keep appending to this file
                    replaced = False
                if replaced or fd < 0:
                    continue  # a new file starts (or, on Windows, reopen this one)
            _write_all(fd, data)
            return
        finally:
            if fd >= 0:
                os.close(fd)
    raise OSError(f"{name} kept changing while it was appended to")


def tail_lines(path: str, max_bytes: int = TAIL_BYTES) -> list[bytes]:
    """The lines in the last ``max_bytes`` of ``path``, oldest first, without a line the
    window cut; ``[]`` when it is missing, unreadable or not a regular file."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    except OSError:
        return []
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return []
        start = max(info.st_size - max_bytes, 0)
        os.lseek(fd, start, os.SEEK_SET)
        chunks, remaining = [], info.st_size - start
        while remaining > 0:
            part = os.read(fd, min(remaining, 65536))
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
    except OSError:
        return []
    finally:
        os.close(fd)
    lines = b"".join(chunks).split(b"\n")
    if start > 0:
        lines = lines[1:]  # the window starts inside a line
    return [line for line in lines if line.strip()]


def read_records(path: str, records: Mapping[str, Mapping[str, Check]], count: int,
                 max_bytes: int = TAIL_BYTES) -> list[dict[str, Any]]:
    """The last ``count`` valid records of ``path``, oldest first, each re-checked
    against the allowlist: a line someone else wrote shows only allowlisted values."""
    out: list[dict[str, Any]] = []
    for line in reversed(tail_lines(path, max_bytes)):
        if len(out) >= count:
            break
        try:
            obj = json.loads(line.decode("utf-8"))
        except (ValueError, RecursionError):
            continue
        record = clean_record(records, obj)
        if record is not None:
            out.append(record)
    out.reverse()
    return out


# --- the server's diagnostics --------------------------------------------------------------

class Diagnostics:
    """The diagnostics of one server process (see the module docstring). Without a
    folder it does nothing; with one, no method ever raises."""

    def __init__(self, directory: str | None = None, *,
                 clock: Callable[[], datetime.datetime] = _utc_now,
                 monotonic: Callable[[], float] = time.monotonic,
                 rotate_at: int = ROTATE_AT) -> None:
        self.directory = directory
        self._clock = clock
        self._monotonic = monotonic
        self._rotate_at = rotate_at
        self._born = monotonic()
        self._lock = threading.Lock()  # the counters and flags
        self._write_lock = threading.Lock()  # one line at a time from this process
        self._calls = 0
        self._errors: dict[str, int] = {}
        self._crashes = 0
        self._connect: str | None = None  # None, "error" or "ok"
        self._stopped = False

    @classmethod
    def from_settings(cls, settings: Any) -> Diagnostics:
        return cls(folder(getattr(settings, "diag_dir", "")))

    @property
    def enabled(self) -> bool:
        return self.directory is not None

    def describe(self) -> str:
        """Where the lines go, for the startup log."""
        if self.directory is None:
            return "off (ODOO_DIAG_DIR unset, off or not an absolute folder)"
        return f"{SERVER_FILE} in {self.directory}"

    # -- events ------------------------------------------------------------------------
    def start(self, settings: Any, policy: Any, audit_mode: str, *,
              environ: Mapping[str, str] | None = None) -> None:
        if self.directory is None:
            return
        try:
            self._write(start_record(settings, policy, audit_mode,
                                     os.environ if environ is None else environ))
        except Exception as exc:
            log.debug("diagnostics: no start line (%s)", type(exc).__name__)

    def tool_call(self, failure: BaseException | None = None, *,
                  category: str | None = None) -> None:
        """Count one ``tools/call`` of a known tool, and its error category if it failed."""
        if self.directory is None:
            return
        try:
            if category is None and failure is not None:
                category = error_category(failure)[0]
            with self._lock:
                self._calls += 1
                if category is not None:
                    self._errors[category] = self._errors.get(category, 0) + 1
        except Exception as exc:
            log.debug("diagnostics: a call was not counted (%s)", type(exc).__name__)

    def connection(self, session: Any, failure: BaseException | None) -> None:
        """After a tool call: the session's connection outcome, once per session, and
        once more when a session that failed signs in later. Never contacts Odoo."""
        if self.directory is None:
            return
        try:
            signed_in = session is not None and bool(getattr(session, "authenticated", False))
            with self._lock:
                if self._connect == "ok":
                    return
                if signed_in:
                    self._connect = "ok"
                elif (self._connect is None and failure is not None
                      and _connection_failure(failure)):
                    self._connect = "error"
                else:
                    return
            if signed_in:
                self._write(connect_record(session))
            elif failure is not None:
                self._write(connect_failure_record(failure))
        except Exception as exc:
            log.debug("diagnostics: no connect line (%s)", type(exc).__name__)

    def crash(self, exc: BaseException, where: str) -> None:
        """An unexpected exception: its class name and its frames inside ``odoo_mcp``."""
        if self.directory is None:
            return
        try:
            with self._lock:
                if self._crashes >= CRASH_LIMIT:
                    return
                self._crashes += 1
            self._write({"event": "crash", "where": where, "error": type(exc).__name__,
                         "frames": crash_frames(exc)})
        except Exception as problem:
            log.debug("diagnostics: no crash line (%s)", type(problem).__name__)

    def stop(self) -> None:
        if self.directory is None:
            return
        try:
            with self._lock:
                if self._stopped:
                    return
                self._stopped = True
                record = {"event": "stop",
                          "uptime_s": max(int(self._monotonic() - self._born), 0),
                          "calls": self._calls, "errors": dict(self._errors)}
            self._write(record)
        except Exception as exc:
            log.debug("diagnostics: no stop line (%s)", type(exc).__name__)

    # -- writing -----------------------------------------------------------------------
    def _write(self, fields: Mapping[str, Any]) -> None:
        """Write one allowlisted line; never raises."""
        if self.directory is None:
            return
        try:
            stamp = self._clock().astimezone(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            data = encode_record(SERVER_RECORDS,
                                 {**fields, "v": DIAG_VERSION, "ts": stamp, "pid": os.getpid()})
            if data is None:
                log.debug("diagnostics: a %s line did not fit the allowlist", fields.get("event"))
                return
            with self._write_lock:
                append_line(self.directory, SERVER_FILE, data + b"\n", rotate_at=self._rotate_at)
        except Exception as exc:  # diagnostics never break the server
            log.debug("diagnostics: a %s line was not written (%s)", fields.get("event"),
                      type(exc).__name__)


# --- run_stdio.py --diagnose -----------------------------------------------------------------

def _shown(text: str) -> str:
    """A path for the report: printable, ASCII (other characters escaped)."""
    printable = "".join(ch if ch.isprintable() else "?" for ch in text)
    return printable.encode("ascii", "backslashreplace").decode("ascii")


def _events(directory: str, name: str, records: Mapping[str, Mapping[str, Check]],
            count: int) -> list[dict[str, Any]]:
    path = os.path.join(directory, name)
    events = read_records(path, records, count)
    if len(events) < count:  # just rotated: the older file has the rest
        events = read_records(path + ".1", records, count - len(events)) + events
    return events


def diagnostics_summary(raw: str | None) -> dict[str, Any]:
    state, path = folder_state(raw)
    if state == "stderr":  # a keyword of the audit, not of the diagnostics
        state = "not an absolute path"
    if path is None:
        shown = _shown((raw or "").strip()) if state == "not an absolute path" else None
        return {"folder": shown, "state": state, "server_events": [], "hook_events": []}
    return {
        "folder": _shown(path),
        "state": "exists" if os.path.isdir(path) else "missing",
        "server_events": _events(path, SERVER_FILE, SERVER_RECORDS, REPORT_SERVER_EVENTS),
        "hook_events": _events(path, HOOK_FILE, HOOK_RECORDS, REPORT_HOOK_EVENTS),
    }


def _audit_call(line: bytes) -> tuple[str, str | None] | None:
    """(status, refusal rule or None) of an audit ``call`` line; ``None`` for any other."""
    try:
        obj = json.loads(line.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    if not isinstance(obj, dict) or obj.get("event") != "call":
        return None
    status = obj.get("status")
    status = status if isinstance(status, str) and status in _AUDIT_STATUSES else "other"
    rule = None
    if status == "refused" or obj.get("decision") == "deny":
        value = obj.get("rule")
        if value is None:
            rule = "none"
        else:
            rule = value if isinstance(value, str) and _RULE.fullmatch(value) else "?"
    return status, rule


def _audit_lines(path: str, budget: list[int]) -> Iterable[bytes]:
    """The lines of one audit file, within the report's read budget."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    except OSError:
        return
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            while True:
                line = handle.readline(_AUDIT_LINE_LIMIT)
                if not line:
                    return
                budget[0] -= len(line)
                if budget[0] < 0:
                    return
                yield line
    finally:
        if fd >= 0:
            os.close(fd)


def audit_summary(raw: str | None, today: datetime.date | None = None) -> dict[str, Any]:
    """Counts of the last ``AUDIT_DAYS`` days of audit files, by call status and by
    refusal rule: nothing else of a line is read into the report."""
    from .audit import file_name

    state, path = folder_state(raw)
    if path is None:
        return {"state": state}
    if not os.path.isdir(path):
        return {"state": "missing"}
    day = today or _utc_now().date()
    by_status: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    files = calls = 0
    budget = [AUDIT_READ_LIMIT]
    for offset in range(AUDIT_DAYS):
        name = os.path.join(path, file_name(day - datetime.timedelta(days=offset)))
        if not os.path.isfile(name):
            continue
        files += 1
        for line in _audit_lines(name, budget):
            found = _audit_call(line)
            if found is None:
                continue
            status, rule = found
            calls += 1
            by_status[status] = by_status.get(status, 0) + 1
            if rule is not None:
                by_rule[rule] = by_rule.get(rule, 0) + 1
    summary: dict[str, Any] = {"state": "ok", "days": AUDIT_DAYS, "files": files, "calls": calls,
                               "by_status": by_status, "refusals_by_rule": by_rule}
    if budget[0] < 0:
        summary["partial"] = True
    return summary


def policy_summary(settings: Any, tools: Iterable[Any]) -> dict[str, Any]:
    """The policy as the server would load it from this environment (ODOO_POLICY, else
    standard; ODOO_POLICY_FILE; ODOO_READONLY), offline: never the file path."""
    from .policy.loader import load_policy

    policy = load_policy(settings, [tool.name for tool in tools])
    info = policy_info(policy)
    summary: dict[str, Any] = {"profile": info["profile"], "file": policy.source is not None,
                               "readonly": bool(policy.readonly), "locked": policy.locked}
    if policy.locked:
        code = info.get("code")
        summary["code"] = code if isinstance(code, str) and _E_CODE.fullmatch(code) else "other"
    else:
        digest = info.get("digest")
        valid = isinstance(digest, str) and _DIGEST.fullmatch(digest)
        summary["digest"] = digest if valid else None
    return summary


def _section(build: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return build()
    except Exception as exc:  # one broken section never hides the others
        return {"state": "unavailable", "error": type(exc).__name__}


def build_report(settings: Any, diag_dir: str | None, audit_dir: str | None,
                 tools: Iterable[Any], today: datetime.date | None = None) -> dict[str, Any]:
    tools = list(tools)
    return {
        "report": HEADER,
        "plugin": PLUGIN_VERSION,
        "python": platform.python_version(),
        "os": os_info(),
        "diagnostics": _section(lambda: diagnostics_summary(diag_dir)),
        "audit": _section(lambda: audit_summary(audit_dir, today)),
        "policy": _section(lambda: policy_summary(settings, tools)),
    }


def _yes(value: Any) -> str:
    return "yes" if value else "no"


def _many(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _counted(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{key} {value}" for key, value in
                     sorted(counts.items(), key=lambda item: (-item[1], item[0]))) or "none"


def render_report(report: Mapping[str, Any]) -> str:
    """The report as text, one fact per line."""
    system = report["os"]
    lines = [
        report["report"],
        f"plugin: {report['plugin']}",
        f"python: {report['python']}",
        f"os: {system['system']} {system['release']} {system['machine']}",
    ]
    diag = report["diagnostics"]
    where, state = diag.get("folder"), diag.get("state")
    if where:
        lines.append(f"diagnostics folder: {where} ({state})")
    elif state == "not set":
        lines.append("diagnostics folder: not set (ODOO_DIAG_DIR is unset; pass --diag-dir)")
    else:
        lines.append(f"diagnostics folder: {state}")
    for title, key in ((f"last {REPORT_SERVER_EVENTS} server events ({SERVER_FILE}):",
                        "server_events"),
                       (f"last {REPORT_HOOK_EVENTS} hook events ({HOOK_FILE}):", "hook_events")):
        lines.append(title)
        events = diag.get(key) or []
        lines.extend(f"  {_dumps(event).decode('ascii')}" for event in events)
        if not events:
            lines.append("  none")
    audit = report["audit"]
    if audit.get("state") == "ok":
        text = (f"audit, last {audit['days']} days: {_many(audit['files'], 'file')}, "
                f"{_many(audit['calls'], 'call')}; by status: {_counted(audit['by_status'])}; "
                f"refusals by rule: {_counted(audit['refusals_by_rule'])}")
        if audit.get("partial"):
            text += " (partial: read limit reached)"
        lines.append(text)
    elif audit.get("state") == "not set":
        lines.append("audit: not set (ODOO_AUDIT_DIR is unset; pass --audit-dir)")
    elif audit.get("state") == "stderr":
        lines.append("audit: stderr (the audit lines go to the server's log, not to files)")
    else:
        lines.append(f"audit: {audit.get('state')}")
    policy = report["policy"]
    head = "policy (computed offline from this environment, never contacts Odoo):"
    if policy.get("state") == "unavailable":
        lines.append(f"{head} unavailable ({policy.get('error')})")
    else:
        state = (f"locked yes ({policy.get('code')})" if policy.get("locked")
                 else f"digest {policy.get('digest')}, locked no")
        lines.append(f"{head} profile {policy.get('profile')}, {state}, policy file "
                     f"{_yes(policy.get('file'))}, read-only {_yes(policy.get('readonly'))}")
    return "\n".join(lines) + "\n"


def diagnose_main(*, diag_dir: str | None, audit_dir: str | None, as_json: bool,
                  tools: Iterable[Any], out: Any, today: datetime.date | None = None) -> int:
    """``--diagnose``: print the support report; exits 0, files present or not.
    ``diag_dir`` and ``audit_dir`` default to ODOO_DIAG_DIR and ODOO_AUDIT_DIR."""
    # The policy loader logs an unexpected failure; the report keeps stderr quiet.
    logging.getLogger("odoo_mcp").addHandler(logging.NullHandler())
    settings = Settings.from_env()
    report = build_report(settings, settings.diag_dir if diag_dir is None else diag_dir,
                          settings.audit_dir if audit_dir is None else audit_dir, tools, today)
    if as_json:
        out.write(json.dumps(report, indent=2, ensure_ascii=True) + "\n")
    else:
        out.write(render_report(report))
    return 0
