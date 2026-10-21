# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The audit trail (design 7 and 9.6): one line per tool call, refusals included.

A line holds names and counts only. The canary tests run real calls through the
server, with distinctive values in record values, domains, ids, an Odoo fault
message, the URL and the secrets, and show that none of them reaches a file,
while the tool, model and operation names do.
"""

from __future__ import annotations

import datetime
import io
import json
import logging
import os
import stat
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from policy_fakes import KEY, ScriptedSession, call, policy
from policy_fakes import server as guarded_server

from odoo_mcp.__main__ import main
from odoo_mcp.audit import (
    AUDIT_KEYS,
    GENESIS,
    AuditLog,
    clean,
    file_name,
    line_hash,
    record,
    touch_text,
    verify,
    verify_main,
)
from odoo_mcp.config import Settings
from odoo_mcp.errors import OdooFault
from odoo_mcp.server import serve

POSIX = os.name == "posix"
CANARY = "CANARY-VALUE-7f3a9c"
CANARY_EMAIL = "canary-person@leak.example"
CANARY_ID = 987654321
CANARY_HOST = "canary-host.example"
CANARY_PASSWORD = "pw-CANARY-5521"
CANARY_FAULT = "duplicate key (email)=(fault-canary@leak.example)"
LOGIN = "auditor-login@example.com"
NOON = datetime.datetime(2026, 10, 21, 12, 0, 0, tzinfo=datetime.timezone.utc)


class Clock:
    """A settable UTC clock."""

    def __init__(self, now: datetime.datetime = NOON) -> None:
        self.now = now

    def __call__(self) -> datetime.datetime:
        return self.now


def audit_in(folder: Path, *, clock: Clock | None = None, retention: int = 90) -> AuditLog:
    return AuditLog("file", str(folder), retention_days=retention, clock=clock or Clock())


def lines_of(folder: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("odoo-tools-audit-*.jsonl")):
        out.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return out


def text_of(folder: Path) -> str:
    return "".join(path.read_text(encoding="utf-8") for path in sorted(folder.iterdir())
                   if path.is_file())


def secret_settings(folder: Path) -> Settings:
    return Settings(url=f"https://gateway:{CANARY_PASSWORD}@{CANARY_HOST}", db="auditdb",
                    login=LOGIN, password=CANARY_PASSWORD, api_key=KEY, audit_dir=str(folder))


def _fault(args: Any, kwargs: Any, ids: Any) -> Any:
    raise OdooFault(CANARY_FAULT)


# --- no value, domain, id or secret ever reaches a file -------------------------------------

def test_no_value_domain_id_fault_text_or_secret_reaches_the_file(tmp_path: Path) -> None:
    folder = tmp_path / "audit"
    settings = secret_settings(folder)
    audit = AuditLog.from_settings(settings)
    session = ScriptedSession(results={("sale.order", "action_confirm"): _fault})
    srv = guarded_server(session, audit=audit)
    audit.start(settings, srv.policy)
    calls = [
        ("odoo_create", {"model": "res.partner",
                         "values": {"name": CANARY, "email": CANARY_EMAIL}}),
        ("odoo_search_read", {"model": "res.partner", "fields": ["name"],
                              "domain": [["name", "=", CANARY], ["id", "in", [CANARY_ID]]]}),
        ("odoo_read", {"model": "res.partner", "ids": [CANARY_ID], "fields": ["name"]}),
        ("odoo_write", {"model": "res.partner", "ids": [CANARY_ID],
                        "values": {"comment": CANARY}}),
        # Odoo fails: only the class name is kept, never the fault text
        ("odoo_execute", {"model": "sale.order", "method": "action_confirm",
                          "ids": [CANARY_ID], "kwargs": {"context": {"lang": CANARY}}}),
        # Layer A refusal (security tier)
        ("odoo_write", {"model": "res.users", "ids": [CANARY_ID],
                        "values": {"login": CANARY_EMAIL}}),
        # Layer B refusal: the command creates a user
        ("odoo_write", {"model": "res.partner", "ids": [CANARY_ID],
                        "values": {"user_ids": [[0, 0, {"login": CANARY_EMAIL}]]}}),
        # a value where a name goes: refused, and the name is not written
        ("odoo_search_read", {"model": f"x_{CANARY}", "domain": [[CANARY, "=", 1]]}),
        ("odoo_execute", {"model": "res.partner", "method": f"{CANARY}\nX", "args": [CANARY]}),
        # hidden under standard: refused at the tool itself
        ("odoo_unlink", {"model": "res.partner", "ids": [CANARY_ID]}),
        # invalid arguments
        ("odoo_read", {"model": "res.partner", "ids": CANARY}),
    ]
    results = [call(srv, tool, **arguments) for tool, arguments in calls]
    assert results[0][0] is False and results[5][0] is True and results[6][0] is True
    assert CANARY_FAULT in results[4][1]  # the agent sees it; the audit does not

    text = text_of(folder)
    for canary in (CANARY, CANARY_EMAIL, "leak.example", str(CANARY_ID), CANARY_HOST,
                   CANARY_PASSWORD, KEY, "gateway", "duplicate key", "fault-canary"):
        assert canary not in text, canary
    lines = lines_of(folder)
    assert [line["event"] for line in lines] == ["start"] + ["call"] * len(calls)
    assert all(set(line) <= AUDIT_KEYS for line in lines)
    # the login identifies the acting user on the start line only
    assert lines[0]["login"] == LOGIN and lines[0]["db"] == "auditdb"
    assert LOGIN not in json.dumps(lines[1:]) and "auditdb" not in json.dumps(lines[1:])
    by_tool = [(line["tool"], line["status"]) for line in lines[1:]]
    assert by_tool == [("odoo_create", "ok"), ("odoo_search_read", "ok"), ("odoo_read", "ok"),
                       ("odoo_write", "ok"), ("odoo_execute", "error"),
                       ("odoo_write", "refused"), ("odoo_write", "refused"),
                       ("odoo_search_read", "refused"), ("odoo_execute", "refused"),
                       ("odoo_unlink", "refused"), ("odoo_read", "invalid")]
    assert lines[5]["error"] == "OdooFault" and lines[5]["decision"] == "allow"
    assert lines[5]["touches"] == ["call:sale.order:action_confirm"]
    # names are kept; a value where a name goes becomes "?"
    for refusal in lines[8:10]:  # an invalid name is described, never written
        assert (refusal["layer"], refusal["rule"]) == ("A", "invalid-name")
        assert refusal["touches"] == []


def test_a_layer_a_refusal_line() -> None:
    audit, lines = recording_audit()
    srv = guarded_server(ScriptedSession(), audit=audit)
    is_error, _text = call(srv, "odoo_write", model="res.users", ids=[1],
                           values={"name": "x"})
    assert is_error
    (line,) = lines
    assert (line["layer"], line["decision"], line["status"]) == ("A", "deny", "refused")
    assert line["rule"] == "tier:security" and line["touches"] == ["write:res.users"]
    assert line["error"] == "PolicyDenied" and line["policy"] == srv.policy.digest
    assert "ms" not in line and "n" not in line  # no handler ran


def test_a_layer_b_refusal_is_audited_with_layer_b() -> None:
    audit, lines = recording_audit()
    session = ScriptedSession()
    srv = guarded_server(session, audit=audit)
    is_error, text = call(srv, "odoo_write", model="res.partner", ids=[7],
                          values={"user_ids": [[0, 0, {"login": "new"}]]})
    assert is_error and "stopped before Odoo ran it" in text
    (line,) = lines
    assert (line["layer"], line["decision"], line["status"]) == ("B", "deny", "refused")
    assert line["rule"] == "relational" and line["error"] == "PolicyDenied"
    assert line["touches"] == ["write:res.partner"]
    assert "create:res.users" in line["effective"]
    assert isinstance(line["ms"], int) and line["n"] == 0 and line["withheld"] == 0


def test_an_allowed_call_counts_rows_and_withheld_fields() -> None:
    audit, lines = recording_audit()
    session = ScriptedSession(results={("res.partner", "search_read"): [
        {"id": 1, "name": "A", "signup_token": "tok-1"}, {"id": 2, "name": "B"}]})
    srv = guarded_server(session, audit=audit)
    is_error, _text = call(srv, "odoo_search_read", model="res.partner")
    assert not is_error
    (line,) = lines
    assert (line["decision"], line["status"]) == ("allow", "ok") and "layer" not in line
    assert line["touches"] == ["read:res.partner"] and "read:res.partner" in line["effective"]
    assert line["n"] == 2 and line["withheld"] >= 1 and "error" not in line


def test_tool_level_refusals_and_invalid_calls() -> None:
    audit, lines = recording_audit()
    srv = guarded_server(ScriptedSession(), audit=audit)
    call(srv, "odoo_unlink", model="res.partner", ids=[1])  # hidden under standard
    readonly = guarded_server(ScriptedSession(), audit=audit, readonly=True)
    call(readonly, "odoo_create", model="res.partner", values={"name": "x"})
    call(srv, "odoo_read", model="res.partner", ids="not a list")
    hidden, ro, invalid = lines
    assert (hidden["layer"], hidden["decision"], hidden["rule"]) == ("tool", "deny",
                                                                    "profile:standard")
    assert (ro["layer"], ro["rule"], ro["error"]) == ("tool", "readonly", "CompatError")
    assert invalid["status"] == "invalid" and "decision" not in invalid


def test_a_bug_in_the_policy_check_is_audited_as_an_error(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from odoo_mcp.policy import Policy

    def broken(self: Any, tool: Any, arguments: Any) -> Any:
        raise RuntimeError(CANARY)

    monkeypatch.setattr(Policy, "check", broken)
    audit, lines = recording_audit()
    call(guarded_server(ScriptedSession(), audit=audit), "odoo_search_read", model="res.partner")
    (line,) = lines
    assert (line["status"], line["decision"], line["layer"], line["rule"], line["error"]) == (
        "error", "deny", "A", "internal", "RuntimeError")
    assert CANARY not in json.dumps(line)


def recording_audit() -> tuple[AuditLog, list[dict[str, Any]]]:
    """An audit whose lines are kept in a list (the stderr mode, read back)."""
    lines: list[dict[str, Any]] = []
    audit = AuditLog("stderr", clock=Clock())

    class Keep(logging.Handler):
        def emit(self, rec: logging.LogRecord) -> None:
            lines.append(json.loads(rec.getMessage()))

    handler = Keep(logging.INFO)
    logger = logging.getLogger("odoo_mcp.audit")
    logger.addHandler(handler)
    _HANDLERS.append((handler, logger.level))
    logger.setLevel(logging.INFO)
    return audit, lines


_HANDLERS: list[tuple[logging.Handler, int]] = []


@pytest.fixture(autouse=True)
def _detach_handlers() -> Any:
    yield
    logger = logging.getLogger("odoo_mcp.audit")
    while _HANDLERS:
        handler, level = _HANDLERS.pop()
        logger.removeHandler(handler)
        logger.setLevel(level)


# --- the record allowlist --------------------------------------------------------------------

def test_only_audit_keys_are_written_and_strings_are_cleaned() -> None:
    line = record({"event": "call", "tool": "odoo_read", "values": {"a": CANARY},
                   "domain": [["name", "=", CANARY]], "url": "https://x", "ids": [CANARY_ID],
                   "rule": "a\x1b[31mb\nc\u2028d\u202ee", "n": 3, "error": "x" * 500})
    assert set(line) == {"event", "tool", "rule", "n", "error"}
    assert line["rule"] == "a[31mbcde" and len(line["error"]) == 200
    assert clean(list(range(80))) == list(range(50))
    assert clean({"k\n": object()}) == {"k": None}
    assert clean(float("nan")) is None


@pytest.mark.parametrize(("raw", "shown"), [
    ("read:res.partner", "read:res.partner"),
    ("call:sale.order:action_confirm", "call:sale.order:action_confirm"),
    ("read:None", "read:?"),
    (f"read:{CANARY}", "read:?"),
    ("call:res.partner:bad name", "call:res.partner:?"),
    ("call:res.partner:a:b", "call:res.partner:?"),
    ("drop:res.partner", "?:res.partner"),
])
def test_touch_strings_keep_checked_names_only(raw: str, shown: str) -> None:
    assert touch_text(raw) == shown


# --- files, modes, naming ------------------------------------------------------------------

def test_daily_files_are_named_by_utc_day_and_owner_only(tmp_path: Path) -> None:
    folder = tmp_path / "audit"
    clock = Clock(datetime.datetime(2026, 10, 21, 23, 59, 59, tzinfo=datetime.timezone.utc))
    audit = audit_in(folder, clock=clock)
    audit.write({"event": "call", "tool": "odoo_read", "status": "ok"})
    clock.now += datetime.timedelta(seconds=2)
    audit.write({"event": "call", "tool": "odoo_read", "status": "ok"})
    names = sorted(path.name for path in folder.iterdir())
    assert names == ["odoo-tools-audit-2026-10-21.jsonl", "odoo-tools-audit-2026-10-22.jsonl"]
    assert file_name(datetime.date(2026, 1, 2)) == "odoo-tools-audit-2026-01-02.jsonl"
    first, second = lines_of(folder)
    assert first["ts"] == "2026-10-21T23:59:59Z" and second["ts"] == "2026-10-22T00:00:01Z"
    # each file is its own chain
    assert first["seq"] == second["seq"] == 1 and first["prev"] == second["prev"] == GENESIS
    if POSIX:
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700
        for path in folder.iterdir():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(not POSIX, reason="symlinks and O_NOFOLLOW")
def test_a_symlinked_daily_file_is_never_followed(tmp_path: Path) -> None:
    folder = tmp_path / "audit"
    folder.mkdir(mode=0o700)
    target = tmp_path / "elsewhere.txt"
    target.write_text("keep\n")
    (folder / file_name(NOON.date())).symlink_to(target)
    audit = audit_in(folder)
    audit.write({"event": "call", "tool": "odoo_read", "status": "ok"})  # never raises
    assert target.read_text() == "keep\n"


def test_pruning_removes_only_old_regular_audit_files(tmp_path: Path) -> None:
    folder = tmp_path / "audit"
    folder.mkdir()
    old = folder / "odoo-tools-audit-2026-07-01.jsonl"
    edge = folder / "odoo-tools-audit-2026-07-23.jsonl"  # exactly 90 days before: kept
    recent = folder / "odoo-tools-audit-2026-10-01.jsonl"
    unrelated = folder / "notes-2020-01-01.jsonl"
    near_miss = folder / "odoo-tools-audit-2020-01-01.jsonl.bak"
    bad_date = folder / "odoo-tools-audit-2020-13-45.jsonl"
    other_digits = folder / "odoo-tools-audit-\u0662\u0660\u0662\u0660-01-01.jsonl"
    old_dir = folder / "odoo-tools-audit-2020-02-02.jsonl"
    for path in (old, edge, recent, unrelated, near_miss, bad_date, other_digits):
        path.write_text("x\n")
    old_dir.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text("keep\n")
    link = folder / "odoo-tools-audit-2020-03-03.jsonl"
    survivors = []
    if POSIX:
        link.symlink_to(outside)
        survivors.append(folder / "odoo-tools-audit-2020-04-04.jsonl\n")  # not an audit name
        survivors[0].write_text("x\n")
    audit = audit_in(folder)
    audit.write({"event": "start"})  # the first write prunes
    assert not old.exists()
    for path in (edge, recent, unrelated, near_miss, bad_date, other_digits, old_dir, outside,
                 *survivors):
        assert path.exists(), path
    if POSIX:
        assert link.is_symlink() and outside.read_text() == "keep\n"


def test_retention_zero_keeps_everything_and_midnight_prunes_again(tmp_path: Path) -> None:
    folder = tmp_path / "audit"
    folder.mkdir()
    ancient = folder / "odoo-tools-audit-2001-01-01.jsonl"
    ancient.write_text("x\n")
    audit_in(folder, retention=0).write({"event": "start"})
    assert ancient.exists()

    clock = Clock()
    audit = audit_in(folder, clock=clock, retention=1)
    audit.write({"event": "start"})
    assert not ancient.exists()
    yesterday = folder / file_name(NOON.date() - datetime.timedelta(days=1))
    yesterday.write_text("x\n")
    audit.write({"event": "call"})  # same day: no pruning
    assert yesterday.exists()
    clock.now += datetime.timedelta(days=1)
    assert yesterday.exists()  # one day old: inside a 1-day retention
    clock.now += datetime.timedelta(days=1)
    audit.write({"event": "call"})  # the first write after midnight prunes again
    assert not yesterday.exists()


def test_a_broken_folder_never_fails_a_call(tmp_path: Path,
                                            caplog: pytest.LogCaptureFixture) -> None:
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("")
    audit = AuditLog("file", str(blocker / "audit"))
    srv = guarded_server(ScriptedSession(), audit=audit)
    with caplog.at_level(logging.WARNING, logger="odoo_mcp.audit"):
        for _ in range(3):
            is_error, _text = call(srv, "odoo_search_read", model="res.partner")
            assert not is_error
    warnings = [r for r in caplog.records if r.name == "odoo_mcp.audit"]
    assert len(warnings) == 1 and "could not be written" in warnings[0].getMessage()


# --- the hash chain and --verify-audit -------------------------------------------------------

def _filled(folder: Path, count: int = 5) -> Path:
    audit = audit_in(folder)
    audit.start(Settings(db="d", login="l"), policy())
    for number in range(count - 1):
        audit.call("odoo_read", status="ok", touches=["read:res.partner"], seconds=number / 100)
    return folder / file_name(NOON.date())


def test_the_chain_links_every_line(tmp_path: Path) -> None:
    path = _filled(tmp_path)
    raw = path.read_bytes().split(b"\n")[:-1]
    lines = [json.loads(line) for line in raw]
    assert [line["seq"] for line in lines] == [1, 2, 3, 4, 5]
    assert lines[0]["prev"] == GENESIS
    for before, line in zip(raw, lines[1:]):
        assert line["prev"] == line_hash(before)
    assert verify(str(path)).ok and verify(str(path)).lines == 5


def _rewrite(path: Path, change: Any) -> None:
    lines = path.read_bytes().split(b"\n")[:-1]
    path.write_bytes(b"".join(line + b"\n" for line in change(lines)))


@pytest.mark.parametrize(("change", "broken", "words"), [
    (lambda ls: ls[:2] + [ls[2].replace(b'"ms":1', b'"ms":9')] + ls[3:], 4, "prev does not match"),
    (lambda ls: ls[:2] + ls[3:], 3, "seq is 4, expected 3"),
    (lambda ls: ls[1:], 1, "seq is 2, expected 1"),
    (lambda ls: ls[:2] + [b'{"v":1,"seq":3,"prev":"x","event":"call","values":"x"}'] + ls[3:],
     3, "unknown keys"),
    (lambda ls: ls[:1] + [b"not json"] + ls[1:], 2, "not a JSON line"),
])
def test_verify_catches_an_edit_a_removal_and_a_truncation(
        tmp_path: Path, change: Any, broken: int, words: str) -> None:
    path = _filled(tmp_path)
    _rewrite(path, change)
    result = verify(str(path))
    assert not result.ok and result.broken == broken and words in result.reason, result


def test_verify_catches_a_cut_tail_and_a_new_chain_says_why(tmp_path: Path) -> None:
    path = _filled(tmp_path)
    data = path.read_bytes()
    path.write_bytes(data[:-25])  # cut inside the last line
    result = verify(str(path))
    assert (result.broken, result.lines) == (5, 4) and "not complete" in result.reason
    # the next write cannot read the tail back: it starts a new chain, and says so
    audit_in(tmp_path).call("odoo_read", status="ok")
    lines = path.read_bytes().split(b"\n")[:-1]
    reset, after = json.loads(lines[-2]), json.loads(lines[-1])
    assert reset["event"] == "chain_reset" and (reset["seq"], reset["prev"]) == (1, GENESIS)
    assert (after["seq"], after["prev"]) == (2, line_hash(lines[-2]))
    result = verify(str(path))
    assert result.broken == 5 and "not a JSON line" in result.reason


def test_a_restart_continues_the_chain(tmp_path: Path) -> None:
    path = _filled(tmp_path, 3)
    audit_in(tmp_path).call("odoo_read", status="ok")  # another process, same day
    assert verify(str(path)).lines == 4 and verify(str(path)).ok


@pytest.mark.skipif(not POSIX, reason="the cross-process lock is flock")
def test_two_writers_sharing_the_folder_keep_one_chain(tmp_path: Path) -> None:
    writers = [audit_in(tmp_path), audit_in(tmp_path)]

    def run(audit: AuditLog) -> None:
        for _ in range(40):
            audit.call("odoo_read", status="ok", touches=["read:res.partner"])

    threads = [threading.Thread(target=run, args=(audit,)) for audit in writers * 3]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    result = verify(str(tmp_path / file_name(NOON.date())))
    assert result.ok and result.lines == 240, result


def test_verify_audit_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _filled(tmp_path)
    assert main(["--verify-audit", str(path)]) == 0
    assert "5 lines, the hash chain is intact" in capsys.readouterr().out
    _rewrite(path, lambda ls: ls[:1] + ls[2:])
    assert main(["--verify-audit", str(path)]) == 1
    out = capsys.readouterr().out
    assert "line 2: seq is 3, expected 2" in out and "The 1 lines before it are intact." in out
    assert main(["--verify-audit", str(tmp_path / "missing.jsonl")]) == 2
    assert "cannot be read" in capsys.readouterr().out
    empty = tmp_path / "empty.jsonl"
    empty.write_bytes(b"")
    buffer = io.StringIO()
    assert verify_main(str(empty), buffer) == 0 and "0 lines" in buffer.getvalue()


def test_verify_audit_through_run_stdio(tmp_path: Path) -> None:
    path = _filled(tmp_path)
    run_stdio = Path(__file__).resolve().parents[1] / "run_stdio.py"
    env = {k: v for k, v in os.environ.items() if not k.startswith("ODOO_")}
    done = subprocess.run([sys.executable, str(run_stdio), "--verify-audit", str(path)],
                          capture_output=True, text=True, timeout=60, env=env, check=False)
    assert done.returncode == 0 and "hash chain is intact" in done.stdout, done.stderr
    assert not list(tmp_path.glob("odoo-tools-audit-*.jsonl"))[1:]  # nothing else written


# --- where it goes: a folder, stderr or off ---------------------------------------------------

@pytest.mark.parametrize(("raw", "mode"), [
    ("", "stderr"), ("stderr", "stderr"), ("STDERR", "stderr"), ("off", "off"), ("Off", "off"),
    ("relative/audit", "stderr"), ("${CLAUDE_PLUGIN_DATA}/audit", "stderr"),
    ("/var/lib/odoo-tools/audit", "file"), ("~/audit", "file"),
])
def test_odoo_audit_dir_picks_the_sink(raw: str, mode: str) -> None:
    audit = AuditLog.from_settings(Settings(audit_dir=raw, audit_retention_days=7))
    assert audit.mode == mode and audit.retention_days == 7
    assert audit.enabled is (mode != "off")
    if mode == "file":
        assert audit.directory is not None and os.path.isabs(audit.directory)
        assert "kept 7 days" in audit.describe()


def test_stderr_mode_logs_chained_lines(caplog: pytest.LogCaptureFixture) -> None:
    audit = AuditLog("stderr", clock=Clock())
    with caplog.at_level(logging.INFO, logger="odoo_mcp.audit"):
        audit.call("odoo_read", status="ok")
        audit.call("odoo_read", status="ok")
    raw = [r.getMessage() for r in caplog.records if r.name == "odoo_mcp.audit"]
    first, second = (json.loads(line) for line in raw)
    assert (first["seq"], first["prev"]) == (1, GENESIS)
    assert (second["seq"], second["prev"]) == (2, line_hash(raw[0].encode("utf-8")))


def test_off_writes_nothing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    audit = AuditLog.from_settings(Settings(audit_dir="off"))
    srv = guarded_server(ScriptedSession(), audit=audit)
    with caplog.at_level(logging.DEBUG):
        audit.start(Settings(login=LOGIN), srv.policy)
        call(srv, "odoo_search_read", model="res.partner")
    assert not [r for r in caplog.records if r.name == "odoo_mcp.audit"]
    assert LOGIN not in caplog.text


# --- the start line, from serve() --------------------------------------------------------------

def test_serve_writes_the_start_line_and_a_line_per_call(tmp_path: Path) -> None:
    folder = tmp_path / "audit"
    settings = secret_settings(folder)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        # hidden under standard, so no session is ever built
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "odoo_unlink", "arguments": {"model": "res.partner",
                                                          "ids": [CANARY_ID]}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "no_such_tool", "arguments": {}}},
    ]
    stdin = io.BytesIO(b"".join(json.dumps(r).encode() + b"\n" for r in requests))
    serve(settings, stdin=stdin, stdout=io.BytesIO())
    lines = lines_of(folder)
    start, refusal = lines  # an unknown tool name is a protocol error, not a tool call
    assert start["event"] == "start" and start["profile"] == "standard"
    assert start["policy"] and start["readonly"] is False and start["source"] is None
    assert start["pid"] == os.getpid() and start["warnings"] == [] and start["opened"] == []
    assert (start["db"], start["login"]) == ("auditdb", LOGIN)
    assert refusal["tool"] == "odoo_unlink" and refusal["layer"] == "tool"
    assert refusal["policy"] == start["policy"]
    text = text_of(folder)
    for canary in (str(CANARY_ID), CANARY_HOST, CANARY_PASSWORD, KEY):
        assert canary not in text


def test_the_start_line_of_a_locked_policy_carries_the_e_code(tmp_path: Path) -> None:
    folder = tmp_path / "audit"
    settings = Settings(policy_profile="readonyl", audit_dir=str(folder), login=LOGIN)
    serve(settings, stdin=io.BytesIO(b""), stdout=io.BytesIO())
    (start,) = lines_of(folder)
    assert start["error"] == "E1" and start["policy"] is None


def test_the_start_line_lists_openings_with_their_reason(tmp_path: Path) -> None:
    reason = "Ticket 4312: reviewed by the owner"
    p = policy(models={"res.partner.bank": {"write": True, "reason": reason}})
    audit = audit_in(tmp_path)
    audit.start(Settings(), p)
    (start,) = lines_of(tmp_path)
    assert start["opened"] == [{"model": "res.partner.bank", "ops": ["write"],
                                "tier": "security", "reason": reason, "expires": None}]
    assert start["source"] == "/etc/odoo-tools/policy.json" and start["policy"] == p.digest
    assert start["login"] is None and start["db"] is None  # unset: null, as on every start
