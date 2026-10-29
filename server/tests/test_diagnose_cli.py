# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""``run_stdio.py --diagnose``: the support report a user pastes to support.

/odoo-tools:odoo-doctor runs exactly ``python3 server/run_stdio.py --diagnose --diag-dir
"${CLAUDE_PLUGIN_DATA}/diagnostics" --audit-dir "${CLAUDE_PLUGIN_DATA}/audit"``. It
must exit 0 with or without files, print no key, URL, login or record data, and never
contact Odoo.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from odoo_mcp import diagnostics
from odoo_mcp.__main__ import main
from odoo_mcp.audit import AuditLog
from odoo_mcp.config import Settings
from odoo_mcp.diagnostics import HEADER, HOOK_FILE, SERVER_FILE
from odoo_mcp.errors import PolicyDenied
from odoo_mcp.policy import load_policy
from odoo_mcp.registry import registry

RUN_STDIO = Path(__file__).resolve().parents[1] / "run_stdio.py"
TOOL_NAMES = [tool.name for tool in registry.all()]
TODAY = datetime.datetime.now(datetime.timezone.utc).date()
DB, LOGIN = "db-CANARY-1", "login-CANARY-2@example.com"
POLICY_ENV = ("ODOO_POLICY", "ODOO_POLICY_FILE", "ODOO_READONLY", "ODOO_DIAG_DIR",
              "ODOO_AUDIT_DIR")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in POLICY_ENV:
        monkeypatch.delenv(name, raising=False)


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(argv)
    captured = capsys.readouterr()
    assert captured.err == ""
    return code, captured.out


def _record(n: int, event: str = "stop", **fields: Any) -> dict[str, Any]:
    return {"v": 1, "ts": f"2026-10-2{n % 10}T00:00:00Z", "event": event, "pid": 100 + n,
            "uptime_s": n, "calls": n, "errors": {}, **fields}


def _write(path: Path, records: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n"
                            for r in records))


def _hook(n: int) -> dict[str, Any]:
    return {"v": 1, "ts": f"2026-10-2{n}T08:00:00Z", "event": "session_start",
            "source": "startup", "session_id": f"s-{n}", "plugin": "1.5.0",
            "os": {"system": "Linux", "release": "6.1", "machine": "x86_64"},
            "python": "3.12.1", "entrypoint": "cli", "server_last": "none", "container": False}


# --- without files -------------------------------------------------------------------------

def test_missing_folders_still_exit_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(["--diagnose", "--diag-dir", str(tmp_path / "nope"),
                      "--audit-dir", str(tmp_path / "nada")], capsys)
    lines = out.splitlines()
    assert code == 0 and lines[0] == HEADER
    assert lines[1].startswith("plugin: ") and lines[2].startswith("python: ")
    assert lines[3].startswith("os: ")
    assert f"diagnostics folder: {tmp_path / 'nope'} (missing)" in lines
    assert lines.count("  none") == 2  # no server events, no hook events
    assert "audit: missing" in lines
    assert any(line.startswith("policy (computed offline") for line in lines)


def test_unset_folders_say_how_to_pass_them(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(["--diagnose"], capsys)
    assert code == 0
    assert "diagnostics folder: not set (ODOO_DIAG_DIR is unset; pass --diag-dir)" in out
    assert "audit: not set (ODOO_AUDIT_DIR is unset; pass --audit-dir)" in out


@pytest.mark.parametrize(("value", "shown"), [
    ("off", "diagnostics folder: off"),
    ("relative/diag", "diagnostics folder: relative/diag (not an absolute path)"),
    ("${CLAUDE_PLUGIN_DATA}/diagnostics",
     "diagnostics folder: ${CLAUDE_PLUGIN_DATA}/diagnostics (not an absolute path)"),
])
def test_a_folder_that_is_not_one(value: str, shown: str,
                                  capsys: pytest.CaptureFixture[str]) -> None:
    assert shown in _run(["--diagnose", "--diag-dir", value], capsys)[1].splitlines()


def test_the_folders_default_to_the_server_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path / "diag" / SERVER_FILE, [_record(1)])
    monkeypatch.setenv("ODOO_DIAG_DIR", str(tmp_path / "diag"))
    monkeypatch.setenv("ODOO_AUDIT_DIR", "off")
    out = _run(["--diagnose"], capsys)[1]
    assert f"diagnostics folder: {tmp_path / 'diag'} (exists)" in out
    assert '"event":"stop","pid":101' in out and "audit: off" in out
    # An explicit folder wins over the environment.
    out = _run(["--diagnose", "--diag-dir", str(tmp_path / "other")], capsys)[1]
    assert f"{tmp_path / 'other'} (missing)" in out


# --- with files ----------------------------------------------------------------------------

def test_the_last_events_of_each_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    diag = tmp_path / "diag"
    _write(diag / SERVER_FILE, [_record(n) for n in range(1, 8)])
    _write(diag / HOOK_FILE, [_hook(n) for n in range(1, 5)])
    lines = _run(["--diagnose", "--diag-dir", str(diag)], capsys)[1].splitlines()
    server = lines.index("last 5 server events (server.jsonl):")
    hook = lines.index("last 3 hook events (hook.jsonl):")
    shown = [json.loads(line) for line in lines[server + 1:hook]]
    assert [event["pid"] for event in shown] == [103, 104, 105, 106, 107]  # oldest first
    hooks = [json.loads(line) for line in lines[hook + 1:hook + 4]]
    assert [event["session_id"] for event in hooks] == ["s-2", "s-3", "s-4"]
    assert hooks[-1] == _hook(4)  # a valid line is shown whole


def test_a_rotated_file_fills_in(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    diag = tmp_path / "diag"
    _write(diag / f"{SERVER_FILE}.1", [_record(n) for n in range(1, 5)])
    _write(diag / SERVER_FILE, [_record(n) for n in range(5, 7)])
    out = _run(["--diagnose", "--json", "--diag-dir", str(diag)], capsys)[1]
    events = json.loads(out)["diagnostics"]["server_events"]
    assert [event["pid"] for event in events] == [102, 103, 104, 105, 106]


def test_a_planted_line_shows_only_allowlisted_values(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    diag = tmp_path / "diag"
    secret = "https://admin:CANARY-PW@erp.example.com"
    _write(diag / SERVER_FILE, [
        "not json",
        {"v": 1, "ts": "2026-10-28T00:00:00Z", "event": "start", "pid": 1, "url": secret,
         "settings": {"url": secret, "db": DB}, "entrypoint": secret,
         "policy": {"profile": "standard", "file": "/home/me/CANARY-policy.json"}},
        {"v": 1, "ts": "2026-10-28T00:00:01Z", "event": "connect", "pid": 1, "ok": False,
         "category": "network", "message": secret},
        {"v": 1, "ts": "2026-10-28T00:00:02Z", "event": "crash", "pid": 1, "where": "tool",
         "error": f"Fault: {secret}", "frames": [["odoo_mcp.server", "call_tool", 3],
                                                  ["/home/me/CANARY.py", "f", 1]]},
        {"v": 2, "ts": "2026-10-28T00:00:03Z", "event": "stop", "secret": secret},
    ])
    _write(diag / HOOK_FILE, [{**_hook(1), "cwd": secret, "session_id": secret}])
    for argv in (["--diagnose"], ["--diagnose", "--json"]):
        out = _run([*argv, "--diag-dir", str(diag)], capsys)[1]
        assert "CANARY" not in out and DB not in out and "erp.example.com" not in out
    report = json.loads(out)["diagnostics"]
    start, connect, crash = report["server_events"]
    assert start["settings"] == {} and start["entrypoint"] == "other"
    assert start["policy"] == {"profile": "standard"}
    assert crash["error"] == "other" and crash["frames"] == [["odoo_mcp.server", "call_tool", 3]]
    assert "message" not in connect
    assert report["hook_events"][0]["session_id"] == "other"


def _audit(folder: Path, day: datetime.date) -> AuditLog:
    noon = datetime.datetime.combine(day, datetime.time(12), tzinfo=datetime.timezone.utc)
    return AuditLog("file", str(folder), retention_days=0, clock=lambda: noon)


def test_the_audit_summary_counts_seven_days_by_status_and_rule(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = tmp_path / "audit"
    policy = load_policy(Settings(), TOOL_NAMES)
    settings = Settings(db=DB, login=LOGIN)
    for offset, calls in ((0, ["ok", "ok", "error"]), (6, ["refused", "invalid"]),
                          (7, ["ok"] * 9)):  # the 8th day back is outside the window
        log = _audit(folder, TODAY - datetime.timedelta(days=offset))
        log.start(settings, policy)  # the start line names the database and the login
        for status in calls:
            if status == "refused":
                log.refused("odoo_write", PolicyDenied("no", rule="tier:security"), layer="A")
            else:
                log.call("odoo_read", status=status)
    out = _run(["--diagnose", "--audit-dir", str(folder)], capsys)[1]
    assert ("audit, last 7 days: 2 files, 5 calls; by status: ok 2, error 1, invalid 1, "
            "refused 1; refusals by rule: tier:security 1") in out.splitlines()
    assert DB not in out and LOGIN not in out
    summary = json.loads(_run(["--diagnose", "--json", "--audit-dir", str(folder)],
                              capsys)[1])["audit"]
    assert summary == {"state": "ok", "days": 7, "files": 2, "calls": 5,
                       "by_status": {"ok": 2, "error": 1, "refused": 1, "invalid": 1},
                       "refusals_by_rule": {"tier:security": 1}}


# --- the policy, offline -------------------------------------------------------------------

def _policy(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    return json.loads(_run(["--diagnose", "--json"], capsys)[1])["policy"]


def test_the_policy_summary_is_computed_as_the_server_would(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    standard = load_policy(Settings(), TOOL_NAMES)
    assert _policy(capsys) == {"profile": "standard", "file": False, "readonly": False,
                               "locked": False, "digest": standard.digest}
    monkeypatch.setenv("ODOO_POLICY", "Builder")
    monkeypatch.setenv("ODOO_READONLY", "1")
    builder = load_policy(Settings.from_env(), TOOL_NAMES)
    assert builder.digest != standard.digest
    assert _policy(capsys) == {"profile": "builder", "file": False, "readonly": True,
                               "locked": False, "digest": builder.digest}
    out = _run(["--diagnose"], capsys)[1]
    assert (f"profile builder, digest {builder.digest}, locked no, policy file no, "
            "read-only yes") in out


def test_a_locked_policy_shows_its_e_code_never_its_text_or_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("ODOO_POLICY", "pasted-CANARY-key")  # a value typed in the wrong box
    assert _policy(capsys) == {"profile": "unknown", "file": False, "readonly": False,
                               "locked": True, "code": "E1"}
    monkeypatch.delenv("ODOO_POLICY")
    folder = tmp_path / "CANARY-folder"
    folder.mkdir()
    path = folder / "policy.json"
    path.write_text('{"version": 1, "modelz": {}}')
    path.chmod(0o600)
    monkeypatch.setenv("ODOO_POLICY_FILE", str(path))
    assert _policy(capsys) == {"profile": "standard", "file": True, "readonly": False,
                               "locked": True, "code": "E8"}
    out = _run(["--diagnose"], capsys)[1]
    assert "locked yes (E8)" in out and "CANARY" not in out and "modelz" not in out


# --- the entry point -----------------------------------------------------------------------

def test_through_run_stdio_as_the_doctor_runs_it(tmp_path: Path) -> None:
    data = tmp_path / "plugin-data"
    _write(data / "diagnostics" / SERVER_FILE, [_record(1)])
    done = subprocess.run(
        [sys.executable, "-I", str(RUN_STDIO), "--diagnose", "--diag-dir",
         str(data / "diagnostics"), "--audit-dir", str(data / "audit")],
        capture_output=True, text=True, timeout=60, check=False, env={})
    assert done.returncode == 0 and done.stderr == ""
    assert done.stdout.splitlines()[0] == HEADER
    assert f"{data / 'diagnostics'} (exists)" in done.stdout


@pytest.mark.parametrize("argv", [
    ["--diag-dir", "x"],  # needs --diagnose
    ["--audit-dir", "x"],
    ["--diagnose", "--check-policy", ""],
    ["--diagnose", "--verify-audit", "x.jsonl"],
    ["--diagnose", "--profile", "full"],
    ["--json"],
])
def test_bad_usage_exits_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(argv)
    assert raised.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_the_report_writes_the_home_folder_as_a_tilde(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    # A report pasted to support should not carry the computer's account name.
    home = tmp_path / "home" / "someone"
    (home / "data" / "diagnostics").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    summary = diagnostics.diagnostics_summary(str(home / "data" / "diagnostics"))
    assert summary["folder"] == "~" + os.sep + os.path.join("data", "diagnostics")
    assert "someone" not in summary["folder"] and summary["state"] == "exists"
    outside = tmp_path / "elsewhere"
    assert diagnostics.diagnostics_summary(str(outside))["folder"] == str(outside)
