# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The code-free directory edition (distribution/directory).

The directory scans only the folder given as the plugin path (Anthropic's submission
guide), so the edition is a folder of this repository that holds nothing the review
portal restricts: Markdown, JSON and one PNG, with no hook, no server and no option.
These tests keep it that way and keep it honest on every surface (product rules 2, 3
and 5). They say nothing about whether the directory accepts it: only Anthropic decides.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
EDITION = ROOT / "distribution" / "directory"
SCOPE = ("This edition of Odoo Tools contains no code and has no connection to Odoo. It adds "
         "no tool for Claude to read or change your Odoo, in any app. It does give Claude "
         "reference knowledge about Odoo 10 to 19 (what changed between versions) and tells you how to "
         "get help connecting Claude to your Odoo. Nothing is wrong with your Claude account, "
         "your Odoo or your computer.")
TEXT_FILES = ("README.md", "skills/odoo-start-here/SKILL.md", "commands/odoo-help.md")
REPO_BLOB = "https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/blob/main/"


def _preflight() -> Any:
    spec = importlib.util.spec_from_file_location("directory_preflight",
                                                  ROOT / "scripts" / "directory_preflight.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["directory_preflight"] = module
    spec.loader.exec_module(module)
    return module


def _text(rel: str) -> str:
    return (EDITION / rel).read_text(encoding="utf-8")


def _manifest() -> dict[str, Any]:
    return json.loads(_text(".claude-plugin/plugin.json"))


def _files() -> list[str]:
    return sorted(p.relative_to(EDITION).as_posix() for p in EDITION.rglob("*") if p.is_file())


def test_the_edition_passes_the_preflight_with_no_errors_and_no_warnings() -> None:
    report = _preflight().run(EDITION)
    problems = [f for f in report["findings"] if f["severity"] != "info"]
    assert not problems, problems


def test_the_edition_holds_only_markdown_json_and_one_png() -> None:
    suffixes = {Path(name).suffix for name in _files() if Path(name).name != "LICENSE"}
    assert suffixes == {".md", ".json", ".png"}
    assert len(_files()) <= 20


def test_the_edition_has_no_hook_server_option_or_script() -> None:
    manifest = _manifest()
    for key in ("hooks", "mcpServers", "lspServers", "userConfig", "workflows", "channels",
                "dependencies", "settings"):
        assert key not in manifest, key
    assert not (EDITION / "hooks").exists() and not (EDITION / ".mcp.json").exists()
    for name in _files():
        data = (EDITION / name).read_bytes()
        assert not data.startswith(b"#!"), name
        if not name.endswith(".png"):
            assert b"\x00" not in data and data.decode("utf-8"), name


def test_the_edition_does_not_use_the_name_of_the_full_plugin() -> None:
    # The directory lists a plugin per folder, and a folder that is not the root is a new
    # submission. A name of its own also keeps the live odoo-tools listing untouched and
    # keeps the doctor of the full plugin from treating this one as a second copy.
    full = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    manifest = _manifest()
    assert manifest["name"] != full["name"] == "odoo-tools"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", manifest["name"])
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])


def test_the_license_is_the_same_as_the_full_plugins() -> None:
    assert _text("LICENSE") == (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert _manifest()["license"] == "MIT"


@pytest.mark.parametrize("rel", TEXT_FILES)
def test_every_surface_says_what_this_edition_is(rel: str) -> None:
    # Product rule 2: where the tools cannot run, say so in plain words the first time it
    # matters. This edition has no tools anywhere, so the same words stand in the README,
    # the entry skill and the command, and the plugin description says it too.
    text = re.sub(r"\s+", " ", _text(rel))
    assert SCOPE in text, rel
    assert "has no code and cannot connect to your Odoo" in _manifest()["description"]


def test_the_ways_forward_lead_to_transgenia_through_official_channels_only() -> None:
    # Product rule 3, item 2. Items 1 and 3 of the rule are not met as written (a synced
    # copy of this edition has no tools, and no hosted server exists yet): the product
    # owner decides, see docs/directory-channel.md.
    allowed_mail = {"dev@transgenia.org"}
    for rel in (*TEXT_FILES, "SUPPORT.md", "PRIVACY.md"):
        text = _text(rel)
        assert set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)) <= allowed_mail, rel
    for rel in ("README.md", "skills/odoo-start-here/SKILL.md", "commands/odoo-help.md",
                "SUPPORT.md"):
        text = _text(rel)
        assert "dev@transgenia.org" in text and "+52 55 8034 0405" in text, rel
        assert "https://wa.me/525580340405" in text, rel
        assert not re.search(r"\+\d[\d ()-]{8,}", text.replace("+52 55 8034 0405", "")), rel


def test_credentials_never_travel_through_a_conversation() -> None:
    # Product rule 5.
    skill = re.sub(r"\s+", " ", _text("skills/odoo-start-here/SKILL.md"))
    assert "Never ask for, accept or repeat an Odoo API key or password" in skill
    command = re.sub(r"\s+", " ", _text("commands/odoo-help.md"))
    assert "Never paste an Odoo API key or password" in command
    assert "Do not send API keys, passwords, private URLs or customer data" in _text("SUPPORT.md")


def test_the_edition_tells_claude_to_run_and_fetch_nothing() -> None:
    skill = re.sub(r"\s+", " ", _text("skills/odoo-start-here/SKILL.md"))
    assert "Do not run shell commands" in skill
    assert "Do not fetch web pages to obtain instructions" in skill
    assert "without running any command and without fetching anything" in _text(
        "commands/odoo-help.md")


def test_the_edition_claims_no_tool_or_command_of_the_full_plugin() -> None:
    for rel in _files():
        if rel.endswith((".md", ".json")):
            text = _text(rel)
            assert not re.search(r"\bodoo_[a-z_]+\b", text), rel  # no odoo_* tool names
            assert "/odoo-tools:" not in text and "odoo-doctor" not in text, rel
            assert "${CLAUDE_PLUGIN" not in text and "userConfig" not in text, rel


def test_the_edition_does_not_give_an_install_command_for_another_plugin() -> None:
    # A pointer for the user to the manual is fine. An install command for a plugin the
    # directory did not review could read as steering around its rules.
    for rel in TEXT_FILES:
        text = _text(rel)
        assert "/plugin install" not in text and "claude plugin install" not in text, rel
        assert "marketplace add" not in text, rel


def test_the_listing_links_point_at_files_that_exist_in_this_repository() -> None:
    manifest = _manifest()
    for key in ("supportUrl", "privacyPolicyUrl", "termsOfServiceUrl"):
        url = manifest[key]
        assert url.startswith(REPO_BLOB), key
        assert (ROOT / url[len(REPO_BLOB):]).is_file(), key
    for key in ("documentationUrl", "homepage", "repository"):
        assert manifest[key].startswith("https://"), key
    assert (EDITION / manifest["icon"]).is_file()


def test_the_icon_is_a_png_of_512_pixels() -> None:
    data = (EDITION / ".claude-plugin" / "icon.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(data[16:20], "big") == 512 and int.from_bytes(data[20:24], "big") == 512
    assert len(data) < 256 * 1024


def _tracked() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                             check=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("not a git checkout")
    return [name for name in out.decode("utf-8").split("\0") if name]


def test_the_edition_is_versioned_with_the_repository() -> None:
    # The folder a submission points at is what git holds, with no build step between.
    tracked = set(_tracked())
    for name in _files():
        assert f"distribution/directory/{name}" in tracked, name


def test_the_full_local_plugin_still_fails_the_three_portal_rules() -> None:
    # Calibration: Anthropic's check refused v1.6.1 for these three rules. The preflight
    # reproduces them for the repository root, which is why the full plugin cannot be the
    # plugin path of a submission and the edition is a folder of its own.
    _tracked()  # skips outside a git checkout
    report = _preflight().run(ROOT, tracked=True)
    errors = {f["code"] for f in report["findings"] if f["severity"] == "error"}
    assert {"LOCAL_CODE_HOOK_COMMAND", "LOCAL_CODE_MCP_SERVER",
            "LOCAL_CODE_FILE_TYPE"} <= errors
