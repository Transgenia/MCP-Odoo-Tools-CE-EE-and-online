# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""hooks/check_options.py: the SessionStart notice for missing connection options.

The hook runs as Claude Code runs it: a subprocess with the event JSON on stdin and the
saved plugin options as CLAUDE_PLUGIN_OPTION_* variables (absent when not saved).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "check_options.py"
CONFIGURED = {
    "ODOO_URL": "https://odoo.invalid",
    "ODOO_DB": "demo",
    "ODOO_LOGIN": "user@example.com",
    "ODOO_API_KEY": "dummy-key-not-real",
}


def _run(tmp_path: Path, options: dict[str, str], source: Any = "startup",
         stdin: str | None = None) -> tuple[int, str]:
    home = tmp_path / "home"
    data = tmp_path / "data"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "CLAUDE_PLUGIN_ROOT": str(ROOT),
        "CLAUDE_PLUGIN_DATA": str(data),
    }
    env.update({"CLAUDE_PLUGIN_OPTION_" + key: value for key, value in options.items()})
    if stdin is None:
        stdin = json.dumps({"hook_event_name": "SessionStart", "source": source})
    result = subprocess.run([sys.executable, str(HOOK)], input=stdin, env=env,
                            capture_output=True, text=True, timeout=30, check=False)
    return result.returncode, result.stdout


def test_silent_when_the_options_are_set(tmp_path: Path) -> None:
    assert _run(tmp_path, CONFIGURED) == (0, "")


def test_a_password_counts_as_the_credential(tmp_path: Path) -> None:
    options = {k: v for k, v in CONFIGURED.items() if k != "ODOO_API_KEY"}
    options["ODOO_PASSWORD"] = "dummy-password"
    assert _run(tmp_path, options) == (0, "")


def test_missing_options_tell_the_user_and_claude(tmp_path: Path) -> None:
    code, out = _run(tmp_path, {})
    assert code == 0
    payload = json.loads(out)
    for key in ("odoo_url", "odoo_db", "odoo_login", "odoo_api_key or odoo_password"):
        assert key in payload["systemMessage"]
        assert key in payload["hookSpecificOutput"]["additionalContext"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Configure options" in payload["systemMessage"]
    assert len(payload["systemMessage"]) < 10_000  # Claude Code's cap per field


def test_only_the_missing_options_are_listed(tmp_path: Path) -> None:
    options = {k: v for k, v in CONFIGURED.items() if k != "ODOO_DB"}
    payload = json.loads(_run(tmp_path, options)[1])
    assert "odoo_db" in payload["systemMessage"]
    assert "odoo_url" not in payload["systemMessage"]
    assert "odoo_api_key or odoo_password" not in payload["systemMessage"]


def test_never_prints_an_option_value(tmp_path: Path) -> None:
    options = {"ODOO_URL": "https://secret-host.invalid", "ODOO_LOGIN": "who@secret.invalid",
               "ODOO_API_KEY": "sk-SHOULD-NEVER-APPEAR"}
    code, out = _run(tmp_path, options)  # odoo_db is missing, so the hook speaks
    assert code == 0 and out
    for value in options.values():
        assert value not in out


def test_unresolved_placeholders_count_as_unset(tmp_path: Path) -> None:
    options = dict(CONFIGURED, ODOO_URL="${user_config.odoo_url}")
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


@pytest.mark.parametrize("source", ["resume", "clear", "compact", "fork"])
def test_only_a_new_session_shows_the_user_notice(tmp_path: Path, source: str) -> None:
    payload = json.loads(_run(tmp_path, {}, source=source)[1])
    assert "systemMessage" not in payload
    assert "odoo_url" in payload["hookSpecificOutput"]["additionalContext"]
    assert not (tmp_path / "data" / "options-notice").exists()  # the daily slot is kept


def test_container_mode_is_left_alone(tmp_path: Path) -> None:
    env_file = tmp_path / "home" / ".odoo-tools" / "mcp" / "odoo.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("ODOO_URL=https://odoo.invalid\n")
    assert _run(tmp_path, {}) == (0, "")


def test_unreadable_event_still_gives_the_notice(tmp_path: Path) -> None:
    code, out = _run(tmp_path, {}, stdin="not json")
    assert code == 0
    assert "systemMessage" in json.loads(out)


def test_unwritable_data_folder_does_not_break_the_hook(tmp_path: Path) -> None:
    (tmp_path / "data").write_text("a file where the folder should be")
    code, out = _run(tmp_path, {})
    assert code == 0
    assert "systemMessage" in json.loads(out)


def test_hooks_json_runs_it_in_exec_form() -> None:
    config = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    hooks = [h for group in config["hooks"]["SessionStart"] for h in group["hooks"]]
    check = [h for h in hooks if any("check_options.py" in a for a in h.get("args", []))]
    assert len(check) == 1
    assert check[0]["command"] == "python3"
    assert check[0]["args"] == ["${CLAUDE_PLUGIN_ROOT}/hooks/check_options.py"]
    # Claude Code rejects ${user_config.*} in a shell-form hook (no args).
    for hook in hooks:
        if "args" not in hook:
            assert "${user_config." not in hook["command"]
