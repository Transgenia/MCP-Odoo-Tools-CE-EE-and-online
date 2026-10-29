#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""SessionStart hook: where the Odoo tools run, from this plugin's local diagnostics.

It reads no plugin option and no credential, and no file outside the plugin's own
data folder and the plugin's own folder. Exactly:

  * from the environment: CLAUDE_PLUGIN_DATA and CLAUDE_CODE_ENTRYPOINT, each looked
    up by its name (the environment is never listed or copied);
  * from the event JSON on stdin: "source" and "session_id";
  * under ${CLAUDE_PLUGIN_DATA}: the last records of diagnostics/server.jsonl and of its
    rotated diagnostics/server.jsonl.1 (the MCP server's own log,
    server/src/odoo_mcp/diagnostics.py), with a bounded read of each end; whether
    diagnostics/hook.jsonl exists (none yet: the first session, when only Claude is
    told); whether diagnostics/container-mode exists (/odoo-tools:deploy-local creates
    it in its container mode); and the timestamps of the daily notices;
  * in the plugin's folder: the version in .claude-plugin/plugin.json.

It writes one session_start line to diagnostics/hook.jsonl (the server writes
server.jsonl, so the two never write the same file): the time, the event's source and
session id, the plugin, OS and Python versions, the entrypoint, the server's last
status (none, ok, locked:<E-code> or an error category) with its age in hours, and
whether the container-mode marker exists. Every value is checked against a fixed list
or pattern before it is written: metadata only, like the server's own log.

What it prints, as Claude Code hook JSON:
  * nothing when the container-mode marker exists: the container server is the one in
    use, so the plugin's own server is expected to stay unused;
  * when the last 14 days record neither a successful connection nor a server start
    with its connection settings (URL, database, login and an API key or password):
    "additionalContext" for Claude on every SessionStart, which puts the surface first
    and ends with one "odoo-tools session diagnostics:" line, and a shorter
    "systemMessage" for the user on a new session (source "startup"), at most once a
    day. A configured start is enough: the server runs on this surface with its
    options, so the surface note would only be noise for someone who has not used the
    Odoo tools for a while;
  * when the last server start was locked by the permission policy: the same, with its
    E-code, pointing to odoo_version and docs/policy.md;
  * otherwise nothing.

Standard library only; it runs on Python 3.9 (hooks.json starts it only on 3.9 or
newer), reads a bounded amount and always exits 0: a SessionStart hook must never get
in the way of the session.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import re
import stat
import sys
import time

try:  # POSIX only: Windows appends without the lock
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAG_FOLDER = "diagnostics"
SERVER_FILE, HOOK_FILE, CONTAINER_MARKER = "server.jsonl", "hook.jsonl", "container-mode"
# The limits of the server's log (odoo_mcp/diagnostics.py; a test keeps them equal).
DIAG_VERSION = 1
LINE_LIMIT = 2048  # bytes, the newline included: every line is shorter than this
ROTATE_AT = 256 * 1024  # bytes: a file this large is renamed <name>.1 before the next line
TAIL_BYTES = 64 * 1024  # how much of the end of server.jsonl is read
FRESH = 14 * 24 * 3600  # a successful connection younger than this: nothing to say
SKEW = 3600  # a record up to an hour ahead of this clock still counts
NOTICE_EVERY = 24 * 3600  # seconds between two notices shown to the user
SURFACE_NOTICE, POLICY_NOTICE = "options-notice", "policy-notice"  # the daily timestamps
SOURCES = ("startup", "resume", "clear", "compact")
CATEGORIES = ("config", "auth", "access", "network", "timeout", "tls", "http", "protocol",
              "policy", "other")
ENTRYPOINT = re.compile(r"[A-Za-z0-9_.-]{1,32}")
_TS = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z")
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+~-]{0,31}")
_OS_PART = re.compile(r"[0-9A-Za-z][0-9A-Za-z_.+~-]{0,63}")
_SESSION_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
# A home folder at the start of a path (macOS, Linux, Windows), written as ~ in the
# diagnostics line: no environment variable or file is read to find it.
_HOME = re.compile(r"^(?:/Users/[^/]+|/home/[^/]+|/root|[A-Za-z]:\\Users\\[^\\]+)(?=[/\\]|$)",
                   re.IGNORECASE)
_E_CODE = re.compile(r"E[0-9]{1,2}")

TRANSGENIA = "Transgenia: dev@transgenia.org, WhatsApp +52 55 8034 0405"
# The surface first; then, in this order (docs/product-rules.md, rule 3), the Code tab or
# Claude Code and assisted setup by Transgenia; then where the options are set and the doctor.
SURFACE_CONTEXT = (
    "odoo-tools plugin status: In Cowork and Claude chat this plugin's Odoo tools (odoo_*) "
    "do not run at all, whatever Python or options; only its skills and commands load "
    "there, and nothing is wrong with the user's account, Odoo or Python. Offer the user, "
    "in this order: the Code tab of Claude Desktop (the plugin is synced there when they "
    "sign in with the same account) or Claude Code; and assisted setup by " + TRANSGENIA
    + ". In Claude Code, the connection options are set in /plugin > odoo-tools > "
    "Configure options, where the user types them, never in the chat. "
    "/odoo-tools:odoo-doctor diagnoses. This note comes from the plugin's local "
    "diagnostics, which record neither a successful connection to Odoo nor a server start "
    "with its connection settings in the last 14 days; if the user reaches Odoo through a "
    "separate Odoo connector, it does not apply."
)
SURFACE_MESSAGE = (
    "odoo-tools: In Cowork and Claude chat this plugin's Odoo tools do not run, whatever "
    "Python or options. Open the Code tab of Claude Desktop (the plugin is synced there "
    "when you sign in with the same account) or Claude Code, or ask for assisted setup by "
    + TRANSGENIA + ". In Claude Code, set the connection in /plugin > odoo-tools > "
    "Configure options. /odoo-tools:odoo-doctor diagnoses."
)


def policy_texts(code: str) -> tuple[str, str]:
    """(systemMessage, additionalContext) for a server start the policy locked."""
    shown = code or "E-code unknown"
    message = (
        "odoo-tools: the permission policy locked the Odoo tools at the last server start "
        f"({shown}). Ask Claude to call odoo_version for the reason, and see docs/policy.md "
        "in the plugin; fix the Permission profile or Permission policy file option "
        "(/plugin > odoo-tools > Configure options) or the file, then reconnect with /mcp."
    )
    context = (
        "odoo-tools plugin status: the last start of this plugin's Odoo MCP server was "
        f"locked by its permission policy ({shown}): only odoo_version works, and every "
        "other Odoo tool refuses without contacting Odoo. Call odoo_version to show the user "
        "why; docs/policy.md in the plugin explains each E-code. The user fixes the "
        "Permission profile or Permission policy file option in /plugin > odoo-tools > "
        "Configure options, or the policy file, then reconnects the server with /mcp. Tell "
        "the user; never edit the policy file or change these options yourself."
    )
    return message, context


# --- what it reads ---------------------------------------------------------------------

def _data_folder() -> str | None:
    """${CLAUDE_PLUGIN_DATA} when it is an absolute path, else None."""
    value = (os.environ.get("CLAUDE_PLUGIN_DATA") or "").strip()
    if not value or "${" in value or not os.path.isabs(value):
        return None
    return value


def _entrypoint() -> str | None:
    """CLAUDE_CODE_ENTRYPOINT when it is a short plain token, "other" when it is
    anything else, None when it is unset."""
    raw = os.environ.get("CLAUDE_CODE_ENTRYPOINT")
    if raw is None:
        return None
    return raw if ENTRYPOINT.fullmatch(raw) else "other"


def _read_event() -> dict:
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None or sys.stdin.isatty():
        return {}
    try:
        # Bytes, so json detects the UTF-8 that Claude Code sends whatever the locale's
        # encoding is (Windows pipes default to the ANSI code page).
        raw = stream.read(1 << 20)
        event = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError, RecursionError):
        return {}
    return event if isinstance(event, dict) else {}


def _token(value: object, allowed: tuple[str, ...] = (), pattern: re.Pattern | None = None
           ) -> str | None:
    """``value`` when it is allowed, "other" for any other string, None for no string."""
    if not isinstance(value, str):
        return None
    if value in allowed or (pattern is not None and pattern.fullmatch(value)):
        return value
    return "other"


def _plugin_version() -> str:
    try:
        path = os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json")
        with open(path, "rb") as handle:
            manifest = json.loads(handle.read(1 << 20))
    except (OSError, ValueError, RecursionError):
        return "unknown"
    version = manifest.get("version") if isinstance(manifest, dict) else None
    return version if isinstance(version, str) and _VERSION.fullmatch(version) else "unknown"


def _os_part(value: object) -> str:
    if not value:
        return "unknown"
    return value if isinstance(value, str) and _OS_PART.fullmatch(value) else "other"


def _seconds(ts: object) -> float | None:
    match = _TS.fullmatch(ts) if isinstance(ts, str) else None
    if match is None:
        return None
    try:
        when = datetime.datetime(*(int(part) for part in match.groups()),
                                 tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    return when.timestamp()


def _tail(path: str) -> list[dict]:
    """The records at the end of the server's log, oldest first: a bounded read, and a
    symbolic link is never followed."""
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
             | getattr(os, "O_BINARY", 0))
    try:
        fd = os.open(path, flags)
    except OSError:
        return []
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return []
        start = max(info.st_size - TAIL_BYTES, 0)
        os.lseek(fd, start, os.SEEK_SET)
        data = b""
        while len(data) < info.st_size - start:
            part = os.read(fd, info.st_size - start - len(data))
            if not part:
                break
            data += part
    except OSError:
        return []
    finally:
        os.close(fd)
    lines = data.split(b"\n")
    if start > 0:
        lines = lines[1:]  # the read starts inside a line
    records = []
    for line in lines:
        try:
            obj = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if (isinstance(obj, dict) and type(obj.get("v")) is int and obj["v"] == DIAG_VERSION
                and _seconds(obj.get("ts")) is not None):
            records.append(obj)
    return records


# --- what it decides -------------------------------------------------------------------

def _locked_code(record: dict) -> str | None:
    """None when this start record is not locked; else its E-code ("" when unreadable)."""
    policy = record.get("policy")
    if not isinstance(policy, dict) or policy.get("locked") is not True:
        return None
    code = policy.get("code")
    return code if isinstance(code, str) and _E_CODE.fullmatch(code) else ""


def _status(record: dict) -> str | None:
    """The status a record settles: a connection outcome, or a locked start."""
    event = record.get("event")
    if event == "connect":
        if record.get("ok") is True:
            return "ok"
        category = record.get("category")
        return category if category in CATEGORIES else "other"
    if event == "start":
        code = _locked_code(record)
        if code is not None:
            return f"locked:{code}" if code else "locked"
    return None


def _configured(record: dict) -> bool:
    """Whether this start record had every connection setting: URL, database, login, and
    an API key or a password (presence only: the server never records a value)."""
    settings, kind = record.get("settings"), record.get("credential")
    return (isinstance(settings, dict)
            and all(settings.get(name) is True for name in ("url", "db", "login"))
            and isinstance(kind, str) and kind not in ("", "none"))


def server_state(records: list[dict], now: float) -> tuple[str, int | None, bool, str | None]:
    """(last status, its age in hours, whether the tools ran or were set up here lately,
    the E-code when the last start was locked) from the server's records, oldest first.
    Lately: a successful connection, or a newest start with every connection setting,
    in the last 14 days."""
    last, age = "none", None
    fresh = False
    locked: str | None = None
    newest_start = True
    for record in reversed(records):
        when = _seconds(record.get("ts"))
        if when is None:
            continue
        if (record.get("event") == "connect" and record.get("ok") is True
                and -SKEW <= now - when < FRESH):
            fresh = True
        if record.get("event") == "start" and newest_start:
            newest_start = False
            locked = _locked_code(record)
            if _configured(record) and -SKEW <= now - when < FRESH:
                fresh = True
        if last == "none":
            status = _status(record)
            if status is not None:
                last, age = status, min(max(int((now - when) // 3600), 0), 10**7)
    return last, age, fresh, locked


def _folder(path: str, mode: int = 0o777) -> None:
    """Create one folder unless it exists. Unlike os.makedirs, it never looks at the
    parent folder: the hook touches nothing above the plugin's data folder."""
    try:
        os.mkdir(path, mode)
    except FileExistsError:
        pass


def _notice_due(data: str | None, now: float, name: str) -> bool:
    """True at most once per NOTICE_EVERY, tracked by a timestamp file in the plugin's
    data folder. Without a usable folder the notice is always due."""
    if not data:
        return True
    marker = os.path.join(data, name)
    try:
        # A marker dated in the future (clock set back, restored backup, synced home)
        # counts as due, so it cannot silence the notice for longer than a day.
        if 0 <= now - os.stat(marker, follow_symlinks=False).st_mtime < NOTICE_EVERY:
            return False
    except OSError:
        pass
    try:
        _folder(data)
        flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(
            os, "O_NONBLOCK", 0)
        fd = os.open(marker, flags, 0o600)
        try:
            os.utime(fd if os.utime in os.supports_fd else marker)
        finally:
            os.close(fd)
    except OSError:
        pass
    return True


def _shown(text: str) -> str:
    return "".join(ch if ch.isprintable() else "?" for ch in text)


def diagnostics_line(entrypoint: str | None, last: str, age: int | None,
                     diag: str | None) -> str:
    # The home folder is written as ~: the line reaches Claude and support reports, which
    # need the folder but not the name of the account on the computer.
    shown = _shown(_HOME.sub("~", diag, count=1)) if diag else "none"
    return (f"odoo-tools session diagnostics: entrypoint={entrypoint or 'none'} "
            f"server_last={last} age_h={'none' if age is None else age} "
            f"diag_dir={shown}")


def build_output(*, surface: bool, locked: str | None, line: str, surface_message: bool,
                 policy_message: bool) -> dict | None:
    """The hook JSON: the context for Claude, and the user's message when it is due."""
    contexts, messages = [], []
    if surface:
        contexts.append(SURFACE_CONTEXT)
        if surface_message:
            messages.append(SURFACE_MESSAGE)
    if locked is not None:
        message, context = policy_texts(locked)
        contexts.append(context)
        if policy_message:
            messages.append(message)
    if not contexts:
        return None
    output: dict = {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                           "additionalContext": " ".join(contexts) + "\n" + line}}
    if messages:
        output["systemMessage"] = "\n".join(messages)
    return output


# --- what it writes ----------------------------------------------------------------------

def _open_for_append(path: str) -> int:
    flags = (os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_CLOEXEC", 0))
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("not a regular file")
        if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
            try:
                os.fchmod(fd, 0o600)  # a looser file is tightened, as the server does
            except OSError:
                pass
    except BaseException:
        os.close(fd)
        raise
    return fd


def append_line(directory: str, name: str, data: bytes) -> None:
    """Append one line, rotating the file to <name>.1 once it has reached ROTATE_AT, as
    the server does (under an exclusive flock where the platform has it). Raises OSError."""
    _folder(os.path.dirname(directory))  # the data folder, normally there already
    _folder(directory, 0o700)
    if os.path.islink(directory):  # O_NOFOLLOW guards the file name only
        raise OSError("the diagnostics folder is a symbolic link")
    path = os.path.join(directory, name)
    rotate = True
    for _attempt in range(4):
        fd = _open_for_append(path)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            info = os.fstat(fd)
            try:
                current = os.stat(path, follow_symlinks=False)
            except OSError:
                continue
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                continue  # rotated by another process while this one waited: reopen
            if rotate and info.st_size >= ROTATE_AT:
                rotate = False
                if fcntl is None:  # Windows renames a file only once it is closed
                    os.close(fd)
                    fd = -1
                try:
                    os.replace(path, path + ".1")
                    replaced = True
                except OSError:
                    replaced = False
                if replaced or fd < 0:
                    continue
            while data:
                data = data[os.write(fd, data):]
            return
        finally:
            if fd >= 0:
                os.close(fd)
    raise OSError(f"{name} kept changing while it was appended to")


def session_record(now: float, event: dict, entrypoint: str | None, last: str,
                   age: int | None, container: bool) -> dict:
    record: dict = {"v": DIAG_VERSION,
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                    "event": "session_start"}
    source = _token(event.get("source"), SOURCES)
    if source is not None:
        record["source"] = source
    session_id = _token(event.get("session_id"), pattern=_SESSION_ID)
    if session_id is not None:
        record["session_id"] = session_id
    record["plugin"] = _plugin_version()
    record["os"] = {"system": _os_part(platform.system()),
                    "release": _os_part(platform.release()),
                    "machine": _os_part(platform.machine())}
    python = platform.python_version()
    record["python"] = python if _VERSION.fullmatch(python) else "other"
    if entrypoint is not None:
        record["entrypoint"] = entrypoint
    record["server_last"] = last
    if age is not None:
        record["age_h"] = age
    record["container"] = container
    return record


def _write_record(diag: str, record: dict) -> None:
    try:
        data = json.dumps(record, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        if len(data) + 1 < LINE_LIMIT:
            append_line(diag, HOOK_FILE, data + b"\n")
    except (OSError, ValueError):
        pass  # the record is a nicety: never a reason to fail


def main() -> int:
    try:
        event = _read_event()
        source = _token(event.get("source"), SOURCES)
        data = _data_folder()
        diag = os.path.join(data, DIAG_FOLDER) if data else None
        now = time.time()
        # The rotated file first: the server may have just started a new server.jsonl.
        records = ([*_tail(os.path.join(diag, SERVER_FILE + ".1")),
                    *_tail(os.path.join(diag, SERVER_FILE))] if diag else [])
        # No hook record yet: the first session after an install or an upgrade, when this
        # session's server may not have written its start yet. Claude is told, the user is
        # not, so a set-up Claude Code user is not sent to Cowork's note on day one.
        first_session = bool(diag) and not any(
            os.path.lexists(os.path.join(diag, HOOK_FILE + suffix)) for suffix in ("", ".1"))
        last, age, fresh, locked = server_state(records, now)
        container = bool(diag) and os.path.lexists(os.path.join(diag, CONTAINER_MARKER))
        entrypoint = _entrypoint()
        if diag:
            _write_record(diag, session_record(now, event, entrypoint, last, age, container))
        if container:
            return 0  # the container server from /odoo-tools:deploy-local is in use
        surface = not fresh
        if not surface and locked is None:
            return 0
        # Without the data folder a notice cannot be limited to once a day: Claude only.
        startup = source in (None, "startup") and bool(data) and not first_session
        output = build_output(
            surface=surface, locked=locked, line=diagnostics_line(entrypoint, last, age, diag),
            surface_message=startup and surface and _notice_due(data, now, SURFACE_NOTICE),
            policy_message=startup and locked is not None and _notice_due(data, now,
                                                                          POLICY_NOTICE),
        )
        if output:
            sys.stdout.write(json.dumps(output))
    except Exception:  # a notice must never break the session
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
