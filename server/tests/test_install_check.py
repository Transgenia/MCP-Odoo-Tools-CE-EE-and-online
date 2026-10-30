# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Which odoo-tools copy runs, and whether its options are complete (1.6.0).

A Windows onboarding on 2026-10-29 ended with two copies active in one folder: 1.4.0
from the Claude plugin directory (project scope, no permission policy) and 1.5.1
from Transgenia's marketplace (user scope). The options dialog saved the connection
in the 1.4.0 copy, and nothing told which copy answered odoo_version. These tests
pin the three answers 1.6.0 gives: ``odoo_version`` names the copy,
``--check-copies`` finds the duplicate and the old copy, ``--check-options`` finds a
copy without the permission options or with an incomplete connection.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fake_odoo_http import FakeOdoo

from odoo_mcp import __version__
from odoo_mcp.__main__ import main
from odoo_mcp.config import Settings
from odoo_mcp.install_check import (
    check_copies,
    check_main,
    check_options,
    parse_version,
    plugin_identity,
)
from odoo_mcp.server import McpServer, serve

HOME = os.path.expanduser("~")
TEST_FOLDER = os.path.join(HOME, "Downloads", "Test-Oct2026")
RUN_STDIO = Path(__file__).resolve().parents[1] / "run_stdio.py"
UPDATE = ["claude plugin marketplace update transgenia-odoo-tools",
          "claude plugin update odoo-tools@transgenia-odoo-tools --scope user"]
INSTALL = ("claude plugin install odoo-tools --marketplace "
           "Transgenia/MCP-Odoo-Tools-CE-EE-and-online --scope user")

# `claude plugin list --json` as Claude Code 2.1.314 prints it, inside the project
# folder of the Windows case (fields the check does not read are left out).
WINDOWS_LIST: list[dict[str, Any]] = [
    {"id": "odoo-tools@anthropic-plugin-directory", "version": "1.4.0-26de374ed2c6",
     "scope": "project", "enabled": True, "projectPath": TEST_FOLDER, "projectEnabled": True,
     "hasUserConfig": True},
    {"id": "odoo-tools@transgenia-odoo-tools", "version": "1.5.1", "scope": "user",
     "enabled": True, "hasUserConfig": True},
    {"id": "odoo-tools-premium@synced", "version": "0.2.0", "scope": "synced",
     "enabled": True},
    {"id": "odoo-tools@synced", "version": "unknown", "scope": "synced", "enabled": True,
     "installPath": "", "noteDetails": [{"type": "synced-plugin-shadowed",
                                         "related": "odoo-tools@transgenia-odoo-tools"}]},
]

SECRET = "4d1f-NOT-A-REAL-KEY-9c2e"


def _schema(with_policy: bool) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "odoo_url": {"type": "string", "title": "Odoo URL", "required": True},
        "odoo_db": {"type": "string", "title": "Odoo database", "required": True},
        "odoo_login": {"type": "string", "title": "Odoo login", "required": True},
        "odoo_api_key": {"type": "string", "title": "Odoo API key", "sensitive": True},
        "odoo_password": {"type": "string", "title": "Odoo password", "sensitive": True},
        "odoo_transport_pref": {"type": "string", "default": "auto"},
        "odoo_timeout": {"type": "number", "default": 120},
        "odoo_readonly": {"type": "boolean", "default": False},
    }
    if with_policy:
        schema["odoo_policy"] = {"type": "string", "default": "standard"}
        schema["odoo_policy_file"] = {"type": "string", "default": ""}
    return schema


def _options(plugin_id: str = "odoo-tools@transgenia-odoo-tools", with_policy: bool = True,
             configured: tuple[str, ...] = ("odoo_url", "odoo_db", "odoo_login",
                                            "odoo_api_key"),
             **inputs: str) -> dict[str, Any]:
    values = {"odoo_url": "https://my-company.odoo.com", "odoo_db": "my-company",
              "odoo_login": "bot@my-company.example", "odoo_api_key": "",
              "odoo_password": "", "odoo_readonly": "true", "odoo_timeout": "",
              "odoo_policy": "", "odoo_policy_file": ""}
    values.update(inputs)
    schema = _schema(with_policy)
    return {"pluginId": plugin_id, "displayName": "Odoo Tools", "schema": schema,
            "inputs": {k: v for k, v in values.items() if k in schema},
            "configured": list(configured),
            "unconfigured": [k for k in schema if k not in configured]}


def _run(kind: str, payload: Any, as_json: bool = False) -> tuple[int, str]:
    out = io.StringIO()
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    code = check_main(kind, io.StringIO(raw), out, as_json=as_json)
    return code, out.getvalue()


# ------------------------------------------------------------------ versions


@pytest.mark.parametrize(("text", "expected"), [
    ("1.4.0-26de374ed2c6", (1, 4, 0)), ("1.5.1", (1, 5, 1)), ("1.6", (1, 6, 0)),
    ("unknown", None), ("", None), (None, None), (150, None)])
def test_parse_version(text: Any, expected: Any) -> None:
    assert parse_version(text) == expected


# ------------------------------------------------------------ plugin identity


@pytest.mark.parametrize(("diag", "audit", "copy"), [
    ("/home/u/.claude/plugins/data/odoo-tools-transgenia-odoo-tools/diagnostics", "",
     "odoo-tools@transgenia-odoo-tools"),
    (r"C:\Users\u\.claude\plugins\data\odoo-tools-anthropic-plugin-directory\diagnostics",
     "", "odoo-tools@anthropic-plugin-directory"),
    ("off", "/home/u/.claude/plugins/data/odoo-tools-synced/audit", "odoo-tools@synced"),
    ("/home/u/.odoo-tools/desktop/diagnostics", "/home/u/.odoo-tools/desktop/audit", None),
    ("", "", None),
    ("/home/u/.claude/plugins/data/other-plugin/diagnostics", "", None),
    ("/home/u/.claude/plugins/data/odoo-tools-/diagnostics", "", None),
])
def test_plugin_identity_names_the_copy_from_its_data_folder(diag: str, audit: str,
                                                              copy: str | None) -> None:
    identity = plugin_identity(diag, audit)
    assert identity["name"] == "odoo-tools" and identity["version"] == __version__
    assert identity.get("copy") == copy


def test_odoo_version_names_the_copy_even_when_the_policy_is_locked(tmp_path: Path) -> None:
    data = tmp_path / ".claude" / "plugins" / "data" / "odoo-tools-transgenia-odoo-tools"
    server = McpServer(Settings(policy_profile="readonyl", diag_dir=str(data / "diagnostics"),
                                audit_dir="off"))
    result = server.call_tool({"name": "odoo_version", "arguments": {}})
    body = json.loads(result["content"][0]["text"])
    assert body["plugin"] == {"name": "odoo-tools", "version": __version__,
                              "copy": "odoo-tools@transgenia-odoo-tools"}
    assert "note" in body and "policy" in body  # locked: the cause, not a success


def test_odoo_version_puts_the_plugin_next_to_the_policy(tmp_path: Path) -> None:
    fake = FakeOdoo()
    try:
        fake.serve_version("19.0-20260926")
        fake.serve_json2(lambda model, method, body: 0 if method == "search_count" else False)
        data = tmp_path / ".claude" / "plugins" / "data" / "odoo-tools-synced"
        settings = Settings(url=fake.url, db="db", login="admin", api_key="key",
                            diag_dir=str(data / "diagnostics"), audit_dir="off")
        stdin = io.BytesIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                       "params": {"name": "odoo_version",
                                                  "arguments": {}}}).encode() + b"\n")
        stdout = io.BytesIO()
        serve(settings, stdin=stdin, stdout=stdout)
    finally:
        fake.close()
    reply = json.loads(stdout.getvalue().splitlines()[0])
    body = json.loads(reply["result"]["content"][0]["text"])
    assert body["plugin"]["copy"] == "odoo-tools@synced"
    assert body["version"] == 19 and "policy" in body  # a 1.5.0+ answer has both


# --------------------------------------------------------------- --check-copies


def test_the_windows_case_finds_the_duplicate_and_the_old_copy() -> None:
    report = check_copies(WINDOWS_LIST)
    codes = [p["code"] for p in report.problems]
    assert codes == ["duplicates", "no-policy"]
    assert report.data["keep"] == "odoo-tools@transgenia-odoo-tools"
    assert "1.4.0-26de374ed2c6" in report.problems[1]["text"]
    # The exact commands, for the terminal, from the project folder.
    assert report.terminal == [
        "cd ~/Downloads/Test-Oct2026",
        "claude plugin uninstall odoo-tools@anthropic-plugin-directory --scope project"]
    assert report.session == []
    text = report.render()
    assert "not loaded   odoo-tools@synced" in text and "takes precedence" in text
    assert "odoo-tools-premium" not in text  # only odoo-tools copies
    assert HOME not in text  # the home folder is written as ~


def test_one_current_copy_is_fine_and_the_claude_ai_copy_behind_it_too() -> None:
    entries = [WINDOWS_LIST[1], WINDOWS_LIST[3]]
    code, text = _run("copies", entries)
    assert code == 0 and text.endswith("Result: ok\n")


def test_a_project_copy_of_another_folder_is_not_active_here() -> None:
    other = dict(WINDOWS_LIST[0], enabled=False, projectEnabled=False)
    report = check_copies([other, WINDOWS_LIST[1]])
    assert report.ok and "other folder" in report.render()


def test_an_old_synced_copy_alone_gets_the_current_install_command() -> None:
    synced = {"id": "odoo-tools@synced", "version": "1.4.0", "scope": "synced",
              "enabled": True}
    report = check_copies([synced])
    assert [p["code"] for p in report.problems] == ["no-policy"]
    assert report.terminal == [("claude plugin install odoo-tools --marketplace "
                                "Transgenia/MCP-Odoo-Tools-CE-EE-and-online --scope user")]


def test_two_current_copies_keep_transgenias_and_drop_the_other() -> None:
    a = {"id": "odoo-tools@anthropic-plugin-directory", "version": "1.6.0", "scope": "user",
         "enabled": True}
    report = check_copies([a, WINDOWS_LIST[1]])
    assert [p["code"] for p in report.problems] == ["duplicates"]
    assert report.data["keep"] == "odoo-tools@transgenia-odoo-tools"
    assert report.terminal == [
        "claude plugin uninstall odoo-tools@anthropic-plugin-directory --scope user"]


def test_no_copy_at_all() -> None:
    report = check_copies([{"id": "odoo-tools-premium@synced", "version": "0.3.0",
                            "scope": "synced", "enabled": True}])
    assert [p["code"] for p in report.problems] == ["none"]
    assert report.terminal[0].startswith("claude plugin install odoo-tools --marketplace")


@pytest.mark.parametrize("here", [True, False])
def test_one_plugin_id_installed_in_two_scopes_is_one_copy(here: bool) -> None:
    # Claude Code 2.1.314, one id at user scope and at project scope in folder "two",
    # listed in that folder (here) and in an unrelated one: `enabled` and
    # `projectEnabled` are per id and folder, not per installation.
    entries = [
        {"id": "odoo-tools@transgenia-odoo-tools", "version": "1.6.0", "scope": "user",
         "enabled": True, "projectPath": None, "projectEnabled": here},
        {"id": "odoo-tools@transgenia-odoo-tools", "version": "1.6.0", "scope": "project",
         "enabled": True, "projectPath": os.path.join(HOME, "projects", "two"),
         "projectEnabled": here},
    ]
    report = check_copies(entries)
    assert report.ok and report.terminal == [], report.render()
    assert [c["state"] for c in report.data["copies"]] == (
        ["active", "active"] if here else ["active", "other folder"])


def test_an_old_copy_from_transgenias_marketplace_is_updated_not_reinstalled() -> None:
    # Uninstall then install --marketplace reused the outdated local copy of the
    # marketplace and put 1.4.0 back, a loop; marketplace update then plugin update
    # moved it (Claude Code 2.1.314).
    old = {"id": "odoo-tools@transgenia-odoo-tools", "version": "1.4.0", "scope": "user",
           "enabled": True}
    report = check_copies([old])
    assert [p["code"] for p in report.problems] == ["no-policy"]
    assert report.terminal == UPDATE


def test_an_old_project_copy_is_updated_from_its_folder() -> None:
    old = {"id": "odoo-tools@transgenia-odoo-tools", "version": "1.4.0", "scope": "project",
           "enabled": True, "projectPath": TEST_FOLDER, "projectEnabled": True}
    assert check_copies([old]).terminal == [
        "cd ~/Downloads/Test-Oct2026", UPDATE[0],
        "claude plugin update odoo-tools@transgenia-odoo-tools --scope project"]


def test_a_known_marketplace_is_updated_before_an_install() -> None:
    disabled = {"id": "odoo-tools@transgenia-odoo-tools", "version": "1.5.1", "scope": "user",
                "enabled": False}
    report = check_copies([disabled])
    assert [p["code"] for p in report.problems] == ["none"]
    assert report.terminal == [UPDATE[0], INSTALL]


@pytest.mark.parametrize(("folder", "line"), [
    (os.path.join(HOME, "R&D"), 'cd ~/"R&D"'),
    (os.path.join(HOME, "proj(1)"), 'cd ~/"proj(1)"'),
    (os.path.join(HOME, "O'Brien"), "cd ~/\"O'Brien\""),
    (os.path.join(HOME, "Documents", "José"), 'cd ~/"Documents/José"'),
    ("D:\\Proyectos\\Odoo App", 'cd "D:/Proyectos/Odoo App"'),
    ("D:\\Proyectos\\odoo", "cd D:/Proyectos/odoo"),
    (os.path.join(HOME, "Cost$Center"), "# first change to this folder by hand: ~/Cost$Center"),
    (os.path.join(HOME, "hey!"), "# first change to this folder by hand: ~/hey!"),
])
def test_the_cd_line_is_quoted_whenever_a_shell_would_read_the_path(folder: str,
                                                                    line: str) -> None:
    entry = dict(WINDOWS_LIST[0], projectPath=folder)
    assert check_copies([entry, WINDOWS_LIST[1]]).terminal[0] == line


def test_a_folder_with_a_space_gets_a_cd_that_bash_and_powershell_both_read() -> None:
    spaced = dict(WINDOWS_LIST[0], projectPath=os.path.join(HOME, "My Projects", "odoo"))
    report = check_copies([spaced, WINDOWS_LIST[1]])
    assert report.terminal[0] == 'cd ~/"My Projects/odoo"'


# -------------------------------------------------------------- --check-options


def test_the_directory_copy_of_the_windows_case_has_no_permission_options() -> None:
    doc = _options("odoo-tools@anthropic-plugin-directory", with_policy=False,
                   odoo_url="https://my-company.odoo.com/", odoo_timeout="15",
                   odoo_readonly="false")
    report = check_options(doc)
    assert [p["code"] for p in report.problems] == ["no-policy"]
    text = report.render()
    assert "the trailing / of the Odoo URL is ignored" in text
    assert "a request timeout of 15 s is short" in text
    assert "Read-only mode: off" in text


def test_an_unconfigured_copy_lists_what_is_missing_and_where_to_type_it() -> None:
    doc = _options(configured=(), odoo_url="", odoo_db="", odoo_login="")
    report = check_options(doc)
    assert [p["code"] for p in report.problems] == ["missing", "missing", "missing",
                                                    "no-credential"]
    assert report.session == ["/plugin configure odoo-tools@transgenia-odoo-tools"]
    assert report.terminal == []  # a slash command never goes to the terminal


def test_a_complete_copy_passes_and_shows_its_permission_options() -> None:
    code, text = _run("options", _options(odoo_policy="readonly"))
    assert code == 0
    assert "Permission profile: readonly" in text and "Read-only mode: on" in text
    assert "Credential: API key" in text


@pytest.mark.parametrize(("url", "fragment"), [
    ("https://my-company.odoo.com/web",
     "use https://my-company.odoo.com, without its path, query or fragment"),
    ("https://my-company.odoo.com/odoo?debug=1", "without its path, query or fragment"),
    ("my-company.odoo.com", "needs a scheme and a host"),
])
def test_the_url_must_be_scheme_and_host(url: str, fragment: str) -> None:
    report = check_options(_options(odoo_url=url))
    assert [p["code"] for p in report.problems] == ["url"]
    assert fragment in report.problems[0]["text"]
    assert report.session == ["/plugin configure odoo-tools@transgenia-odoo-tools"]


def test_a_url_with_a_user_name_and_password_is_refused_and_never_echoed() -> None:
    report = check_options(_options(odoo_url=f"https://bot:{SECRET}@my-company.odoo.com"))
    assert "url" in [p["code"] for p in report.problems]
    assert SECRET not in report.render() and SECRET not in json.dumps(report.as_dict())


@pytest.mark.parametrize("url", [
    f"admin:{SECRET}@erp.example.com",           # no scheme: urlsplit finds no host
    f"https//admin:{SECRET}@erp.example.com",    # a missing colon
    f"https:admin:{SECRET}@erp.example.com",     # missing slashes
    f"http:/admin:{SECRET}@erp.example.com",
    f"https://admin:{SECRET}@erp.example.com",
    f"https://erp.example.com/my/orders/7?access_token={SECRET}",  # a copied portal link
    f"https://erp.example.com/web#{SECRET}",
    f"https://erp.example.com/{SECRET}/web",
])
def test_nothing_of_the_url_but_its_scheme_and_host_is_ever_shown(url: str) -> None:
    # Review of 1.6.0: without "//" no host was parsed, the user info was not stripped
    # and the URL was printed as typed; a path, query or fragment was echoed in the
    # problem text. The guided route runs this check through Claude's Bash tool.
    for as_json in (False, True):
        code, text = _run("options", _options(odoo_url=url), as_json=as_json)
        assert code == 1 and SECRET not in text
    if "@" in url:
        texts = [p["text"] for p in check_options(_options(odoo_url=url)).problems]
        assert any("user name or password" in t for t in texts)


def test_a_url_without_a_host_is_not_shown_at_all() -> None:
    report = check_options(_options(odoo_url=f"admin:{SECRET}@erp.example.com"))
    assert "Odoo URL: set, not shown (no scheme and host could be read)" in report.lines


def test_plain_http_is_fine_on_this_computer_only() -> None:
    local = check_options(_options(odoo_url="http://localhost:8069"))
    remote = check_options(_options(odoo_url="http://erp.example.com"))
    assert local.warnings == [] and "unencrypted" in remote.warnings[0]


def test_a_sensitive_value_is_never_printed_whatever_the_input_holds() -> None:
    doc = _options(odoo_api_key=SECRET, odoo_password=SECRET,
                   configured=("odoo_url", "odoo_db", "odoo_login", "odoo_api_key",
                               "odoo_password"))
    for as_json in (False, True):
        code, text = _run("options", doc, as_json=as_json)
        assert code == 0 and SECRET not in text
    assert "the API key is used" in _run("options", doc)[1]


# ---------------------------------------------------------------- input and CLI


@pytest.mark.parametrize(("kind", "payload", "fragment"), [
    ("copies", "", "nothing was piped in"),
    ("copies", "not json", "is not JSON"),
    ("copies", {"pluginId": "x"}, "claude plugin list --json"),
    ("options", [], "claude plugin configure <id> --json"),
    ("options", _options("odoo-tools-premium@synced"), "odoo-tools copy"),
])
def test_input_that_is_not_the_expected_json_exits_2(kind: str, payload: Any,
                                                     fragment: str) -> None:
    code, text = _run(kind, payload)
    assert code == 2 and fragment in text


@pytest.mark.parametrize("configured", [[["odoo_url"]], True, 5, {"odoo_url": 1}])
def test_odd_values_inside_valid_json_exit_2(configured: Any) -> None:
    code, text = _run("options", dict(_options(), configured=configured))
    assert code == 2 and "Traceback" not in text


def test_odd_note_details_do_not_stop_the_copies_check() -> None:
    code, _text = _run("copies", [dict(WINDOWS_LIST[1], noteDetails=5)])
    assert code == 0


def test_the_checks_read_utf8_whatever_the_code_page() -> None:
    # Claude Code prints UTF-8; Python on Windows reads a pipe as cp1252, where the
    # second byte of an accented capital (0x81) does not decode. PYTHONIOENCODING
    # plays that here, with and without a BOM.
    entries = [dict(WINDOWS_LIST[0], projectPath="/srv/Ángel/odoo"), WINDOWS_LIST[1]]
    payload = json.dumps(entries, ensure_ascii=False).encode("utf-8")
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    for prefix in (b"", b"\xef\xbb\xbf"):
        done = subprocess.run([sys.executable, str(RUN_STDIO), "--check-copies"],
                              input=prefix + payload, capture_output=True, env=env,
                              timeout=60, check=False)
        assert done.returncode == 1, done.stderr.decode("utf-8", "replace")
        assert 'cd "/srv/Ángel/odoo"' in done.stdout.decode("utf-8")


def test_the_json_report_is_machine_readable() -> None:
    code, text = _run("copies", WINDOWS_LIST, as_json=True)
    body = json.loads(text)
    assert code == 1 and body["ok"] is False and body["keep"] == "odoo-tools@transgenia-odoo-tools"
    assert [c["state"] for c in body["copies"]] == ["active", "active", "shadowed"]


def test_the_cli_flags(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(WINDOWS_LIST)))
    assert main(["--check-copies"]) == 1
    assert "claude plugin uninstall" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_options())))
    assert main(["--check-options", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    with pytest.raises(SystemExit):
        main(["--check-copies", "--diagnose"])
