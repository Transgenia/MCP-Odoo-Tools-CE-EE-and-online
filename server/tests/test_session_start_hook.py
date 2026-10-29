# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""hooks/session_start.py: the SessionStart notice, from the plugin's local diagnostics.

The hook runs as Claude Code runs it: a subprocess with the event JSON on stdin (UTF-8
bytes) and CLAUDE_PLUGIN_ROOT and CLAUDE_PLUGIN_DATA set. It replaces 1.5.0's
check_options.py, which read plugin options from its environment, loaded the policy
file and looked for the container mode's credentials file in the home folder: it may
read only CLAUDE_PLUGIN_DATA and CLAUDE_CODE_ENTRYPOINT, the "source" and "session_id"
of the event, and files under the plugin's data folder and its own folder.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from odoo_mcp import diagnostics
from odoo_mcp.diagnostics import HOOK_RECORDS, LINE_LIMIT, clean_record

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "session_start.py"
POSIX_ONLY = pytest.mark.skipif(os.name == "nt" or shutil.which("sh") is None,
                                reason="runs the hooks.json shell command with sh")
POSIX_MODES = pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
SESSION = "5a1c3d9e-0000-4c4c-8888-123456789abc"
# The names a hook must never read, and the values that must never come out. The
# option prefix is built here, in the tests, so it appears nowhere under hooks/.
OPTION = "CLAUDE_PLUGIN_" + "OPTION_"
CANARIES = {
    OPTION + "ODOO_URL": "https://canary-host.invalid",
    OPTION + "ODOO_DB": "canary-db",
    OPTION + "ODOO_LOGIN": "canary-login@example.com",
    OPTION + "ODOO_API_KEY": "sk-CANARY-OPTION-KEY",
    OPTION + "ODOO_PASSWORD": "pw-CANARY-OPTION",
    OPTION + "ODOO_POLICY": "builder",
    OPTION + "ODOO_POLICY_FILE": "/canary/policy.json",
    "ODOO_API_KEY": "sk-CANARY-ENV-KEY",
    "ODOO_PASSWORD": "pw-CANARY-ENV",
    "ODOO_HTTP_BEARER": "bearer-CANARY",
    "ODOO_URL": "https://user:CANARY@canary-env.invalid",
}
FIRST_MESSAGE = (
    "odoo-tools: python3 is not runnable on this computer. In Claude Code the Odoo MCP "
    "server needs Python 3.9+ as python3 (README, Requirements). In Cowork and Claude chat "
    "the Odoo tools do not run with or without Python: use the Code tab of Claude Desktop, "
    "or contact Transgenia (dev@transgenia.org, WhatsApp +52 55 8034 0405)."
)
# The surface notice, in its order.
# The order of docs/product-rules.md, rule 3: the Code tab, then Transgenia's assisted
# setup; then the Claude Code options and the doctor.
SURFACE = ("In Cowork and Claude chat", "Code tab of Claude Desktop",
           "assisted setup by Transgenia: dev@transgenia.org, WhatsApp +52 55 8034 0405",
           "/plugin > odoo-tools > Configure options", "/odoo-tools:odoo-doctor diagnoses")
LINE = re.compile(r"^odoo-tools session diagnostics: entrypoint=(\S+) server_last=(\S+) "
                  r"age_h=(\S+) diag_dir=(.+)$")


def _data(tmp_path: Path) -> Path:
    return tmp_path / "data"


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "USERPROFILE": str(home),
           "CLAUDE_PLUGIN_ROOT": str(ROOT), "CLAUDE_PLUGIN_DATA": str(_data(tmp_path)),
           **CANARIES}
    env.update(extra)
    return env


def _event(source: Any = "startup", cwd: str = "/tmp/project",
           session_id: Any = SESSION) -> bytes:
    payload = {"hook_event_name": "SessionStart", "source": source, "cwd": cwd,
               "session_id": session_id, "transcript_path": "/tmp/CANARY-transcript.jsonl"}
    # Claude Code writes UTF-8 without escaping non-ASCII characters.
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _seen_before(tmp_path: Path) -> None:
    """An earlier session's record, as after the first session of 1.5.1 on this computer."""
    folder = _data(tmp_path) / "diagnostics"
    if _data(tmp_path).is_dir() or not _data(tmp_path).exists():
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "hook.jsonl"
        if not path.exists():
            path.write_text(json.dumps({"v": 1, "ts": _ts(48), "event": "session_start",
                                        "plugin": "1.5.1", "server_last": "none"}) + "\n")


def _run_full(tmp_path: Path, source: Any = "startup", stdin: bytes | None = None, *,
              first: bool = False, **extra: str) -> tuple[int, str, str]:
    if not first:
        _seen_before(tmp_path)
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(HOOK)], input=_event(source) if stdin is None else stdin,
        env=_env(tmp_path, **extra), capture_output=True, timeout=30, check=False)
    assert time.monotonic() - started < 10  # finishes fast (hooks.json allows 10 s)
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


def _run(tmp_path: Path, source: Any = "startup", stdin: bytes | None = None, *,
         first: bool = False, **extra: str) -> tuple[int, str]:
    code, out, err = _run_full(tmp_path, source, stdin, first=first, **extra)
    assert err == ""
    return code, out


def _payload(tmp_path: Path, source: Any = "startup", *, first: bool = False,
             **extra: str) -> dict[str, Any]:
    code, out = _run(tmp_path, source, first=first, **extra)
    assert code == 0 and out
    return json.loads(out)


def _ts(hours_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours_ago * 3600))


def start(hours_ago: float, code: str | None = None, *, configured: bool = False,
          credential: str = "api_key", **settings: bool) -> dict[str, Any]:
    policy = ({"profile": "standard", "locked": True, "code": code} if code else
              {"profile": "standard", "digest": "0123456789ab", "locked": False})
    record = {"v": 1, "ts": _ts(hours_ago), "event": "start", "pid": 7, "policy": policy}
    if configured:
        record["settings"] = {"url": True, "db": True, "login": True, **settings}
        record["credential"] = credential
    return record


def connect(hours_ago: float, category: str | None = None) -> dict[str, Any]:
    if category:
        return {"v": 1, "ts": _ts(hours_ago), "event": "connect", "pid": 7, "ok": False,
                "category": category}
    return {"v": 1, "ts": _ts(hours_ago), "event": "connect", "pid": 7, "ok": True,
            "transport": "jsonrpc", "odoo_major": 18}


def _server_log(tmp_path: Path, records: list[Any]) -> None:
    folder = _data(tmp_path) / "diagnostics"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "server.jsonl").write_text(
        "".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in records))


def _marker(tmp_path: Path) -> None:
    folder = _data(tmp_path) / "diagnostics"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "container-mode").write_bytes(b"")


def _hook_lines(tmp_path: Path) -> list[dict[str, Any]]:
    path = _data(tmp_path) / "diagnostics" / "hook.jsonl"
    out = []
    for line in path.read_bytes().splitlines():
        assert len(line) + 1 < LINE_LIMIT
        record = json.loads(line.decode("ascii"))
        assert clean_record(HOOK_RECORDS, record) == record  # only what the allowlist keeps
        out.append(record)
    return out


def _line(context: str) -> re.Match[str]:
    match = LINE.match(context.splitlines()[-1])
    assert match, context
    return match


def _in_order(text: str, parts: tuple[str, ...]) -> None:
    positions = [text.find(part) for part in parts]
    assert -1 not in positions and positions == sorted(positions), (positions, text)


# --- the states ----------------------------------------------------------------------------

def test_no_record_puts_the_surface_first(tmp_path: Path) -> None:
    payload = _payload(tmp_path, CLAUDE_CODE_ENTRYPOINT="claude-desktop")
    context = payload["hookSpecificOutput"]["additionalContext"]
    message = payload["systemMessage"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert context.startswith("odoo-tools plugin status: In Cowork and Claude chat")
    assert message.startswith("odoo-tools: In Cowork and Claude chat")
    _in_order(context, SURFACE)
    _in_order(message, SURFACE)
    assert "whatever Python or options" in message and len(message) < len(context)
    assert _line(context).groups() == ("claude-desktop", "none", "none",
                                       str(_data(tmp_path) / "diagnostics"))
    for text in (message, context):
        assert len(text) < 10_000  # Claude Code's cap per field
        assert text.isascii()


def test_a_recent_connection_is_silent(tmp_path: Path) -> None:
    _server_log(tmp_path, [start(30), connect(29), start(1)])
    assert _run(tmp_path) == (0, "")
    # A failure after a success of this fortnight: the tools run here, nothing to say.
    _server_log(tmp_path, [start(30), connect(29), start(1), connect(1, "network")])
    assert _run(tmp_path) == (0, "")


def test_a_stale_connection_speaks_again(tmp_path: Path) -> None:
    _server_log(tmp_path, [start(15 * 24 + 1), connect(15 * 24)])
    payload = _payload(tmp_path)
    assert "systemMessage" in payload
    assert _line(payload["hookSpecificOutput"]["additionalContext"]).group(2, 3) == (
        "ok", "360")


def test_a_recent_configured_start_is_silent(tmp_path: Path) -> None:
    # The server started here with every connection setting: the tools run on this
    # surface, even if nobody used them in the last 14 days.
    _server_log(tmp_path, [start(20 * 24), connect(20 * 24), start(48, configured=True)])
    assert _run(tmp_path) == (0, "")
    _server_log(tmp_path, [start(2, configured=True, credential="password")])
    assert _run(tmp_path) == (0, "")


@pytest.mark.parametrize("records", [
    [start(15 * 24, configured=True)],  # set up, but longer ago than 14 days
    # only the newest start counts: here it lacks a setting
    [start(5 * 24, configured=True), start(2, configured=True, url=False)],
    [start(2, configured=True, credential="none")],  # no API key or password
    [start(2, configured=True, login="yes")],  # not a boolean: not trusted
])
def test_an_incomplete_or_old_start_still_speaks(tmp_path: Path, records: list[Any]) -> None:
    _server_log(tmp_path, records)
    payload = _payload(tmp_path)
    assert payload["hookSpecificOutput"]["additionalContext"].startswith(
        "odoo-tools plugin status: In Cowork and Claude chat")


def test_a_locked_configured_start_says_only_the_lock(tmp_path: Path) -> None:
    _server_log(tmp_path, [start(1, code="E8", configured=True)])
    payload = _payload(tmp_path)
    for text in (payload["systemMessage"], payload["hookSpecificOutput"]["additionalContext"]):
        assert "(E8)" in text and "Cowork" not in text


def test_the_first_session_tells_claude_but_not_the_user(tmp_path: Path) -> None:
    # Right after an install or an upgrade this session's server may not have written
    # its start yet, so a set-up Claude Code user would get Cowork's note: Claude only.
    payload = _payload(tmp_path, first=True)
    assert "systemMessage" not in payload
    assert payload["hookSpecificOutput"]["additionalContext"].startswith(
        "odoo-tools plugin status: In Cowork and Claude chat")
    assert not (_data(tmp_path) / "options-notice").exists()  # the daily slot is kept
    assert "systemMessage" in _payload(tmp_path)  # the next session tells the user


def test_the_rotated_server_log_counts(tmp_path: Path) -> None:
    # The server has just rotated server.jsonl: the fresh records are in server.jsonl.1.
    _server_log(tmp_path, [start(2, configured=True), connect(2)])
    folder = _data(tmp_path) / "diagnostics"
    (folder / "server.jsonl").rename(folder / "server.jsonl.1")
    (folder / "server.jsonl").write_text(json.dumps(
        {"v": 1, "ts": _ts(1), "event": "stop", "pid": 7, "uptime_s": 5}) + "\n")
    assert _run(tmp_path) == (0, "")


@POSIX_ONLY
def test_a_symlinked_diagnostics_folder_is_not_written_through(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _data(tmp_path).mkdir()
    (_data(tmp_path) / "diagnostics").symlink_to(elsewhere, target_is_directory=True)
    code, _ = _run(tmp_path, first=True)
    assert code == 0 and list(elsewhere.iterdir()) == []


@pytest.mark.parametrize("folder, shown", [
    ("/Users/someone/.claude/plugins/data/x/diagnostics", "~/.claude/plugins/data/x/diagnostics"),
    ("/home/someone/.claude/plugins/data/x/diagnostics", "~/.claude/plugins/data/x/diagnostics"),
    ("C:\\Users\\Someone\\.claude\\plugins\\data\\x\\diagnostics",
     "~\\.claude\\plugins\\data\\x\\diagnostics"),
    ("/srv/claude/data/diagnostics", "/srv/claude/data/diagnostics"),
])
def test_the_diagnostics_line_writes_the_home_folder_as_a_tilde(
        monkeypatch: pytest.MonkeyPatch, folder: str, shown: str) -> None:
    hook = _load_hook(monkeypatch)
    line = hook.diagnostics_line("cli", "none", None, folder)
    assert line.endswith(f"diag_dir={shown}") and "omeone" not in line


def test_the_last_failure_is_reported_by_category(tmp_path: Path) -> None:
    _server_log(tmp_path, [start(3), connect(2, "auth")])
    context = _payload(tmp_path)["hookSpecificOutput"]["additionalContext"]
    assert _line(context).group(1, 2, 3) == ("none", "auth", "2")


def test_a_locked_start_names_the_e_code(tmp_path: Path) -> None:
    _server_log(tmp_path, [start(5), connect(5), start(0.1, code="E8")])
    payload = _payload(tmp_path)
    message, context = payload["systemMessage"], payload["hookSpecificOutput"]["additionalContext"]
    for text in (message, context):
        assert "(E8)" in text and "odoo_version" in text and "docs/policy.md" in text
        assert "Cowork" not in text  # a connection succeeded this fortnight
    assert "never edit the policy file" in context
    assert _line(context).group(2, 3) == ("locked:E8", "0")


def test_a_locked_start_without_any_connection_says_both(tmp_path: Path) -> None:
    _server_log(tmp_path, [start(1, code="E2")])
    payload = _payload(tmp_path)
    context = payload["hookSpecificOutput"]["additionalContext"]
    _in_order(context, (*SURFACE, "(E2)", "odoo-tools session diagnostics:"))
    surface, locked = payload["systemMessage"].split("\n")
    assert surface.startswith("odoo-tools: In Cowork") and "(E2)" in locked


def test_a_newer_unlocked_start_clears_the_lock(tmp_path: Path) -> None:
    _server_log(tmp_path, [start(3, code="E8"), start(1), connect(1)])
    assert _run(tmp_path) == (0, "")


@pytest.mark.parametrize("records", [[], [start(1, code="E8")], [start(400), connect(399)]])
def test_container_mode_is_silent(tmp_path: Path, records: list[Any]) -> None:
    _server_log(tmp_path, records)
    _marker(tmp_path)
    assert _run(tmp_path) == (0, "")
    assert not (_data(tmp_path) / "options-notice").exists()
    assert _hook_lines(tmp_path)[-1]["container"] is True


def test_records_it_cannot_trust_are_ignored(tmp_path: Path) -> None:
    _server_log(tmp_path, [
        "not json", '{"v": 1}', {"v": True, "ts": _ts(1), "event": "connect", "ok": True},
        {"v": 2, "ts": _ts(1), "event": "connect", "ok": True},
        {"v": 1, "ts": "yesterday", "event": "connect", "ok": True},
        {"v": 1, "ts": _ts(1), "event": "connect", "ok": "yes"},
        {"v": 1, "ts": _ts(-48), "event": "connect", "ok": True},  # two days ahead: no
        {"v": 1, "ts": _ts(1), "event": "connect", "ok": False,
         "category": "https://CANARY.invalid"},
    ])
    payload = _payload(tmp_path)
    assert _line(payload["hookSpecificOutput"]["additionalContext"]).group(2) == "other"
    assert "CANARY" not in json.dumps(payload)


def test_a_long_log_is_read_from_its_end(tmp_path: Path) -> None:
    filler = [start(30 * 24) for _ in range(2000)]  # far more than the bounded read
    _server_log(tmp_path, [connect(31 * 24), *filler, connect(2)])
    assert (_data(tmp_path) / "diagnostics" / "server.jsonl").stat().st_size > 128 * 1024
    assert _run(tmp_path) == (0, "")


# --- the daily notice ------------------------------------------------------------------------

def test_the_user_notice_is_shown_once_a_day(tmp_path: Path) -> None:
    first = _payload(tmp_path)
    second = _payload(tmp_path)
    assert "systemMessage" in first and "systemMessage" not in second
    assert "additionalContext" in second["hookSpecificOutput"]  # Claude still knows
    marker = _data(tmp_path) / "options-notice"
    assert marker.read_bytes() == b""  # a timestamp only
    old = marker.stat().st_mtime - 25 * 3600
    os.utime(marker, (old, old))
    assert "systemMessage" in _payload(tmp_path)


def test_a_marker_from_the_future_does_not_silence_the_notice(tmp_path: Path) -> None:
    _payload(tmp_path)
    marker = _data(tmp_path) / "options-notice"
    future = marker.stat().st_mtime + 10 * 24 * 3600  # clock set back, restored backup
    os.utime(marker, (future, future))
    assert "systemMessage" in _payload(tmp_path)


@pytest.mark.parametrize("source", ["resume", "clear", "compact", "fork"])
def test_only_a_new_session_shows_the_user_notice(tmp_path: Path, source: str) -> None:
    payload = _payload(tmp_path, source=source)
    assert "systemMessage" not in payload
    assert "In Cowork" in payload["hookSpecificOutput"]["additionalContext"]
    assert not (_data(tmp_path) / "options-notice").exists()  # the daily slot is kept


def test_the_policy_notice_has_its_own_daily_slot(tmp_path: Path) -> None:
    _server_log(tmp_path, [start(2), connect(2), start(1, code="E8")])
    assert "(E8)" in _payload(tmp_path)["systemMessage"]
    assert "systemMessage" not in _payload(tmp_path)
    assert (_data(tmp_path) / "policy-notice").exists()
    assert not (_data(tmp_path) / "options-notice").exists()


def test_a_non_ascii_cwd_survives_a_windows_code_page(tmp_path: Path) -> None:
    # Windows pipes decode text with the ANSI code page; the hook must read UTF-8 bytes.
    stdin = _event("resume", cwd="C:\\Users\\Ángel\\LOGÍSTICA\\odoo")
    code, out = _run(tmp_path, stdin=stdin, PYTHONIOENCODING="cp1252")
    assert code == 0 and "systemMessage" not in json.loads(out)
    assert _hook_lines(tmp_path)[-1]["source"] == "resume"


def test_an_unreadable_event_counts_as_a_new_session(tmp_path: Path) -> None:
    code, out = _run(tmp_path, stdin=b"not json")
    assert code == 0 and "systemMessage" in json.loads(out)
    record = _hook_lines(tmp_path)[0]
    assert "source" not in record and "session_id" not in record


def test_an_unwritable_data_folder_does_not_break_the_hook(tmp_path: Path) -> None:
    _data(tmp_path).write_text("a file where the folder should be")
    code, out = _run(tmp_path)
    payload = json.loads(out)
    assert code == 0 and "systemMessage" not in payload
    assert payload["hookSpecificOutput"]["additionalContext"].startswith("odoo-tools plugin")


@pytest.mark.parametrize("value", ["", "relative/data", "${CLAUDE_PLUGIN_DATA}"])
def test_without_a_data_folder_nothing_is_written(tmp_path: Path, value: str) -> None:
    work = tmp_path / "cwd"
    work.mkdir()
    env = _env(tmp_path, CLAUDE_PLUGIN_DATA=value)
    result = subprocess.run([sys.executable, str(HOOK)], input=_event(), env=env, cwd=work,
                            capture_output=True, timeout=30, check=True)
    payload = json.loads(result.stdout)
    # Without a folder a notice cannot be kept to once a day: Claude only, every time.
    assert "systemMessage" not in payload
    assert _line(payload["hookSpecificOutput"]["additionalContext"]).group(4) == "none"
    assert list(work.iterdir()) == [] and not _data(tmp_path).exists()


# --- the record it writes ------------------------------------------------------------------

def test_one_metadata_record_per_session_start(tmp_path: Path) -> None:
    _server_log(tmp_path, [start(3), connect(3)])
    _run(tmp_path, first=True, CLAUDE_CODE_ENTRYPOINT="cli")
    _run(tmp_path, source="compact", stdin=_event("compact", session_id="not a uuid!"),
         CLAUDE_CODE_ENTRYPOINT="has spaces")
    _run(tmp_path, source="weird")
    first, second, third = _hook_lines(tmp_path)
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert list(first) == ["v", "ts", "event", "source", "session_id", "plugin", "os",
                           "python", "entrypoint", "server_last", "age_h", "container"]
    assert first == {**first, "v": 1, "event": "session_start", "source": "startup",
                     "session_id": SESSION, "plugin": plugin, "entrypoint": "cli",
                     "server_last": "ok", "age_h": 3, "container": False}
    assert first["python"] == ".".join(map(str, sys.version_info[:3])) or first["python"]
    assert set(first["os"]) == {"system", "release", "machine"}
    assert abs(time.time() - time.mktime(time.strptime(first["ts"], "%Y-%m-%dT%H:%M:%SZ"))
               + time.timezone) < 600
    assert (second["source"], second["session_id"], second["entrypoint"]) == (
        "compact", "other", "other")
    assert third["source"] == "other" and "entrypoint" not in third
    text = (_data(tmp_path) / "diagnostics" / "hook.jsonl").read_text()
    for value in CANARIES.values():
        assert value not in text
    assert "CANARY" not in text and "/tmp/project" not in text


@POSIX_MODES
def test_the_record_files_are_owner_only(tmp_path: Path) -> None:
    _run(tmp_path, first=True)  # the hook creates the folder
    folder = _data(tmp_path) / "diagnostics"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE((folder / "hook.jsonl").stat().st_mode) == 0o600
    (folder / "hook.jsonl").chmod(0o644)
    _run(tmp_path)
    assert stat.S_IMODE((folder / "hook.jsonl").stat().st_mode) == 0o600


def test_a_full_record_file_is_rotated(tmp_path: Path) -> None:
    folder = _data(tmp_path) / "diagnostics"
    folder.mkdir(parents=True)
    old = (json.dumps({"v": 1, "ts": _ts(1), "event": "session_start"}) + "\n").encode()
    (folder / "hook.jsonl").write_bytes(old * (diagnostics.ROTATE_AT // len(old) + 1))
    _run(tmp_path)
    assert (folder / "hook.jsonl.1").stat().st_size >= diagnostics.ROTATE_AT
    assert len(_hook_lines(tmp_path)) == 1


def _load_hook(monkeypatch: pytest.MonkeyPatch) -> Any:
    # No __pycache__ in the plugin's hooks folder: it ships as it is.
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec = importlib.util.spec_from_file_location("odoo_tools_session_start", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_hook_keeps_the_limits_of_the_server_log(monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _load_hook(monkeypatch)
    for name in ("DIAG_VERSION", "LINE_LIMIT", "ROTATE_AT", "TAIL_BYTES", "SERVER_FILE",
                 "HOOK_FILE", "CONTAINER_MARKER", "CATEGORIES", "SOURCES"):
        assert getattr(hook, name) == getattr(diagnostics, name), name
    assert hook.ENTRYPOINT.pattern == diagnostics.ENTRYPOINT.pattern


# --- what it may read --------------------------------------------------------------------------

def test_no_file_under_hooks_names_an_option_or_a_credential() -> None:
    # The plugin directory's policy scan reads the text of hook scripts.
    forbidden = ("CLAUDE_PLUGIN_OPTION", "user_config", "ODOO_API_KEY", "ODOO_PASSWORD",
                 "odoo.env")
    for path in (ROOT / "hooks").iterdir():
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for word in forbidden:
                assert word not in text, f"{path.name}: {word}"
            lowered = text.lower()
            for word in ("plugin_option", "api_key", "odoo_password", "http_bearer",
                         ".odoo-tools"):
                assert word not in lowered, f"{path.name}: {word}"
    assert not (ROOT / "hooks" / "check_options.py").exists()


# Runs the hook with os.environ replaced by a mapping that records every key looked up
# and every bulk read (iteration, items, copy...), records the paths it opens, stats or
# creates, and which odoo_mcp modules got imported; then writes that record to a file.
_SPY = r"""
import json, os, runpy, sys
seen, bulk, touched, active = [], [], [], [True]
def note(key):
    if active[0]:
        seen.append(key.decode("latin-1") if isinstance(key, bytes) else str(key))
class Spy(dict):
    def __getitem__(self, key):
        note(key); return dict.__getitem__(self, key)
    def get(self, key, default=None):
        note(key); return dict.get(self, key, default)
    def __contains__(self, key):
        note(key); return dict.__contains__(self, key)
    def setdefault(self, key, default=None):
        note(key); return dict.setdefault(self, key, default)
    def pop(self, key, *default):
        note(key); return dict.pop(self, key, *default)
for name in ("__iter__", "items", "keys", "values", "copy", "__repr__", "__len__"):
    def bulk_read(self, *a, _n=name, _f=getattr(dict, name)):
        if active[0]:
            bulk.append(_n)
        return _f(self, *a)
    setattr(Spy, name, bulk_read)
os.environ = Spy(os.environ)
if hasattr(os, "environb"):
    os.environb = Spy(os.environb)
def path_of(value):
    if isinstance(value, int):
        return None
    try:
        return os.fsdecode(value)
    except TypeError:
        return None
EVENTS = {"open", "os.mkdir", "os.rename", "os.utime", "os.chmod", "os.remove", "os.rmdir",
          "os.listdir", "os.scandir", "os.symlink", "os.link"}
def audit(event, args):
    if active[0] and event in EVENTS:
        for value in args[:2] if event in ("os.rename", "os.link") else args[:1]:
            path = path_of(value)
            if path:
                touched.append(path)
sys.addaudithook(audit)
for name in ("stat", "lstat"):
    def wrapped(path, *a, _f=getattr(os, name), **k):
        found = path_of(path)
        if active[0] and found:
            touched.append(found)
        return _f(path, *a, **k)
    setattr(os, name, wrapped)
try:
    runpy.run_path(sys.argv[1], run_name="__main__")
except SystemExit:
    pass
active[0] = False
modules = sorted(name for name in sys.modules if name.split(".")[0] == "odoo_mcp")
with open(sys.argv[2], "w") as fh:
    json.dump({"seen": seen, "bulk": bulk, "touched": touched, "modules": modules}, fh)
"""

# What the hook may look up; Windows' platform module also reads the processor names.
READABLE = {"CLAUDE_PLUGIN_DATA", "CLAUDE_CODE_ENTRYPOINT"}
WINDOWS_PLATFORM = {"PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432"}
CREDENTIAL = re.compile(r"API_?KEY|PASSWORD|PASSWD|SECRET|TOKEN|BEARER|CREDENTIAL|^ODOO_",
                        re.IGNORECASE)


def _within(path: str, roots: list[str]) -> bool:
    real = os.path.realpath(path)
    return any(real == root or real.startswith(root + os.sep) for root in roots)


@pytest.mark.parametrize(("state", "source"), [
    ("none", "startup"), ("none", "resume"), ("ok recent", "startup"), ("ok stale", "startup"),
    ("locked", "startup"), ("container", "startup"),
])
def test_it_reads_only_its_two_variables_and_its_own_folders(tmp_path: Path, state: str,
                                                              source: str) -> None:
    records = {"none": [], "ok recent": [start(2), connect(2)],
               "ok stale": [start(500), connect(500)], "locked": [start(1, code="E8")],
               "container": [start(2), connect(2)]}[state]
    _server_log(tmp_path, records)
    if state == "container":
        _marker(tmp_path)
    # What 1.5.0 looked for: the container mode's credentials file in the home folder.
    env_file = tmp_path / "home" / ".odoo-tools" / "mcp" / ("odoo" + ".env")
    env_file.parent.mkdir(parents=True)
    env_file.write_text("ODOO_URL=<https://your-odoo>\n")
    report = tmp_path / "access.json"
    work = tmp_path / "cwd"
    work.mkdir()
    done = subprocess.run([sys.executable, "-I", "-c", _SPY, str(HOOK), str(report)],
                          input=_event(source), env=_env(tmp_path, CLAUDE_CODE_ENTRYPOINT="cli"),
                          cwd=work, capture_output=True, timeout=30, check=True)
    access = json.loads(report.read_text(encoding="utf-8"))
    assert access["bulk"] == []  # the environment is never listed or copied
    assert "CLAUDE_PLUGIN_DATA" in access["seen"]  # the spy works
    for key in access["seen"]:
        assert not key.upper().startswith(OPTION), key
        assert not CREDENTIAL.search(key), key
    allowed = READABLE | (WINDOWS_PLATFORM if os.name == "nt" else set())
    assert set(access["seen"]) <= allowed
    assert access["modules"] == []  # it never imports the server, nor its loader
    roots = [os.path.realpath(p) for p in (_data(tmp_path), ROOT, sys.prefix, sys.base_prefix,
                                           sys.exec_prefix, sys.base_exec_prefix)]
    outside = [p for p in access["touched"] if not _within(p, roots)]
    assert outside == []
    assert not any(".odoo-tools" in p or str(tmp_path / "home") in p
                   for p in access["touched"])
    for value in CANARIES.values():
        assert value.encode() not in done.stdout


# --- hooks.json ----------------------------------------------------------------------------

def _hooks() -> list[dict[str, Any]]:
    config = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    return [h for group in config["hooks"]["SessionStart"] for h in group["hooks"]]


def test_hooks_json_runs_the_new_hook_behind_the_version_guard() -> None:
    first, second = _hooks()
    assert first == {"type": "command", "command": (
        "if python3 --version >/dev/null 2>&1; then :; else echo '" + FIRST_MESSAGE + "'; fi")}
    assert first["command"].isascii()
    assert "sys.version_info < (3, 9)" in second["command"]
    assert '"${CLAUDE_PLUGIN_ROOT}/hooks/session_start.py"' in second["command"]  # quoted
    assert "args" not in second and second["timeout"] == 10
    for hook in (first, second):  # Claude Code rejects option references in shell hooks
        assert "${user_" + "config." not in hook["command"]
    assert "check_options" not in (ROOT / "hooks" / "hooks.json").read_text()


def _shell(command: str, tmp_path: Path, path: str,
           source: str = "startup") -> tuple[int, str, str]:
    env = _env(tmp_path, PATH=path)
    sh = shutil.which("sh")  # resolved here: the child's PATH is the one under test
    assert sh
    result = subprocess.run([sh, "-c", command.replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT))],
                            input=_event(source), env=env, capture_output=True, timeout=30,
                            check=False)
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


def _bin(tmp_path: Path, name: str, python: str | None) -> str:
    folder = tmp_path / name
    folder.mkdir()
    if python == "real":
        (folder / "python3").symlink_to(sys.executable)
    elif python == "old":
        (folder / "python3").write_text("#!/bin/sh\nexit 1\n")  # what 3.8 answers the guard
        (folder / "python3").chmod(0o755)
    return str(folder)


@POSIX_ONLY
def test_without_python3_the_first_hook_explains_and_the_second_is_quiet(
        tmp_path: Path) -> None:
    first, second = _hooks()
    empty = _bin(tmp_path, "empty-bin", None)
    assert _shell(first["command"], tmp_path, empty) == (0, FIRST_MESSAGE + "\n", "")
    assert _shell(second["command"], tmp_path, empty) == (0, "", "")


@POSIX_ONLY
def test_an_old_python3_is_skipped_quietly(tmp_path: Path) -> None:
    old = _bin(tmp_path, "old-bin", "old")
    assert _shell(_hooks()[1]["command"], tmp_path, old) == (0, "", "")


@POSIX_ONLY
def test_a_supported_python3_runs_the_hook(tmp_path: Path) -> None:
    first, second = _hooks()
    real = _bin(tmp_path, "py-bin", "real")
    assert _shell(first["command"], tmp_path, real) == (0, "", "")
    _seen_before(tmp_path)
    code, out, err = _shell(second["command"], tmp_path, real)
    assert code == 0 and err == ""
    assert "In Cowork" in json.loads(out)["systemMessage"]


@POSIX_ONLY
def test_the_event_reaches_the_hook_past_the_version_guard(tmp_path: Path) -> None:
    # If the guard consumed stdin, a resume would look like a new session and notify.
    real = _bin(tmp_path, "py-bin", "real")
    code, out, err = _shell(_hooks()[1]["command"], tmp_path, real, source="resume")
    payload = json.loads(out)
    assert code == 0 and err == ""
    assert "systemMessage" not in payload
    assert not (_data(tmp_path) / "options-notice").exists()
    assert _hook_lines(tmp_path)[0]["source"] == "resume"
