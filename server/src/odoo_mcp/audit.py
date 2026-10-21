# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The audit trail: one JSON line per tool call, refusals included.

What a line holds is an allowlist (``AUDIT_KEYS``), enforced like telemetry's
``ALLOWED_KEYS``: any other key is dropped, strings lose their control
characters and are cut to 200 characters, and the ``op:model[:method]`` strings
keep only names that pass the policy's name checks. A line records tool, model
and operation names, counts, timings and the policy digest. It never records
argument values, domains, field values, ids, file contents, the URL, tokens,
keys, passwords or error message texts (only the exception class name). The
Odoo database and login appear on the ``start`` line only, written once when
the server starts, because accountability needs the acting user.

Where it goes (``ODOO_AUDIT_DIR``, which the plugin sets to
``${CLAUDE_PLUGIN_DATA}/audit``):

  * a folder: one file per UTC day, ``odoo-tools-audit-YYYY-MM-DD.jsonl``. The
    folder is created with mode 0700, each file with 0600, opened without
    following a symlink, and every line is written and flushed as one append
    under a lock (an exclusive ``flock`` too, where the platform has it, so two
    server processes sharing the folder keep one valid chain). Files older than
    ``ODOO_AUDIT_RETENTION_DAYS`` (90; 0 keeps them) are pruned when the server
    starts and at the first write after UTC midnight;
  * unset, ``stderr``, or a path that is not absolute (an unresolved
    ``${...}``): the ``odoo_mcp.audit`` logger on stderr (``docker logs`` in a
    container);
  * ``off``: nothing.

Tamper evidence: each line's ``prev`` is the first 16 hex characters of the
SHA-256 of the previous line of the same file (``genesis`` on the first), and
``seq`` counts the lines of the file from 1. A tail that cannot be read back
(a cut line, or one that is not an audit line) starts a new chain with a
``chain_reset`` line. ``run_stdio.py --verify-audit FILE`` (``verify()``)
reports the first broken line. In stdio this is evidence, not prevention:
whoever can write the folder can rewrite the files.

The audit never breaks a tool call: a failure to write logs one warning, and
the call goes on.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import math
import os
import re
import stat
import threading
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Callable

from . import __version__ as PLUGIN_VERSION
from .errors import PolicyError
from .policy.classify import valid_method, valid_model
from .policy.model import OPERATIONS

try:  # POSIX only: Windows keeps the in-process lock alone
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

log = logging.getLogger("odoo_mcp.audit")

AUDIT_VERSION = 1
AUDIT_KEYS = frozenset({"v", "ts", "seq", "prev", "event", "tool", "layer", "decision", "rule",
                        "touches", "effective", "n", "status", "error", "ms", "policy", "profile",
                        "readonly", "version", "pid", "source", "db", "login", "opened",
                        "warnings", "withheld"})
# The order keys are written in, so a line reads the same way every time.
_KEY_ORDER = ("v", "ts", "seq", "prev", "event", "tool", "layer", "decision", "rule", "touches",
              "effective", "n", "withheld", "status", "error", "ms", "policy", "profile",
              "readonly", "version", "pid", "source", "db", "login", "opened", "warnings")
EVENTS = frozenset({"start", "call", "chain_reset"})
GENESIS = "genesis"
# Matched with fullmatch, ASCII digits only: "$" would also accept a trailing newline.
FILE_PATTERN = re.compile(r"odoo-tools-audit-([0-9]{4})-([0-9]{2})-([0-9]{2})\.jsonl")
MAX_TEXT = 200  # characters per string
MAX_ITEMS = 50  # items per list
_TAIL_LIMIT = 1 << 20  # a last line longer than this is unreadable: a new chain starts
_TOKEN = re.compile(r"[A-Za-z0-9_.:*\-]{1,200}")
# Control, format and line/paragraph separator characters: none reaches a line.
_DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})
_OPS = frozenset(OPERATIONS) | {"inspect"}


def file_name(day: datetime.date) -> str:
    return f"odoo-tools-audit-{day.isoformat()}.jsonl"


def line_hash(line: bytes) -> str:
    """The ``prev`` of the line after ``line`` (without its newline)."""
    return hashlib.sha256(line).hexdigest()[:16]


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# --- sanitising --------------------------------------------------------------------------

def clean(value: Any) -> Any:
    """``value`` as a line may hold it: strings without control characters and at most
    200 characters long, lists of at most 50 items, objects with string keys; any
    other type is dropped (``None``)."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        text = "".join(ch for ch in value if unicodedata.category(ch) not in _DROPPED_CATEGORIES)
        return text[:MAX_TEXT]
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in list(value)[:MAX_ITEMS]]
    if isinstance(value, dict):
        return {clean(str(key)): clean(item) for key, item in list(value.items())[:MAX_ITEMS]}
    return None


def touch_text(value: Any) -> str:
    """An ``op:model[:method]`` string with every name checked: an operation that is
    not one, a model or a method that fails its check becomes ``?``, so a value the
    agent put where a name goes is never written."""
    parts = str(value).split(":")
    op = parts[0] if parts[0] in _OPS else "?"
    model = parts[1] if len(parts) > 1 and valid_model(parts[1]) else "?"
    text = f"{op}:{model}"
    if len(parts) > 2:
        text += f":{parts[2] if len(parts) == 3 and valid_method(parts[2]) else '?'}"
    return text


def _touches(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        text = touch_text(value)
        if text not in out:
            out.append(text)
        if len(out) >= MAX_ITEMS:
            break
    return out


def _token(value: Any) -> str | None:
    """A rule, a tool or an exception class name, or ``?`` when it is not a plain token."""
    if value is None or value == "":
        return None
    return value if isinstance(value, str) and _TOKEN.fullmatch(value) else "?"


def record(fields: dict[str, Any]) -> dict[str, Any]:
    """The allowlisted, sanitised form of ``fields``, in the written key order. Keys
    outside ``AUDIT_KEYS`` are dropped, and so are ``None`` values except on the
    ``start`` line, which always shows every key (``"source": null`` without a file)."""
    keep_null = fields.get("event") == "start"
    out: dict[str, Any] = {}
    for key in _KEY_ORDER:
        if key in fields and key in AUDIT_KEYS:
            value = clean(fields[key])
            if value is not None or keep_null:
                out[key] = value
    return out


# --- the log -----------------------------------------------------------------------------

class AuditLog:
    """Writes the audit lines of one server process (see the module docstring)."""

    def __init__(self, mode: str = "stderr", directory: str | None = None, *,
                 retention_days: int = 90,
                 clock: Callable[[], datetime.datetime] = _utc_now) -> None:
        if mode not in ("file", "stderr", "off"):
            raise ValueError(f"unknown audit mode {mode!r}")
        if mode == "file" and not directory:
            raise ValueError("a file audit needs a folder")
        self.mode = mode
        self.directory = directory if mode == "file" else None
        self.retention_days = max(int(retention_days), 0)
        self._clock = clock
        self._lock = threading.Lock()
        self._day: datetime.date | None = None  # the day whose folder and pruning are done
        self._warned = False
        # The chain of the stderr mode, which has no file to read it back from.
        self._seq = 0
        self._prev = GENESIS

    @classmethod
    def from_settings(cls, settings: Any) -> AuditLog:
        """The audit ``ODOO_AUDIT_DIR`` asks for. A value that is not an absolute path
        (a host left ``${CLAUDE_PLUGIN_DATA}`` unresolved) falls back to stderr."""
        raw = (getattr(settings, "audit_dir", "") or "").strip()
        retention = getattr(settings, "audit_retention_days", 90)
        if raw.lower() == "off":
            return cls("off", retention_days=retention)
        if not raw or raw.lower() == "stderr":
            return cls("stderr", retention_days=retention)
        path = os.path.expanduser(raw)
        if "${" in path or not os.path.isabs(path):
            log.warning("ODOO_AUDIT_DIR is not an absolute folder; the audit goes to stderr")
            return cls("stderr", retention_days=retention)
        return cls("file", path, retention_days=retention)

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def describe(self) -> str:
        """Where the lines go, for the startup log."""
        if self.mode == "off":
            return "off (ODOO_AUDIT_DIR=off)"
        if self.mode == "stderr":
            return "the odoo_mcp.audit logger on stderr"
        kept = (f"kept {self.retention_days} days" if self.retention_days
                else "kept until deleted")
        return f"daily files in {self.directory}, {kept}"

    # -- events ------------------------------------------------------------------------
    def start(self, settings: Any, policy: Any) -> None:
        """The ``start`` line: the server, the policy and the acting Odoo user."""
        self.write({
            "event": "start",
            "version": PLUGIN_VERSION,
            "pid": os.getpid(),
            "profile": getattr(policy, "profile_name", None),
            "policy": getattr(policy, "digest", None),
            "source": getattr(policy, "source", None),
            "readonly": bool(getattr(policy, "readonly", False)),
            "error": getattr(policy, "error_code", None),
            "warnings": [code for code, _text in getattr(policy, "warnings", ())],
            "opened": _opened(policy),
            "db": getattr(settings, "db", "") or None,
            "login": getattr(settings, "login", "") or None,
        })

    def call(self, tool: str, *, policy: Any = None, status: str, scope: Any = None,
             exc: BaseException | None = None, layer: str | None = None,
             rule: str | None = None, decision: str | None = None,
             touches: Iterable[Any] | None = None, seconds: float | None = None) -> None:
        """One ``call`` line. ``decision``, ``layer`` and ``rule`` default to what a
        ``PolicyError`` says (a refusal), else to an allowed call; an invalid call
        (``status`` ``invalid``) was never decided."""
        is_policy = isinstance(exc, PolicyError)
        if decision is None and status != "invalid":
            decision = "deny" if is_policy else "allow"
        if is_policy:
            layer = layer or getattr(exc, "layer", None) or None
            rule = rule or getattr(exc, "rule", None) or None
        if touches is None:
            touches = scope.touch_strings() if scope is not None else (
                getattr(exc, "touches", ()) if is_policy else ())
        fields: dict[str, Any] = {
            "event": "call",
            "tool": _token(tool),
            "layer": layer,
            "decision": decision,
            "rule": _token(rule),
            "touches": _touches(touches),
            "status": status,
            "error": _token(type(exc).__name__) if exc is not None else None,
            "policy": getattr(policy, "digest", None) if policy is not None else None,
        }
        if scope is not None:
            fields["effective"] = _touches(getattr(scope, "effective", ()))
            fields["n"] = int(getattr(scope, "n", 0) or 0)
            fields["withheld"] = len(getattr(scope, "withheld", ()) or ())
        if seconds is not None:
            fields["ms"] = max(round(seconds * 1000), 0)
        self.write(fields)

    def refused(self, tool: str, exc: BaseException, *, layer: str, policy: Any = None,
                rule: str | None = None) -> None:
        """A call refused before its handler ran (the tool itself, or Layer A)."""
        self.call(tool, policy=policy, status="refused", exc=exc, layer=layer,
                  rule=rule or getattr(exc, "rule", None), decision="deny")

    # -- writing -----------------------------------------------------------------------
    def write(self, fields: dict[str, Any]) -> None:
        """Write one line; never raises."""
        if self.mode == "off":
            return
        try:
            with self._lock:
                now = self._clock()
                fields = {**fields, "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
                if self.mode == "stderr":
                    self._seq += 1
                    data = _encode(fields, self._seq, self._prev)
                    self._prev = line_hash(data)
                    log.info("%s", data.decode("utf-8"))
                else:
                    self._append(now.date(), fields)
        except Exception as exc:  # the audit never breaks a tool call
            if not self._warned:
                self._warned = True
                log.warning("the audit line could not be written to %s (%s: %s); tool calls "
                            "go on without it", self.directory or "stderr",
                            type(exc).__name__, getattr(exc, "strerror", None) or "failed")

    def _append(self, day: datetime.date, fields: dict[str, Any]) -> None:
        assert self.directory is not None
        if self._day != day:  # at startup, and at the first write after UTC midnight
            os.makedirs(self.directory, mode=0o700, exist_ok=True)
            self.prune(day)
            self._day = day
        path = os.path.join(self.directory, file_name(day))
        flags = (os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
                 | getattr(os, "O_CLOEXEC", 0))
        fd = os.open(path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError(f"{file_name(day)} is not a regular file")
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            seq, prev, cut = _chain_state(path)
            out = b""
            if prev is None:  # an unreadable tail: a new chain, which says so
                if cut:
                    out += b"\n"
                reset = _encode({"event": "chain_reset", "ts": fields["ts"]}, 1, GENESIS)
                out += reset + b"\n"
                seq, prev = 1, line_hash(reset)
            data = _encode(fields, seq + 1, prev)
            _write_all(fd, out + data + b"\n")
        finally:
            os.close(fd)  # also releases the flock

    def prune(self, today: datetime.date) -> list[str]:
        """Remove this folder's daily files older than the retention; only regular
        files whose name is an audit file name. Returns the names removed."""
        if self.mode != "file" or not self.retention_days:
            return []
        assert self.directory is not None
        limit = today - datetime.timedelta(days=self.retention_days)
        removed = []
        for name in sorted(os.listdir(self.directory)):
            match = FILE_PATTERN.fullmatch(name)
            if match is None:
                continue
            try:
                day = datetime.date(*(int(part) for part in match.groups()))
            except ValueError:
                continue
            if day >= limit:
                continue
            path = os.path.join(self.directory, name)
            try:
                if not stat.S_ISREG(os.lstat(path).st_mode):  # a symlink is never followed
                    continue
                os.remove(path)
                removed.append(name)
            except OSError:
                continue
        return removed


def _opened(policy: Any) -> list[dict[str, Any]]:
    try:
        return list(policy.opened_sensitive()) if policy is not None and not policy.locked else []
    except Exception:
        return []


def _encode(fields: dict[str, Any], seq: int, prev: str) -> bytes:
    line = record({**fields, "v": AUDIT_VERSION, "seq": seq, "prev": prev})
    return json.dumps(line, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _write_all(fd: int, data: bytes) -> None:
    while data:
        written = os.write(fd, data)
        data = data[written:]


def _chain_state(path: str) -> tuple[int, str | None, bool]:
    """``(seq, prev, cut)`` for the next line of ``path``: the last line's ``seq`` and
    hash (0 and ``genesis`` for an empty file), or ``prev`` ``None`` when the last line
    cannot be read back; ``cut`` when the file does not end with a newline."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    try:
        size = os.fstat(fd).st_size
        if size == 0:
            return 0, GENESIS, False
        tail = b""
        position = size
        while position > 0 and len(tail) <= _TAIL_LIMIT:
            step = min(8192, position)
            position -= step
            os.lseek(fd, position, os.SEEK_SET)
            chunk = b""
            while len(chunk) < step:
                part = os.read(fd, step - len(chunk))
                if not part:
                    break
                chunk += part
            tail = chunk + tail
            if b"\n" in tail[:-1]:
                break
    finally:
        os.close(fd)
    if not tail.endswith(b"\n"):
        return 0, None, True
    body = tail[:-1]
    newline = body.rfind(b"\n")
    if newline < 0 and position > 0:  # longer than the limit
        return 0, None, False
    last = body[newline + 1:]
    seq = _line_seq(last)
    if seq is None:
        return 0, None, False
    return seq, line_hash(last), False


def _line_seq(line: bytes) -> int | None:
    """The ``seq`` of an audit line, or ``None`` when it is not one."""
    try:
        obj = json.loads(line.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    if not isinstance(obj, dict) or obj.get("v") != AUDIT_VERSION:
        return None
    seq = obj.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        return None
    return seq


# --- verification ------------------------------------------------------------------------

@dataclass(frozen=True)
class Verification:
    """What ``verify()`` found: the number of intact lines, and the first broken line
    (1-based) with why, or ``broken`` ``None`` when the chain holds."""

    lines: int
    broken: int | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.broken is None


def verify(path: str) -> Verification:
    """Check the hash chain of one audit file. Raises ``OSError`` when it cannot be read."""
    with open(path, "rb") as handle:
        data = handle.read()
    if not data:
        return Verification(0)
    lines = data.split(b"\n")
    cut = lines.pop() != b""  # the text after the last newline: empty for a whole file
    prev = GENESIS
    for number, line in enumerate(lines, start=1):
        problem = _check_line(line, number, prev)
        if problem:
            return Verification(number - 1, number, problem)
        prev = line_hash(line)
    if cut:
        return Verification(len(lines), len(lines) + 1,
                            "the last line is not complete (the file was cut, or a write was "
                            "interrupted)")
    return Verification(len(lines))


def _check_line(line: bytes, number: int, prev: str) -> str:
    """Why line ``number`` breaks the chain (``prev`` is the hash it must carry), or ""."""
    try:
        obj = json.loads(line.decode("utf-8"))
    except UnicodeDecodeError:
        return "not UTF-8 text"
    except (ValueError, RecursionError):
        return "not a JSON line"
    if not isinstance(obj, dict) or obj.get("v") != AUDIT_VERSION:
        return "not an odoo-tools audit line"
    unknown = set(obj) - AUDIT_KEYS
    if unknown or obj.get("event") not in EVENTS:
        return "not an odoo-tools audit line (unknown keys or event)"
    if obj.get("event") == "chain_reset":
        return ("a new chain starts here because the line before it could not be read back "
                "(cut or edited)")
    if obj.get("seq") != number:
        return (f"seq is {clean(str(obj.get('seq')))[:20]}, expected {number} (a line was "
                "removed or inserted)")
    if obj.get("prev") != prev:
        if number == 1:
            return "prev is not 'genesis' on the first line (the start of the file was removed)"
        return (f"prev does not match line {number - 1} (that line was edited, or lines were "
                "removed or inserted)")
    return ""


def verify_main(path: str, out: Any) -> int:
    """``--verify-audit FILE``: 0 when the chain holds, 1 at the first broken line,
    2 when the file cannot be read."""
    shown = clean(path)
    try:
        result = verify(path)
    except OSError as exc:
        out.write(f"{shown}: cannot be read ({exc.strerror or type(exc).__name__})\n")
        return 2
    if result.ok:
        out.write(f"{shown}: {result.lines} lines, the hash chain is intact\n")
        return 0
    out.write(f"{shown}: line {result.broken}: {result.reason}. The {result.lines} lines before "
              "it are intact.\n")
    return 1
