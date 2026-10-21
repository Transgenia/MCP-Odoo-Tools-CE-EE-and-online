# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The docs must say what each Claude surface does with this plugin's MCP server.

Anthropic's plugin support matrix (https://claude.com/docs/plugins/platform-support)
says Cowork ignores an MCP server that references ``${user_config.*}`` options without
a default ("Cowork doesn't prompt for values") and that chat ignores a plugin's local
MCP server. v1.4.0 documented the server as working in a local Cowork session: a user who
installed the plugin there found "odoo - Runs in each session" with an empty panel and
no form for the connection options.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
_REFERENCE = re.compile(r"\$\{user_config\.([A-Za-z0-9_]+)\}")


def _manifest() -> dict[str, Any]:
    return json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))


def _referenced_options() -> set[str]:
    refs: set[str] = set()
    for server in _manifest().get("mcpServers", {}).values():
        refs.update(_REFERENCE.findall(json.dumps(server)))
    return refs


def test_every_referenced_option_is_declared() -> None:
    # A reference to an undeclared option makes the host drop the server.
    assert _referenced_options() <= set(_manifest()["userConfig"])


def _where_it_works() -> dict[str, list[str]]:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Where it works", 1)[1].split("\n## ", 1)[0]
    rows: dict[str, list[str]] = {}
    for line in section.splitlines():
        if line.startswith("|") and not set(line) <= set("|- "):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            rows[cells[0]] = cells[1:]
    return rows


def test_readme_does_not_promise_the_odoo_tools_where_options_cannot_be_entered() -> None:
    options = _manifest()["userConfig"]
    without_default = [key for key in _referenced_options() if "default" not in options[key]]
    # Cowork ignores the server only while a referenced option has no default. If every
    # option gets one the server may load there: re-check Anthropic's matrix and README.
    assert without_default, "revisit this test and the README section 'Where it works'"
    rows = _where_it_works()
    for surface, cells in rows.items():
        if surface.startswith(("Cowork", "Claude chat")):
            assert cells[0].strip("*").startswith("No"), surface
    assert any(
        surface.startswith("Claude Code") and cells[0].strip("*").startswith("Yes")
        for surface, cells in rows.items()
    )


def test_guided_route_checks_the_surface_before_python() -> None:
    skill = (ROOT / "skills/odoo-setup-mcp/SKILL.md").read_text(encoding="utf-8")
    frontmatter = skill.split("---", 2)[1]
    assert "Runs in each session" in frontmatter  # findable by the symptom users report
    triage = skill.index("Are the Odoo tools loaded on this surface?")
    assert triage < skill.index("### Step 1A")
    # Phase 0 sends a surface without the tools to Phase 0b before any shell probe:
    # Claude chat has no shell.
    phase0 = skill.split("## Phase 0 ", 1)[1].split("## Phase 0b", 1)[0]
    assert "Phase 0b" in phase0 and phase0.index("Phase 0b") < phase0.index("```bash")
    assert "claude plugin configure" in skill and "Cowork" in skill
