# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The local diagnostics (odoo_mcp/diagnostics.py): metadata only, never in the way.

The server writes server.jsonl in ODOO_DIAG_DIR: start, connect, crash and stop. These
tests run the real lifecycle (serve() over stdio, the transports against a scripted
Odoo) with a canary in every credential and connection setting, and check that no
canary reaches a file, that the files rotate and keep their modes, that "off" and a
broken folder change nothing for the tools, and that errors become categories.
"""

from __future__ import annotations

import datetime
import io
import json
import os
import socket
import stat
import time
import xmlrpc.client
from pathlib import Path
from typing import Any

import pytest
from fake_odoo_http import (
    FakeOdoo,
    html_reply,
    json_reply,
    jsonrpc_result,
    odoo_error,
    version_payload,
)

from odoo_mcp import diagnostics as diag_module
from odoo_mcp.config import Settings
from odoo_mcp.diagnostics import (
    CATEGORIES,
    CRASH_LIMIT,
    HOOK_RECORDS,
    LINE_LIMIT,
    ROTATE_AT,
    SERVER_FILE,
    SERVER_RECORDS,
    Diagnostics,
    append_line,
    clean_record,
    encode_record,
    error_category,
)
from odoo_mcp.errors import (
    AuthError,
    ConfigError,
    OdooFault,
    PolicyDenied,
    RateLimited,
    TransportError,
)
from odoo_mcp.policy import load_policy
from odoo_mcp.registry import NO_MODEL, ToolDef, registry
from odoo_mcp.server import serve
from odoo_mcp.transport.json2 import Json2Transport
from odoo_mcp.transport.jsonrpc import JsonRpcTransport

ROOT = Path(__file__).resolve().parents[2]
TOOL_NAMES = [tool.name for tool in registry.all()]
POSIX = pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")

# A canary in every value a line must never hold.
CANARY = {
    "user": "usr-CANARY-U1",
    "url_password": "pw-CANARY-P2",
    "path": "path-CANARY-H3",
    "db": "db-CANARY-D4",
    "login": "login-CANARY-L5@example.com",
    "api_key": "key-CANARY-K6",
    "password": "pass-CANARY-W7",
    "bearer": "bearer-CANARY-B8",
    "policy_dir": "policy-CANARY-F9",
    "argument": "arg-CANARY-A10",
    "fault": "fault-CANARY-M11",
    "crash": "crash-CANARY-X12",
}


def _request(msg_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def _call(msg_id: int, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return _request(msg_id, "tools/call", {"name": name, "arguments": arguments or {}})


def _serve(settings: Settings, requests: list[dict[str, Any]]) -> dict[Any, Any]:
    stdin = io.BytesIO(b"".join(json.dumps(r).encode() + b"\n" for r in requests))
    stdout = io.BytesIO()
    serve(settings, stdin=stdin, stdout=stdout)
    return {reply["id"]: reply for reply in map(json.loads, stdout.getvalue().splitlines())}


def lines_of(folder: Path, name: str = SERVER_FILE) -> list[dict[str, Any]]:
    """Every line of a diagnostics file, each checked: shorter than 2 KB, ASCII JSON,
    and nothing the allowlist would drop."""
    path = folder / name
    if not path.exists():
        return []
    out = []
    for line in path.read_bytes().splitlines():
        assert len(line) + 1 < LINE_LIMIT
        line.decode("ascii")
        record = json.loads(line)
        records = SERVER_RECORDS if name.startswith("server") else HOOK_RECORDS
        assert clean_record(records, record) == record  # nothing outside the allowlist
        out.append(record)
    return out


@pytest.fixture
def fake() -> Any:
    server = FakeOdoo()
    yield server
    server.close()


@pytest.fixture
def crash_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(ctx: Any, args: dict[str, Any]) -> Any:
        raise RuntimeError(f"{CANARY['crash']} {args}")

    monkeypatch.setitem(registry._tools, "t_crash", ToolDef(
        name="t_crash", description="raises", input_schema={"type": "object"},
        handler=handler, access=NO_MODEL))


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# --- the allowlist, end to end -----------------------------------------------------------

def _legacy_odoo(fake: FakeOdoo) -> None:
    """Odoo 19 behind basic auth: the web probe answers, then /jsonrpc signs in. A
    fields_get comes back as an AccessError that echoes its arguments."""
    fake.serve_version()

    def dispatch(request: dict[str, Any]) -> Any:
        params = request["body"]["params"]
        if (params["service"], params["method"]) == ("common", "version"):
            return jsonrpc_result(version_payload())
        if (params["service"], params["method"]) == ("common", "authenticate"):
            return jsonrpc_result(2)
        _db, _uid, _secret, model, method, args, kwargs = params["args"]
        if method == "fields_get":
            return json_reply(200, {"jsonrpc": "2.0", "id": 1, "error": {
                "code": 200, "message": "Odoo Server Error",
                "data": {"name": "odoo.exceptions.AccessError", "arguments": [],
                         "message": f"{CANARY['fault']} {model} {args} {kwargs}",
                         "debug": f"Traceback\n{CANARY['fault']}"}}})
        if method == "search_count":
            return jsonrpc_result(0)
        return jsonrpc_result(False)

    fake.on("POST", "/jsonrpc", dispatch)


def _canary_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, url: str) -> Path:
    policy_dir = tmp_path / CANARY["policy_dir"]
    policy_dir.mkdir(exist_ok=True)
    policy_file = policy_dir / "policy.json"
    policy_file.write_text('{"version": 1, "models": {"res.partner": {"read": true}}}')
    policy_file.chmod(0o600)
    for name, value in {
        "ODOO_URL": url, "ODOO_DB": CANARY["db"], "ODOO_LOGIN": CANARY["login"],
        "ODOO_API_KEY": CANARY["api_key"], "ODOO_PASSWORD": CANARY["password"],
        "ODOO_HTTP_BEARER": CANARY["bearer"], "ODOO_POLICY_FILE": str(policy_file),
        "ODOO_DIAG_DIR": str(tmp_path / "diag"), "ODOO_AUDIT_DIR": str(tmp_path / "audit"),
        "CLAUDE_CODE_ENTRYPOINT": "cli",
    }.items():
        monkeypatch.setenv(name, value)
    return policy_file


def test_no_canary_reaches_a_file_or_the_report(
        tmp_path: Path, fake: FakeOdoo, crash_tool: None, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    from odoo_mcp.__main__ import main

    _legacy_odoo(fake)
    host = fake.url.split("//", 1)[1]
    policy_file = _canary_env(
        monkeypatch, tmp_path, f"http://{CANARY['user']}:{CANARY['url_password']}@{host}")
    assert not load_policy(Settings.from_env(), TOOL_NAMES).locked
    replies = _serve(Settings.from_env(), [
        _request(1, "initialize", {"protocolVersion": "2025-06-18"}),
        _call(2, "odoo_version"),
        _call(3, "odoo_fields_get", {"model": "res.partner", "attributes": [CANARY["argument"]]}),
        _call(4, "t_crash", {"x": CANARY["argument"]}),
    ])
    assert replies[2]["result"]["isError"] is False  # signed in over /jsonrpc
    assert replies[3]["result"]["isError"] is True and replies[4]["result"]["isError"] is True
    # A second run that cannot connect: the URL carries a path, and nothing listens.
    monkeypatch.setenv("ODOO_URL", f"http://{CANARY['user']}:{CANARY['url_password']}"
                                   f"@127.0.0.1:{_closed_port()}/{CANARY['path']}")
    _serve(Settings.from_env(), [_call(1, "odoo_version")])

    records = lines_of(tmp_path / "diag")
    assert [r["event"] for r in records] == ["start", "connect", "crash", "stop",
                                             "start", "connect", "stop"]
    start, connected, crash, stop, _start, failed, stopped = records
    assert start["settings"] == {"url": True, "db": True, "login": True}
    assert start["credential"] == "api_key" and start["entrypoint"] == "cli"
    assert start["policy"]["profile"] == "standard" and start["policy"]["locked"] is False
    assert connected == {**connected, "ok": True, "transport": "jsonrpc", "odoo_major": 19,
                         "edition": "community", "deployment": "onprem"}
    assert crash["error"] == "RuntimeError" and crash["where"] == "tool"
    assert stop["calls"] == 3 and stop["errors"] == {"access": 1, "other": 1}
    assert failed["ok"] is False and failed["category"] == "network"
    assert stopped["errors"] == {"network": 1}

    main(["--diagnose"])  # the folders from ODOO_DIAG_DIR and ODOO_AUDIT_DIR
    text = capsys.readouterr().out
    main(["--diagnose", "--json", "--diag-dir", str(tmp_path / "diag"),
          "--audit-dir", str(tmp_path / "audit")])
    report = capsys.readouterr().out
    assert json.loads(report)["audit"]["calls"] == 4
    audit = "".join(p.read_text() for p in (tmp_path / "audit").iterdir())
    assert CANARY["db"] in audit and CANARY["login"] in audit  # the audit names the user
    files = "".join(p.read_text() for p in (tmp_path / "diag").iterdir())
    for name, canary in CANARY.items():
        for where, blob in (("diagnostics files", files), ("report", text),
                            ("JSON report", report)):
            assert canary not in blob, f"{name} in the {where}"
    for blob in (files, text, report):
        assert str(policy_file) not in blob and "127.0.0.1" not in blob


# --- where it writes ---------------------------------------------------------------------

@pytest.mark.parametrize("value", ["", "off", " OFF ", "relative/diag",
                                   "${CLAUDE_PLUGIN_DATA}/diagnostics", "stderr"])
def test_off_unset_or_not_a_folder_writes_nothing(value: str, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(diag_dir=value, audit_dir="off")
    assert Diagnostics.from_settings(settings).enabled is False
    replies = _serve(settings, [_call(1, "odoo_version")])
    assert replies[1]["result"]["isError"] is True  # no credentials: unchanged answer
    assert list(tmp_path.iterdir()) == []


def test_the_folder_comes_from_odoo_diag_dir(monkeypatch: pytest.MonkeyPatch,
                                             tmp_path: Path) -> None:
    monkeypatch.delenv("ODOO_DIAG_DIR", raising=False)
    assert Settings.from_env().diag_dir == "" and Settings().diag_dir == ""
    # A host that leaves the plugin's folder unresolved: kept as given (as ODOO_AUDIT_DIR
    # is), and not a folder, so the diagnostics are off.
    monkeypatch.setenv("ODOO_DIAG_DIR", "${CLAUDE_PLUGIN_DATA}/diagnostics")
    assert Diagnostics.from_settings(Settings.from_env()).enabled is False
    monkeypatch.setenv("ODOO_DIAG_DIR", "${user_config.diag}")
    assert Settings.from_env().diag_dir == ""  # a bare placeholder is unset
    monkeypatch.setenv("ODOO_DIAG_DIR", f" {tmp_path} ")
    settings = Settings.from_env()
    assert settings.diag_dir == str(tmp_path)
    assert Diagnostics.from_settings(settings).directory == str(tmp_path)
    # The startup log says whether diagnostics are on, never where.
    assert settings.redacted()["diagnostics"] is True
    assert str(tmp_path) not in repr(settings)
    assert Settings(diag_dir="off").redacted()["diagnostics"] is False


def test_the_plugin_passes_its_data_folder_and_nothing_else_changed() -> None:
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    env = manifest["mcpServers"]["odoo"]["env"]
    assert env["ODOO_DIAG_DIR"] == "${CLAUDE_PLUGIN_DATA}/diagnostics"
    names = list(env)
    assert names.index("ODOO_DIAG_DIR") == names.index("ODOO_AUDIT_DIR") + 1
    assert set(env) == {"ODOO_URL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY", "ODOO_PASSWORD",
                        "ODOO_TRANSPORT_PREF", "ODOO_TIMEOUT", "ODOO_READONLY", "ODOO_POLICY",
                        "ODOO_POLICY_FILE", "ODOO_AUDIT_DIR", "ODOO_DIAG_DIR",
                        "ODOO_AUDIT_RETENTION_DAYS"}


# --- the files ---------------------------------------------------------------------------

def test_a_full_file_is_renamed_and_a_new_one_starts(tmp_path: Path) -> None:
    assert ROTATE_AT == 256 * 1024
    folder = tmp_path / "diag"
    policy = load_policy(Settings(), TOOL_NAMES)
    seconds = iter(range(10_000))  # a new second per line, so no two lines are equal
    start = datetime.datetime(2026, 10, 29, tzinfo=datetime.timezone.utc)
    diag = Diagnostics(str(folder), rotate_at=1000,
                       clock=lambda: start + datetime.timedelta(seconds=next(seconds)))

    def write() -> None:
        diag.start(Settings(), policy, "off", environ={})

    write()
    per_file = -(-1000 // (folder / SERVER_FILE).stat().st_size)  # lines that reach 1000
    for _ in range(per_file - 1):
        write()
    assert not (folder / "server.jsonl.1").exists()
    first = (folder / SERVER_FILE).read_bytes()
    write()  # the file reached the limit: it is renamed before this line
    assert (folder / "server.jsonl.1").read_bytes() == first
    assert len(lines_of(folder)) == 1
    for _ in range(per_file):
        write()
    # The second rotation replaced the older .1: nothing else accumulates.
    assert sorted(p.name for p in folder.iterdir()) == ["server.jsonl", "server.jsonl.1"]
    assert (folder / "server.jsonl.1").read_bytes() != first
    assert len(lines_of(folder, "server.jsonl.1")) == per_file
    assert len(lines_of(folder)) == 1


def test_a_folder_in_place_of_the_old_file_does_not_stop_the_lines(tmp_path: Path) -> None:
    folder = tmp_path / "diag"
    (folder / "server.jsonl.1").mkdir(parents=True)
    append_line(str(folder), SERVER_FILE, b"x" * 50 + b"\n", rotate_at=10)
    append_line(str(folder), SERVER_FILE, b"y" * 50 + b"\n", rotate_at=10)
    assert (folder / SERVER_FILE).read_bytes() == b"x" * 50 + b"\n" + b"y" * 50 + b"\n"


@POSIX
def test_modes_are_owner_only_and_a_loose_file_is_tightened(tmp_path: Path) -> None:
    folder = tmp_path / "diag"
    diag = Diagnostics(str(folder))
    diag.stop()
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE((folder / SERVER_FILE).stat().st_mode) == 0o600
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / SERVER_FILE).write_text("")
    (loose / SERVER_FILE).chmod(0o644)
    Diagnostics(str(loose)).stop()
    assert stat.S_IMODE((loose / SERVER_FILE).stat().st_mode) == 0o600
    assert lines_of(loose)[0]["event"] == "stop"


@POSIX
def test_a_symlink_is_never_followed(tmp_path: Path) -> None:
    folder = tmp_path / "diag"
    folder.mkdir()
    target = tmp_path / "elsewhere.txt"
    target.write_text("untouched\n")
    (folder / SERVER_FILE).symlink_to(target)
    Diagnostics(str(folder)).stop()
    assert target.read_text() == "untouched\n"


@pytest.mark.parametrize("breakage", ["file-as-folder", "folder-as-file", "fifo"])
def test_an_unusable_folder_never_reaches_the_tools(breakage: str, tmp_path: Path) -> None:
    folder = tmp_path / "diag"
    if breakage == "file-as-folder":
        folder.write_text("a file where the folder should be")
    elif breakage == "folder-as-file":
        (folder / SERVER_FILE).mkdir(parents=True)
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("no FIFO on this platform")
        folder.mkdir()
        os.mkfifo(folder / SERVER_FILE)  # opened non-blocking: never hangs
    settings = Settings(diag_dir=str(folder), audit_dir="off")
    replies = _serve(settings, [_request(1, "ping"), _call(2, "odoo_version")])
    assert replies[1]["result"] == {}
    assert "ODOO_URL" in replies[2]["result"]["content"][0]["text"]


def test_a_writer_that_fails_is_swallowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                          caplog: pytest.LogCaptureFixture) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(diag_module, "append_line", broken)
    diag = Diagnostics(str(tmp_path / "diag"))
    caplog.set_level("DEBUG", logger="odoo_mcp.diagnostics")
    diag.start(Settings(), load_policy(Settings(), TOOL_NAMES), "off")
    diag.tool_call(ConfigError("x"))
    diag.connection(None, ConfigError("x"))
    diag.crash(RuntimeError("x"), "tool")
    diag.stop()
    assert all(r.levelname == "DEBUG" for r in caplog.records if r.name.endswith("diagnostics"))
    assert not (tmp_path / "diag").exists()


# --- the lifecycle -----------------------------------------------------------------------

def _json2_odoo(fake: FakeOdoo, version: str = "19.0-20260926") -> None:
    fake.serve_version(version)
    fake.serve_json2(lambda model, method, body: 0 if method == "search_count" else False)


def _settings(tmp_path: Path, fake: FakeOdoo, **extra: Any) -> Settings:
    return Settings(url=fake.url, db="db", login="admin", api_key="key",
                    diag_dir=str(tmp_path / "diag"), audit_dir="off", **extra)


def test_the_start_line_says_what_is_set_never_the_values(tmp_path: Path) -> None:
    folder = tmp_path / "diag"
    policy = load_policy(Settings(), TOOL_NAMES)
    cases = [(Settings(url="https://x.example", password="p"), "password",
              {"CLAUDE_CODE_ENTRYPOINT": "claude-desktop"}, "claude-desktop"),
             (Settings(db="d", login="l", api_key="k", password="p"), "api_key",
              {"CLAUDE_CODE_ENTRYPOINT": "bad value!"}, "other"),
             (Settings(transport_pref="xmlrpc", readonly=True), "none", {}, None)]
    for settings, credential, environ, entrypoint in cases:
        Diagnostics(str(folder)).start(settings, policy, "stderr", environ=environ)
    lines = lines_of(folder)
    for line, (settings, credential, _environ, entrypoint) in zip(lines, cases):
        assert list(line)[:4] == ["v", "ts", "event", "pid"] and line["pid"] == os.getpid()
        assert line["credential"] == credential and line.get("entrypoint") == entrypoint
        assert line["settings"] == {name: bool(getattr(settings, name))
                                    for name in ("url", "db", "login")}
        assert line["transport"] == settings.transport_pref
        assert line["readonly"] is settings.readonly and line["audit"] == "stderr"
        assert line["plugin"] == diag_module.PLUGIN_VERSION
        assert set(line["os"]) == {"system", "release", "machine"}
        assert line["policy"] == {"profile": "standard", "digest": policy.digest,
                                  "locked": False}
    assert "entrypoint" not in lines[2]  # unset: left out


def test_a_locked_start_carries_the_e_code_and_no_digest(tmp_path: Path) -> None:
    settings = Settings(policy_profile="readonyl", diag_dir=str(tmp_path / "diag"),
                        audit_dir="off")
    _serve(settings, [_call(1, "odoo_version")])
    start, stop = lines_of(tmp_path / "diag")
    assert start["policy"] == {"profile": "unknown", "locked": True, "code": "E1"}
    assert stop["calls"] == 1 and stop["errors"] == {}  # the locked odoo_version answers


def test_connect_success_with_the_facts_already_known(tmp_path: Path, fake: FakeOdoo) -> None:
    _json2_odoo(fake, "19.0+e-20260926")
    replies = _serve(_settings(tmp_path, fake),
                     [_call(1, "odoo_version"), _call(2, "odoo_version")])
    assert json.loads(replies[1]["result"]["content"][0]["text"])["transport"] == "json2"
    start, connected, stop = lines_of(tmp_path / "diag")
    assert {k: connected[k] for k in ("ok", "transport", "odoo_major", "edition",
                                      "deployment")} == {
        "ok": True, "transport": "json2", "odoo_major": 19, "edition": "enterprise",
        "deployment": "onprem"}
    assert "category" not in connected and stop["calls"] == 2 and stop["errors"] == {}
    assert start["ts"] <= connected["ts"] <= stop["ts"]
    assert isinstance(stop["uptime_s"], int) and stop["uptime_s"] >= 0


def test_a_failure_then_a_success_are_both_recorded_once(tmp_path: Path) -> None:
    diag = Diagnostics(str(tmp_path / "diag"))
    failure = AuthError("bad key")
    diag.connection(None, failure)
    diag.connection(None, TransportError("down"))  # the first failure only

    class Session:
        authenticated = True
        transport = type("T", (), {"active": "jsonrpc(auto)", "series": (17, 0)})()
        creds = type("C", (), {"url": "https://acme.odoo.com"})()

        def known_facts(self) -> None:
            return None

    diag.connection(Session(), None)
    diag.connection(Session(), None)  # once per session
    diag.connection(None, AuthError("later"))  # after a success, nothing more
    first, second = lines_of(tmp_path / "diag")
    assert (first["ok"], first["category"]) == (False, "auth")
    assert second == {**second, "ok": True, "transport": "jsonrpc", "odoo_major": 17,
                      "edition": "unknown", "deployment": "saas"}


def test_a_call_that_never_needed_odoo_records_no_connect(tmp_path: Path) -> None:
    settings = Settings(diag_dir=str(tmp_path / "diag"), audit_dir="off")
    replies = _serve(settings, [
        # A stub that never calls Odoo: it answers why it cannot work over RPC.
        _call(1, "odoo_report", {"report_name": "base.report_x", "ids": [1]}),
        _call(2, "odoo_create", {})])  # invalid: refused before a session
    assert "cannot work over RPC" in replies[1]["result"]["content"][0]["text"]
    assert "Input validation error" in replies[2]["result"]["content"][0]["text"]
    lines = lines_of(tmp_path / "diag")
    assert [line["event"] for line in lines] == ["start", "stop"]
    assert lines[-1]["calls"] == 2 and lines[-1]["errors"] == {"other": 2}


def test_crash_lines_are_capped_and_hold_frames_of_odoo_mcp_only(
        tmp_path: Path, crash_tool: None) -> None:
    settings = Settings(url="http://127.0.0.1:9", db="d", login="l", api_key="k",
                        diag_dir=str(tmp_path / "diag"), audit_dir="off")
    _serve(settings, [_call(n, "t_crash") for n in range(1, CRASH_LIMIT + 4)])
    lines = lines_of(tmp_path / "diag")
    crashes = [line for line in lines if line["event"] == "crash"]
    assert len(crashes) == CRASH_LIMIT
    for crash in crashes:
        assert set(crash) == {"v", "ts", "event", "pid", "where", "error", "frames"}
        assert crash["error"] == "RuntimeError"
        modules = [frame[0] for frame in crash["frames"]]
        assert modules and all(m.startswith("odoo_mcp") for m in modules)
        assert ["odoo_mcp.server", "call_tool"] in [frame[:2] for frame in crash["frames"]]
    assert lines[-1]["calls"] == CRASH_LIMIT + 3
    assert lines[-1]["errors"] == {"other": CRASH_LIMIT + 3}


def test_a_crash_while_serving_is_recorded_then_raised(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    from odoo_mcp.server import McpServer

    def broken(self: Any, inp: Any, out: Any) -> None:
        raise MemoryError()

    monkeypatch.setattr(McpServer, "run", broken)
    settings = Settings(diag_dir=str(tmp_path / "diag"), audit_dir="off")
    with pytest.raises(MemoryError):
        serve(settings, stdin=io.BytesIO(b""), stdout=io.BytesIO())
    start, crash, stop = lines_of(tmp_path / "diag")
    assert start["event"] == "start"
    assert (crash["where"], crash["error"]) == ("serve", "MemoryError")
    assert stop["event"] == "stop"


def test_errors_are_counted_by_category(tmp_path: Path) -> None:
    settings = Settings(readonly=True, diag_dir=str(tmp_path / "diag"), audit_dir="off")
    _serve(settings, [
        _call(1, "odoo_create", {"model": "res.partner", "values": {}}),  # read-only mode
        _call(2, "odoo_unlink", {"model": "res.partner", "ids": [1]}),  # hidden: policy
        _call(3, "odoo_search_read", {"model": 7}),  # invalid arguments
        _call(4, "odoo_search_read", {"model": "ir.config_parameter"}),  # Layer A: secrets
        _call(5, "odoo_version"),  # no credentials: config
        _call(6, "no_such_tool"),  # not a tool call of a known tool: not counted
    ])
    stop = lines_of(tmp_path / "diag")[-1]
    assert stop["calls"] == 5
    assert stop["errors"] == {"policy": 3, "other": 1, "config": 1}


def test_every_line_is_short_even_for_a_deep_crash() -> None:
    # The longest names the allowlist accepts: eight frames would not fit in 2 KB.
    module = "odoo_mcp." + ".".join(["m" * 48] * 4)
    frames = [[module, "f" * 64, 9999999 - n] for n in range(500)]
    data = encode_record(SERVER_RECORDS, {
        "v": 1, "ts": "2026-10-29T00:00:00Z", "event": "crash", "pid": 1, "where": "tool",
        "error": "E" * 64, "frames": frames})
    assert data is not None and len(data) + 1 < LINE_LIMIT
    kept = json.loads(data)["frames"]
    assert 0 < len(kept) < diag_module.FRAME_LIMIT
    assert kept[-1] == frames[-1]  # the innermost frames are the ones kept


def test_the_allowlist_drops_what_it_does_not_know() -> None:
    planted = {"v": 1, "ts": "2026-10-29T00:00:00Z", "event": "start", "pid": 1,
               "url": "https://secret.example", "db": "prod",
               "settings": {"url": "https://secret.example", "db": True, "token": "x"},
               "policy": {"profile": "standard", "digest": "/home/me/policy.json",
                          "locked": "no", "file": "/home/me/policy.json"},
               "entrypoint": "https://secret.example", "transport": "smtp"}
    assert clean_record(SERVER_RECORDS, planted) == {
        "v": 1, "ts": "2026-10-29T00:00:00Z", "event": "start", "pid": 1,
        "policy": {"profile": "standard"}, "settings": {"db": True}, "entrypoint": "other"}
    assert clean_record(SERVER_RECORDS, {**planted, "event": "unknown"}) is None
    assert clean_record(SERVER_RECORDS, {**planted, "v": True}) is None
    assert clean_record(SERVER_RECORDS, {**planted, "ts": "yesterday"}) is None


# --- error categories --------------------------------------------------------------------

def _raised(call: Any) -> BaseException:
    try:
        call()
    except BaseException as exc:  # the error is what is checked
        return exc
    raise AssertionError("no error")


def test_categories_of_the_transports_own_errors(fake: FakeOdoo) -> None:
    fake.on("POST", "/jsonrpc", html_reply(502))
    fake.on("POST", "/json/2/res.partner/read",
            odoo_error(403, "odoo.exceptions.AccessError", "you may not"))
    fake.on("POST", "/json/2/res.partner/search", json_reply(
        401, {"name": "odoo.exceptions.AccessDenied", "message": "Access Denied"}))
    fake.on("POST", "/json/2/res.partner/write", (429, {"Retry-After": "1"}, b""))
    fake.on("POST", "/json/2/res.partner/search_count", (200, {"Content-Type": "text/html"},
                                                         b"<html>proxy</html>"))
    legacy, j2 = JsonRpcTransport(fake.url), Json2Transport(fake.url)
    cases = {
        "http 502": legacy.version,
        "http 404": lambda: j2.execute_kw("db", 2, "k", "res.partner", "unlink", [[1]]),
        "access": lambda: j2.execute_kw("db", 2, "k", "res.partner", "read", [[1]]),
        "auth": lambda: j2.execute_kw("db", 2, "k", "res.partner", "search", [[]]),
        "http 429": lambda: j2.execute_kw("db", 2, "k", "res.partner", "write", [[1], {}]),
        "protocol": lambda: j2.execute_kw("db", 2, "k", "res.partner", "search_count", [[]]),
        "network": JsonRpcTransport(f"http://127.0.0.1:{_closed_port()}").version,
        "tls": JsonRpcTransport(fake.url.replace("http://", "https://")).version,
        "config": JsonRpcTransport("odoo.example.com").version,
    }
    for expected, call in cases.items():
        category, _, status = expected.partition(" ")
        exc = _raised(call)
        assert error_category(exc) == (category, int(status) if status else None), expected
    fault = _raised(lambda: j2.execute_kw("db", 2, "k", "res.partner", "read", [[1]]))
    assert isinstance(fault, OdooFault) and fault.odoo_name == "odoo.exceptions.AccessError"


def test_a_jsonrpc_fault_keeps_the_odoo_exception_name(fake: FakeOdoo) -> None:
    fake.on("POST", "/jsonrpc", json_reply(200, {"jsonrpc": "2.0", "id": 1, "error": {
        "code": 200, "message": "Odoo Server Error",
        "data": {"name": "odoo.exceptions.AccessError", "message": "nope"}}}))
    exc = _raised(lambda: JsonRpcTransport(fake.url).execute_kw("d", 2, "k", "res.partner",
                                                                 "read", [[1]]))
    assert isinstance(exc, OdooFault) and exc.odoo_name == "odoo.exceptions.AccessError"
    assert str(exc) == "Odoo Server Error | nope"  # the message is unchanged
    assert error_category(exc) == ("access", None)


def test_a_timeout_is_a_timeout(fake: FakeOdoo) -> None:
    def slow(request: dict[str, Any]) -> Any:
        time.sleep(1.0)
        return jsonrpc_result(version_payload())

    fake.on("POST", "/jsonrpc", slow)
    exc = _raised(JsonRpcTransport(fake.url, timeout=0.3).version)  # type: ignore[arg-type]
    assert error_category(exc) == ("timeout", None)


def test_categories_of_other_errors() -> None:
    def xmlrpc_fault(code: int) -> BaseException:
        def raise_it() -> None:
            try:
                raise xmlrpc.client.Fault(code, "denied")
            except xmlrpc.client.Fault as fault:
                raise OdooFault("denied") from fault
        return _raised(raise_it)

    assert error_category(xmlrpc_fault(4)) == ("access", None)
    assert error_category(xmlrpc_fault(1)) == ("other", None)
    assert error_category(PolicyDenied("no", rule="tier:secrets")) == ("policy", None)
    assert error_category(ConfigError("missing")) == ("config", None)
    assert error_category(RateLimited("xmlrpc: HTTP 429 Too Many")) == ("http", 429)
    assert error_category(TransportError("jsonrpc: the reply is not a JSON-RPC object")) == (
        "protocol", None)
    assert error_category(RuntimeError("boom")) == ("other", None)
    assert set(CATEGORIES) == {"config", "auth", "access", "network", "timeout", "tls", "http",
                               "protocol", "policy", "other"}


def test_the_status_comes_from_the_transport_never_from_odoo_text() -> None:
    # An Odoo fault is never parsed for a status: its text is Odoo's, not the transport's.
    assert error_category(OdooFault("HTTP 404 in a record name")) == ("other", None)


def test_the_utc_clock_is_used(tmp_path: Path) -> None:
    clock = datetime.datetime(2026, 10, 29, 1, 2, 3, tzinfo=datetime.timezone(
        datetime.timedelta(hours=-6)))
    Diagnostics(str(tmp_path), clock=lambda: clock).stop()
    assert lines_of(tmp_path)[0]["ts"] == "2026-10-29T07:02:03Z"


@pytest.mark.skipif(os.name == "nt", reason="symbolic links need privileges on Windows")
def test_a_symlinked_folder_is_not_written_through(tmp_path: Path) -> None:
    # O_NOFOLLOW guards the file name only; the folder itself is checked too.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = tmp_path / "diagnostics"
    link.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(OSError):
        append_line(str(link), "server.jsonl", b'{"v":1}\n')
    assert list(elsewhere.iterdir()) == []
