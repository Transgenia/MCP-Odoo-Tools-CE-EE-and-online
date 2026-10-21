# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""hooks/check_options.py: the SessionStart notice for missing connection options.

The hook runs as Claude Code runs it: a subprocess with the event JSON on stdin (UTF-8
bytes) and the saved plugin options as CLAUDE_PLUGIN_OPTION_* variables (absent when
not saved).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "check_options.py"
REQUIRED_SET = {
    "ODOO_URL": "https://odoo.invalid",
    "ODOO_DB": "demo",
    "ODOO_LOGIN": "user@example.com",
}
POSIX_ONLY = pytest.mark.skipif(os.name == "nt" or shutil.which("sh") is None,
                                reason="runs the hooks.json shell command with sh")


def _env(tmp_path: Path, options: dict[str, str], **extra: str) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "CLAUDE_PLUGIN_ROOT": str(ROOT),
        "CLAUDE_PLUGIN_DATA": str(tmp_path / "data"),
    }
    env.update({"CLAUDE_PLUGIN_OPTION_" + key: value for key, value in options.items()})
    env.update(extra)
    return env


def _event(source: Any = "startup", cwd: str = "/tmp/project") -> bytes:
    payload = {"hook_event_name": "SessionStart", "source": source, "cwd": cwd}
    # Claude Code writes UTF-8 without escaping non-ASCII characters.
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _run_full(tmp_path: Path, options: dict[str, str], source: Any = "startup",
              stdin: bytes | None = None, **extra: str) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, str(HOOK)], input=_event(source) if stdin is None else stdin,
        env=_env(tmp_path, options, **extra), capture_output=True, timeout=30, check=False,
    )
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


def _run(tmp_path: Path, options: dict[str, str], source: Any = "startup",
         stdin: bytes | None = None, **extra: str) -> tuple[int, str]:
    code, out, _ = _run_full(tmp_path, options, source, stdin, **extra)
    return code, out


def test_silent_when_the_required_options_are_set(tmp_path: Path) -> None:
    # The credential is not checked: the server and the guided route report it.
    assert _run(tmp_path, REQUIRED_SET) == (0, "")


def test_never_reads_the_credential_options() -> None:
    # v1.2.0 directory finding: a SessionStart hook must not read the API key option.
    source = HOOK.read_text(encoding="utf-8")
    assert "odoo_api_key" not in source.lower() and "odoo_password" not in source.lower()
    assert "API_KEY" not in source and "PASSWORD" not in source


def test_missing_options_tell_the_user_and_claude(tmp_path: Path) -> None:
    code, out = _run(tmp_path, {})
    assert code == 0
    payload = json.loads(out)
    for key in ("odoo_url", "odoo_db", "odoo_login"):
        assert key in payload["systemMessage"]
        assert key in payload["hookSpecificOutput"]["additionalContext"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Configure options" in payload["systemMessage"]
    assert "remote connector" in payload["systemMessage"]
    for text in (payload["systemMessage"], payload["hookSpecificOutput"]["additionalContext"]):
        assert len(text) < 10_000  # Claude Code's cap per field


def test_only_the_missing_options_are_listed(tmp_path: Path) -> None:
    options = {k: v for k, v in REQUIRED_SET.items() if k != "ODOO_DB"}
    payload = json.loads(_run(tmp_path, options)[1])
    assert "odoo_db" in payload["systemMessage"]
    assert "odoo_url" not in payload["systemMessage"]


def test_never_prints_or_stores_an_option_value(tmp_path: Path) -> None:
    options = {"ODOO_URL": "https://secret-host.invalid", "ODOO_LOGIN": "who@secret.invalid",
               "ODOO_API_KEY": "sk-CANARY-SHOULD-NEVER-APPEAR",
               "ODOO_PASSWORD": "pw-CANARY-SHOULD-NEVER-APPEAR"}
    code, out, err = _run_full(tmp_path, options)  # odoo_db is missing, so the hook speaks
    assert code == 0 and out
    for value in options.values():
        assert value not in out and value not in err
    assert (tmp_path / "data" / "options-notice").read_bytes() == b""  # a timestamp only


# Runs the hook with os.environ replaced by a mapping that records every key looked up
# and every bulk read (iteration, items, copy...), then writes that record to a file.
_ENV_SPY = r"""
import json, os, runpy, sys
seen, bulk = [], []
def note(key):
    seen.append(key.decode("latin-1") if isinstance(key, bytes) else key)
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
        bulk.append(_n); return _f(self, *a)
    setattr(Spy, name, bulk_read)
os.environ = Spy(os.environ)
if hasattr(os, "environb"):
    os.environb = Spy(os.environb)
try:
    runpy.run_path(sys.argv[1], run_name="__main__")
except SystemExit:
    pass
with open(sys.argv[2], "w") as fh:
    json.dump({"seen": seen, "bulk": bulk}, fh)
"""


# Every variable the hook may look up: the three connection options, the two policy
# options (1.5.0), the plugin data folder and what Path.home() reads.
READABLE = {"CLAUDE_PLUGIN_OPTION_ODOO_URL", "CLAUDE_PLUGIN_OPTION_ODOO_DB",
            "CLAUDE_PLUGIN_OPTION_ODOO_LOGIN", "CLAUDE_PLUGIN_OPTION_ODOO_POLICY",
            "CLAUDE_PLUGIN_OPTION_ODOO_POLICY_FILE", "CLAUDE_PLUGIN_DATA", "HOME",
            "USERPROFILE", "HOMEDRIVE", "HOMEPATH"}


@pytest.mark.parametrize(("source", "configured", "container", "policy"), [
    ("startup", False, False, None), ("resume", False, False, None),
    ("startup", False, True, None), ("startup", True, False, None),
    ("startup", True, False, "valid"), ("startup", True, False, "broken"),
    ("resume", False, False, "broken"),
])
def test_never_reads_a_credential_variable(tmp_path: Path, source: str, configured: bool,
                                           container: bool, policy: str | None) -> None:
    # The v1.2.0 directory rule, checked by behaviour on every branch of the hook: it may
    # look up only the variables it needs, by name, and never scan the environment. The
    # policy check (1.5.0) imports the server's loader, which must not read any either.
    report = tmp_path / "env-access.json"
    options = dict(REQUIRED_SET if configured else {"ODOO_URL": "https://odoo.invalid"})
    options.update({"ODOO_API_KEY": "sk-CANARY", "ODOO_PASSWORD": "pw-CANARY"})
    if policy is not None:
        options.update(_policy_options(tmp_path, VALID_FILE if policy == "valid" else BAD_FILE))
    env = _env(tmp_path, options)
    if container:
        env_file = tmp_path / "home" / ".odoo-tools" / "mcp" / "odoo.env"
        env_file.parent.mkdir(parents=True)
        env_file.write_text("ODOO_URL=<https://your-odoo>\n")
    subprocess.run([sys.executable, "-c", _ENV_SPY, str(HOOK), str(report)],
                   input=_event(source), env=env, capture_output=True, timeout=30, check=True)
    access = json.loads(report.read_text(encoding="utf-8"))
    assert access["bulk"] == []
    assert any(key.endswith("ODOO_URL") for key in access["seen"])  # the spy works
    for key in access["seen"]:
        assert "API_KEY" not in key.upper() and "PASSWORD" not in key.upper(), key
    assert set(access["seen"]) <= READABLE
    if policy is not None:
        assert "CLAUDE_PLUGIN_OPTION_ODOO_POLICY_FILE" in access["seen"]


# --- the permission policy check (1.5.0) ----------------------------------------------

VALID_FILE = '{"version": 1, "models": {"*": {"call": false}}}'
BAD_FILE = '{"version": 1, "modelz": {}}'


def _policy_options(tmp_path: Path, content: str | None = None,
                    profile: str | None = None) -> dict[str, str]:
    options: dict[str, str] = {}
    if content is not None:
        path = tmp_path / "policy.json"
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
        options["ODOO_POLICY_FILE"] = str(path)
    if profile is not None:
        options["ODOO_POLICY"] = profile
    return options


def test_a_valid_policy_is_silent(tmp_path: Path) -> None:
    options = dict(REQUIRED_SET, **_policy_options(tmp_path, VALID_FILE, profile=" Builder "))
    assert _run(tmp_path, options) == (0, "")
    assert not (tmp_path / "data" / "policy-notice").exists()


def test_a_broken_policy_file_tells_the_user_and_claude(tmp_path: Path) -> None:
    options = dict(REQUIRED_SET, **_policy_options(tmp_path, BAD_FILE))
    code, out, err = _run_full(tmp_path, options)
    assert code == 0 and err == ""
    payload = json.loads(out)
    message = payload["systemMessage"]
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert message.startswith("odoo-tools: the permission policy file has an error, so the "
                              "Odoo tools are locked: policy file ")
    assert "unknown key 'modelz' at the top level" in message and "(E8)" in message
    assert "E8" in context and "only odoo_version works" in context
    assert "never edit the policy file" in context
    assert "odoo_url" not in message  # the connection options are set


def test_an_unknown_profile_is_reported(tmp_path: Path) -> None:
    options = dict(REQUIRED_SET, **_policy_options(tmp_path, profile="readonyl"))
    payload = json.loads(_run(tmp_path, options)[1])
    assert payload["systemMessage"].startswith(
        "odoo-tools: the permission profile is not valid, so the Odoo tools are locked: "
        "unknown permission profile 'readonyl'")


def test_a_relative_policy_path_is_reported(tmp_path: Path) -> None:
    options = dict(REQUIRED_SET, ODOO_POLICY_FILE="policy.json")
    payload = json.loads(_run(tmp_path, options)[1])
    assert "the policy file path must be absolute" in payload["systemMessage"]


def test_the_policy_notice_is_shown_once_a_day_and_only_on_startup(tmp_path: Path) -> None:
    options = dict(REQUIRED_SET, **_policy_options(tmp_path, BAD_FILE))
    first = json.loads(_run(tmp_path, options)[1])
    second = json.loads(_run(tmp_path, options)[1])
    resumed = json.loads(_run(tmp_path, options, source="resume")[1])
    assert "systemMessage" in first and "systemMessage" not in second
    for payload in (second, resumed):
        assert "E8" in payload["hookSpecificOutput"]["additionalContext"]  # Claude knows
    assert "systemMessage" not in resumed


def test_both_notices_together(tmp_path: Path) -> None:
    options = _policy_options(tmp_path, BAD_FILE)  # no connection options either
    payload = json.loads(_run(tmp_path, options)[1])
    message = payload["systemMessage"]
    assert "odoo_url" in message and "(E8)" in message
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "odoo_url" in context and "E8" in context


def test_an_unresolved_policy_option_counts_as_unset(tmp_path: Path) -> None:
    options = dict(REQUIRED_SET, ODOO_POLICY="${user_config.odoo_policy}",
                   ODOO_POLICY_FILE="${user_config.odoo_policy_file}")
    assert _run(tmp_path, options) == (0, "")


def test_unresolved_placeholders_count_as_unset(tmp_path: Path) -> None:
    options = dict(REQUIRED_SET, ODOO_URL="${user_config.odoo_url}")
    payload = json.loads(_run(tmp_path, options)[1])
    assert "odoo_url" in payload["systemMessage"]


def test_the_user_notice_is_shown_once_a_day(tmp_path: Path) -> None:
    first = json.loads(_run(tmp_path, {})[1])
    second = json.loads(_run(tmp_path, {})[1])
    assert "systemMessage" in first
    assert "systemMessage" not in second
    assert "additionalContext" in second["hookSpecificOutput"]  # Claude still knows
    marker = tmp_path / "data" / "options-notice"
    old = marker.stat().st_mtime - 25 * 3600
    os.utime(marker, (old, old))
    assert "systemMessage" in json.loads(_run(tmp_path, {})[1])


def test_a_marker_from_the_future_does_not_silence_the_notice(tmp_path: Path) -> None:
    _run(tmp_path, {})
    marker = tmp_path / "data" / "options-notice"
    future = marker.stat().st_mtime + 10 * 24 * 3600  # clock set back, restored backup
    os.utime(marker, (future, future))
    assert "systemMessage" in json.loads(_run(tmp_path, {})[1])


@pytest.mark.parametrize("source", ["resume", "clear", "compact", "fork"])
def test_only_a_new_session_shows_the_user_notice(tmp_path: Path, source: str) -> None:
    payload = json.loads(_run(tmp_path, {}, source=source)[1])
    assert "systemMessage" not in payload
    assert "odoo_url" in payload["hookSpecificOutput"]["additionalContext"]
    assert not (tmp_path / "data" / "options-notice").exists()  # the daily slot is kept


def test_a_non_ascii_cwd_survives_a_windows_code_page(tmp_path: Path) -> None:
    # Windows pipes decode text with the ANSI code page; the hook must read UTF-8 bytes.
    stdin = _event("resume", cwd="C:\\Users\\Ángel\\LOGÍSTICA\\odoo")
    code, out = _run(tmp_path, {}, stdin=stdin, PYTHONIOENCODING="cp1252")
    assert code == 0
    assert "systemMessage" not in json.loads(out)
    assert not (tmp_path / "data" / "options-notice").exists()


def test_container_mode_tells_only_claude(tmp_path: Path) -> None:
    env_file = tmp_path / "home" / ".odoo-tools" / "mcp" / "odoo.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("ODOO_URL=<https://your-odoo>\n")
    payload = json.loads(_run(tmp_path, {})[1])
    assert "systemMessage" not in payload
    assert "odoo-tools-docker" in payload["hookSpecificOutput"]["additionalContext"]
    assert not (tmp_path / "data" / "options-notice").exists()
    assert _run(tmp_path, REQUIRED_SET) == (0, "")  # configured: silent as usual


def test_unreadable_event_still_gives_the_notice(tmp_path: Path) -> None:
    code, out = _run(tmp_path, {}, stdin=b"not json")
    assert code == 0
    assert "systemMessage" in json.loads(out)


def test_unwritable_data_folder_does_not_break_the_hook(tmp_path: Path) -> None:
    (tmp_path / "data").write_text("a file where the folder should be")
    code, out = _run(tmp_path, {})
    assert code == 0
    assert "systemMessage" in json.loads(out)


def _hook_command() -> str:
    config = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    hooks = [h for group in config["hooks"]["SessionStart"] for h in group["hooks"]]
    for hook in hooks:  # Claude Code rejects ${user_config.*} in a shell-form hook
        assert "${user_config." not in hook.get("command", "")
    found = [h for h in hooks if "check_options.py" in h.get("command", "")]
    assert len(found) == 1 and "args" not in found[0]
    return found[0]["command"]


def test_hooks_json_guards_the_python_version() -> None:
    command = _hook_command()
    assert "sys.version_info < (3, 9)" in command
    assert '"${CLAUDE_PLUGIN_ROOT}/hooks/check_options.py"' in command  # quoted path


def _shell(command: str, tmp_path: Path, path: str,
           source: str = "startup") -> tuple[int, str, str]:
    env = _env(tmp_path, {}, PATH=path)
    sh = shutil.which("sh")  # resolved here: the child's PATH is the one under test
    assert sh
    result = subprocess.run([sh, "-c", command.replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT))],
                            input=_event(source), env=env, capture_output=True, timeout=30,
                            check=False)
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


@POSIX_ONLY
def test_without_python3_the_hook_command_is_quiet(tmp_path: Path) -> None:
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    assert _shell(_hook_command(), tmp_path, str(empty)) == (0, "", "")


@POSIX_ONLY
def test_an_old_python3_is_skipped_quietly(tmp_path: Path) -> None:
    fake = tmp_path / "old-bin"
    fake.mkdir()
    (fake / "python3").write_text("#!/bin/sh\nexit 1\n")  # what 3.8 answers to the guard
    (fake / "python3").chmod(0o755)
    assert _shell(_hook_command(), tmp_path, str(fake)) == (0, "", "")


@POSIX_ONLY
def test_a_supported_python3_runs_the_check(tmp_path: Path) -> None:
    real = tmp_path / "py-bin"
    real.mkdir()
    (real / "python3").symlink_to(sys.executable)
    code, out, err = _shell(_hook_command(), tmp_path, str(real))
    assert code == 0 and err == ""
    assert "odoo_url" in json.loads(out)["systemMessage"]


@POSIX_ONLY
def test_the_event_reaches_the_check_past_the_version_guard(tmp_path: Path) -> None:
    # If the guard consumed stdin, a resume would look like a new session and notify.
    real = tmp_path / "py-bin"
    real.mkdir()
    (real / "python3").symlink_to(sys.executable)
    code, out, err = _shell(_hook_command(), tmp_path, str(real), source="resume")
    payload = json.loads(out)
    assert code == 0 and err == ""
    assert "systemMessage" not in payload
    assert "odoo_url" in payload["hookSpecificOutput"]["additionalContext"]
    assert not (tmp_path / "data" / "options-notice").exists()
