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


# Options added after 1.4.1. Each must have a default, so it never adds to the options
# Cowork cannot fill, and the default must be what the server uses when the option is
# unset (config.Settings), so the manifest and the server agree.
NEW_OPTIONS = {"odoo_policy": ("ODOO_POLICY", "standard"),
               "odoo_policy_file": ("ODOO_POLICY_FILE", "")}


def test_every_new_option_has_a_default() -> None:
    from odoo_mcp.config import Settings

    manifest = _manifest()
    options = manifest["userConfig"]
    env = manifest["mcpServers"]["odoo"]["env"]
    defaults = Settings()
    for key, (variable, default) in NEW_OPTIONS.items():
        assert key in options, key
        assert "default" in options[key], key
        assert options[key]["default"] == default, key
        assert options[key]["type"] == "string" and not options[key].get("sensitive"), key
        assert not options[key].get("required"), key
        assert env[variable] == "${user_config." + key + "}"
    assert defaults.policy_profile == NEW_OPTIONS["odoo_policy"][1]
    assert defaults.policy_file == NEW_OPTIONS["odoo_policy_file"][1]
    assert options["odoo_policy"]["title"] == "Permission profile"
    assert options["odoo_policy_file"]["title"] == "Permission policy file (optional)"
    for name in ("readonly", "standard", "builder", "full"):
        assert name in options["odoo_policy"]["description"]
    # The audit folder needs no option: the plugin passes its data folder.
    assert env["ODOO_AUDIT_DIR"] == "${CLAUDE_PLUGIN_DATA}/audit"
    # Every option that has no default predates 1.5.0: the five connection options.
    without_default = {key for key in options if "default" not in options[key]}
    assert without_default == {"odoo_url", "odoo_db", "odoo_login", "odoo_api_key",
                               "odoo_password"}


def test_the_docs_show_the_full_escape() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## Permissions" in readme and "docs/policy.md" in readme
    assert "`full`" in readme.split("## Permissions", 1)[1].split("\n## ", 1)[0]
    release = changelog.split("\n## [1.5.0]", 1)[1].split("\n## [", 1)[0]  # 1.5.0's notes
    assert re.findall(r"^### (.+)$", release, re.MULTILINE)[0] == "Changed (secure defaults)"
    assert "**Permission profile** to `full`" in release


# --- 1.5.1: the tools-missing gate and the listings (the Cowork incident of 2026-10-28)
#
# A Cowork user ran /odoo-doctor: with no Odoo tools loaded, Claude checked Python in
# Cowork's virtual machine (3.13, "Pass") and then sent the user to check their Odoo
# Online plan. Neither could be the cause. Every component that calls the Odoo tools
# now checks first that they loaded.

GATE = "if `odoo_version` is not in your tool list"
_TOOL = re.compile(r"`odoo_[a-z_]+`")
# Exempt, with the reason: the guided route has its own Phase 0 and 0b, the shortcut
# loads it, the doctor's step 0 is the gate itself, and deploy-local and the CLI
# fallback do not need the plugin's MCP tools to start.
_GATE_EXEMPT = {"skills/odoo-setup-mcp/SKILL.md", "commands/setup-odoo-tools.md",
                "commands/odoo-doctor.md", "commands/deploy-local.md",
                "skills/odoo-setup-cli/SKILL.md"}


def _body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text.split("---", 2)[2] if text.startswith("---") else text


def test_every_component_that_calls_the_odoo_tools_checks_they_loaded_first() -> None:
    checked = 0
    for pattern in ("skills/*/SKILL.md", "commands/*.md", "agents/*.md"):
        for path in sorted(ROOT.glob(pattern)):
            rel = path.relative_to(ROOT).as_posix()
            body = _body(path)
            first_tool = _TOOL.search(body)
            if rel in _GATE_EXEMPT or not first_tool:
                continue
            assert GATE in body, rel
            assert body.index(GATE) < first_tool.start(), rel
            checked += 1
    assert checked >= 7


def test_the_doctor_checks_the_surface_before_anything_else() -> None:
    text = (ROOT / "commands/odoo-doctor.md").read_text(encoding="utf-8")
    step0, step1 = text.index("## 0."), text.index("## 1.")
    assert step0 < step1 < text.index("`odoo_version`", step1)
    gate = text[step0:step1]
    for phrase in ("Do not run shell commands", "virtual machine", "Odoo side",
                   "odoo-tools session diagnostics:", "**Code** tab",
                   "dev@transgenia.org", "+52 55 8034 0405"):
        assert phrase in gate, phrase
    # the support report runs the server's --diagnose on the plugin's own folders
    assert ('run_stdio.py" --diagnose --diag-dir "${CLAUDE_PLUGIN_DATA}/diagnostics" '
            '--audit-dir "${CLAUDE_PLUGIN_DATA}/audit"') in text
    assert "Never ask for the API key" in text


_SURFACE_NOTE = "in Cowork and Claude chat the skills and commands load without the tools"


def test_both_listings_say_where_the_tools_run() -> None:
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    # A display field set on the marketplace entry is what users see, even when
    # plugin.json sets another one (Claude Code marketplace reference, "Display
    # fields"): in 1.4.1 the surface note was in plugin.json only, under an entry
    # description that hid it.
    for where, description in (("plugin.json", _manifest()["description"]),
                               ("marketplace entry", market["plugins"][0].get("description", ""))):
        assert _SURFACE_NOTE in description, where
        assert "dev@transgenia.org" in description, where


def test_the_readme_says_where_it_runs_before_the_badges() -> None:
    # The directory shows the README as the listing's description.
    head = (ROOT / "README.md").read_text(encoding="utf-8").split("[![", 1)[0]
    for phrase in ("Where it runs", "Code** tab", "Cowork and Claude chat",
                   "dev@transgenia.org"):
        assert phrase in head, phrase


def test_the_manifests_carry_the_directory_listing_fields() -> None:
    manifest = _manifest()
    for key in ("documentationUrl", "supportUrl", "privacyPolicyUrl", "termsOfServiceUrl"):
        assert manifest[key].startswith("https://"), key
    assert (ROOT / manifest["icon"]).is_file()
    for name in ("plugin.json", "marketplace.json"):
        text = (ROOT / ".claude-plugin" / name).read_text(encoding="utf-8")
        assert "—" not in text and "–" not in text, name


# --- 1.6.0: the Claude app's own words for the Cowork case (a Mac user, 2026-10-30)
#
# Claude Desktop reported this plugin's server with the status "not_started" and the
# reason "user_config_unsupported". On the directory's 1.4.0 Claude called that a fault
# between the plugin and the app, to report as a bug, and the user looked for an update.
# It is the case of Anthropic's matrix, which no version changes. A cloud session of the
# Code tab has the plugin synced but none of its options, so the way out is a local
# session. The hooks never name the reason: no hook file may mention "user_config"
# (test_product_rules.test_hooks_never_read_plugin_options_or_credentials).

_STATUS = "user_config_unsupported"
_STATUS_DOCS = ("commands/odoo-doctor.md", "skills/odoo-setup-mcp/SKILL.md", "README.md",
                "docs/install.md", "SUPPORT.md")


def test_the_apps_status_for_the_cowork_case_is_recognised() -> None:
    for rel in _STATUS_DOCS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert _STATUS in text and "`not_started`" in text, rel
        assert "local session" in text, rel
    doctor = (ROOT / "commands/odoo-doctor.md").read_text(encoding="utf-8")
    step0 = " ".join(doctor[doctor.index("## 0."):doctor.index("## 1.")].split())
    for phrase in (_STATUS, "never present it as a bug to report",
                   "Updating the plugin does not change it", "**A cloud session**",
                   "Do not ask for the options here"):
        assert phrase in step0, phrase
    # the status, as the app showed it, goes in the support report
    assert _STATUS in doctor.split("## 4.", 1)[1]
    # findable by the status the app shows
    assert _STATUS in (ROOT / "skills/odoo-setup-mcp/SKILL.md").read_text(
        encoding="utf-8").split("---", 2)[1]
    assert (ROOT / "evals/cowork-status-report/prompt.md").is_file()


def test_a_cloud_session_is_not_promised_the_odoo_tools() -> None:
    rows = _where_it_works()
    cloud = [cells for surface, cells in rows.items() if "cloud session" in surface]
    assert len(cloud) == 1 and cloud[0][0].strip("*").startswith("No")
    local = [cells for surface, cells in rows.items() if "local session" in surface]
    assert len(local) == 1 and local[0][0].strip("*").startswith("Yes")
    # the hook's notes say "a local session" too: test_session_start_hook.SURFACE
