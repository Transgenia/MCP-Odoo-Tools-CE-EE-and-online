# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Install commands say where they go: inside Claude Code or in a terminal (1.6.0).

In a Windows onboarding on 2026-10-29, `/plugin install` was typed in PowerShell
("not recognized") and `claude.exe /plugin configure ...` started a session that
saved nothing. A `/plugin` command belongs inside Claude Code; `claude plugin` is
the terminal command. These tests keep every guide in the repository on that line.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TERMINAL_LANGUAGES = {"bash", "sh", "shell", "console", "powershell", "ps1", "pwsh",
                      "cmd", "bat", "zsh"}
# A Claude Code slash command at the start of a line, possibly behind `claude`.
SLASH_COMMAND = re.compile(r"^\s*(?:claude(?:\.exe)?\s+)?/(?:plugin|odoo-tools:|reload-plugins"
                           r"|mcp)\b")
INSIDE = "/plugin install odoo-tools --marketplace Transgenia/MCP-Odoo-Tools-CE-EE-and-online"
TERMINAL = "claude plugin install odoo-tools --marketplace Transgenia/MCP-Odoo-Tools-CE-EE-and-online"


def _guides() -> list[Path]:
    paths = [ROOT / name for name in ("README.md", "SUPPORT.md", "CONTRIBUTING.md",
                                      "PRIVACY.md", "SECURITY.md")]
    for folder in ("docs", "skills", "commands", "agents"):
        paths.extend(sorted((ROOT / folder).rglob("*.md")))
    return [path for path in paths if path.is_file()]


def _blocks(text: str) -> list[tuple[int, str, list[str]]]:
    """(line number, info string, body lines) of every fenced code block."""
    blocks: list[tuple[int, str, list[str]]] = []
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if fence is None:
            match = re.match(r"(`{3,}|~{3,})(.*)$", stripped)
            if match:
                fence = match.group(1)
                blocks.append((number, match.group(2).strip().split(" ")[0], []))
        elif stripped.startswith(fence) and not stripped[len(fence):].strip():
            fence = None
        else:
            blocks[-1][2].append(line)
    return blocks


def test_the_guides_are_found() -> None:
    names = {path.relative_to(ROOT).as_posix() for path in _guides()}
    assert {"README.md", "docs/install.md", "skills/odoo-setup-mcp/SKILL.md",
            "commands/odoo-doctor.md"} <= names


def test_no_terminal_block_holds_a_claude_code_slash_command() -> None:
    found = []
    for path in _guides():
        for number, info, body in _blocks(path.read_text(encoding="utf-8")):
            if info.lower() in TERMINAL_LANGUAGES:
                found.extend(f"{path.relative_to(ROOT)}:{number}: {line.strip()}"
                             for line in body if SLASH_COMMAND.match(line))
    assert not found, found


def test_a_block_of_slash_commands_is_labelled_text() -> None:
    # An unlabelled block reads as a terminal block; `text` says it is typed in a session.
    found = []
    for path in _guides():
        for number, info, body in _blocks(path.read_text(encoding="utf-8")):
            if any(SLASH_COMMAND.match(line) for line in body) and info != "text":
                found.append(f"{path.relative_to(ROOT)}:{number} ({info or 'no label'})")
    assert not found, found


def test_the_install_guides_give_both_forms() -> None:
    for name in ("README.md", "docs/install.md", "skills/odoo-mcp-tools/SKILL.md",
                 "skills/odoo-setup-mcp/SKILL.md"):
        text = " ".join((ROOT / name).read_text(encoding="utf-8").split())
        assert INSIDE in text, name
        assert TERMINAL in text, name


def test_no_guide_sends_the_user_to_a_menu_that_does_not_exist() -> None:
    # "/plugin manage" is in a Claude Code error message, not in its menus.
    found = [str(path.relative_to(ROOT)) for path in _guides()
             if "/plugin manage" in path.read_text(encoding="utf-8")]
    assert not found, found


def test_the_windows_guides_name_the_sign_of_a_missing_python3() -> None:
    # windows-launch.yml, case python-only: without python3.exe, Claude Code 2.1.314 reports
    # the server as "Failed to connect" with "Connection closed", and nothing names Python.
    # The guides quote that message, and the workflow fails if a new pinned Claude Code
    # version changes it.
    sign = "`Failed to connect` with `Connection closed`"
    for name in ("README.md", "docs/install.md", "skills/odoo-setup-mcp/SKILL.md",
                 "commands/odoo-doctor.md"):
        text = " ".join((ROOT / name).read_text(encoding="utf-8").split())
        assert sign in text, name
    workflow = (ROOT / ".github/workflows/windows-launch.yml").read_text(encoding="utf-8")
    assert "-match 'Failed to connect' -and $env:LINE -match 'Connection closed'" in workflow
