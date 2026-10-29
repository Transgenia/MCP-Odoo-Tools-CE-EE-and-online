# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The product rules a test can check (docs/product-rules.md).

Rule 1: the plugin installs on every surface Anthropic allows, and nothing in it makes
the directory list it on fewer surfaces or hold every version for a reviewer
(https://claude.com/docs/plugins/platform-support and the plugin pre-submission
checklist, read 2026-10-29). The surface rows of the directory follow the plugin's
components, so a top-level bin/ or a mod would take the plugin out of claude.ai and
Cowork, where most installs come from.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_IMAGES_AND_FONTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".woff", ".woff2",
                     ".ttf", ".otf")
_HELD_BINARIES = (".zip", ".mcpb", ".dxt", ".pdf", ".ico", ".exe", ".dll", ".so", ".dylib",
                  ".whl", ".tar", ".gz", ".jar")


def test_no_top_level_bin_directory() -> None:
    # claude.ai and Cowork refuse to install a plugin that has one.
    assert not (ROOT / "bin").exists()


def test_no_mod_in_the_hooks() -> None:
    # The directory lists a plugin with a mod (hooks.json "modules") for Claude Code only.
    hooks = json.loads((ROOT / "hooks/hooks.json").read_text(encoding="utf-8"))
    assert "modules" not in hooks


def test_hooks_never_read_plugin_options_or_credentials() -> None:
    # Claude Code exports every saved option, the API key included, to hook processes,
    # and the directory holds a plugin that reads a credential from the user's machine
    # ("Uses a credential from the user's machine"). So a hook must not read any of
    # them: what a hook needs comes from the plugin's own diagnostics folder.
    for path in sorted((ROOT / "hooks").iterdir()):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for needle in ("CLAUDE_PLUGIN_OPTION", "user_config", "ODOO_API_KEY",
                           "ODOO_PASSWORD", "odoo.env"):
                assert needle not in text, f"{path.name} mentions {needle}"


def _tracked_files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                             check=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("not a git checkout")
    return [name for name in out.decode("utf-8").split("\0") if name]


def test_the_plugin_folder_stays_within_what_the_directory_inspects() -> None:
    # The pre-submission checklist holds for a reviewer a plugin with more than 512
    # files, a non-image file over 256 KiB, or a binary file such as a .zip or .mcpb.
    files = _tracked_files()
    assert len(files) <= 512
    for name in files:
        lowered = name.lower()
        assert not lowered.endswith(_HELD_BINARIES), name
        path = ROOT / name
        if path.is_file() and not lowered.endswith(_IMAGES_AND_FONTS):
            assert path.stat().st_size <= 256 * 1024, name


def test_the_rules_document_states_the_installation_rule() -> None:
    rules = (ROOT / "docs/product-rules.md").read_text(encoding="utf-8")
    assert "## 1. Installable on every surface" in rules
    assert "never block a surface" in rules
    assert "dev@transgenia.org" in rules and "+52 55 8034 0405" in rules
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "docs/product-rules.md" in contributing


def test_the_rules_document_states_the_manual_rule() -> None:
    # Rule 8 (product owner, 2026-10-29): every change to the plugin is checked against
    # the manual at docs.transgenia.org, which is kept in Spanish, English and Chinese.
    rules = (ROOT / "docs/product-rules.md").read_text(encoding="utf-8")
    assert "## 8. Every change is checked against the manual" in rules
    assert "Spanish, English and Chinese" in rules and "software_version" in rules
    for name in ("CONTRIBUTING.md", "CLAUDE.md", "docs/packaging.md",
                 ".github/pull_request_template.md"):
        assert "docs.transgenia.org" in (ROOT / name).read_text(encoding="utf-8"), name


@pytest.mark.parametrize("name", ["CLAUDE.md", "docs/product-rules.md", "docs/packaging.md",
                                  "PRIVACY.md", ".github/pull_request_template.md"])
def test_public_rule_texts_have_no_dashes(name: str) -> None:
    # Public text uses plain ASCII punctuation: no em dash (U+2014), no en dash (U+2013).
    text = (ROOT / name).read_text(encoding="utf-8")
    assert "\u2014" not in text and "\u2013" not in text, name


_CREDENTIAL_NAME = re.compile(r"KEY|PASSWORD|PASSWD|TOKEN|BEARER|SECRET|CREDENTIAL")
_ENV_READERS = {"_env", "_get_bool", "_get_int", "getenv"}


def _env_names_the_server_reads() -> set[str]:
    """Every environment variable name the server's source reads by literal name."""
    names: set[str] = set()
    for path in sorted((ROOT / "server/src/odoo_mcp").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            target = None
            if isinstance(node, ast.Call) and node.args:
                func = node.func
                called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                environ_get = (isinstance(func, ast.Attribute) and func.attr == "get"
                               and getattr(func.value, "attr", getattr(func.value, "id", ""))
                               == "environ")
                if called in _ENV_READERS or environ_get:
                    target = node.args[0]
            elif (isinstance(node, ast.Subscript)
                  and getattr(node.value, "attr", getattr(node.value, "id", "")) == "environ"):
                target = node.slice
            if isinstance(target, ast.Constant) and isinstance(target.value, str):
                names.add(target.value)
    return names


def test_the_server_reads_only_credentials_that_plugin_json_passes_from_sensitive_options(
) -> None:
    # The directory holds a plugin that reads a credential already set in the user's
    # environment and sends it to a server ("Uses a credential from the user's machine",
    # MCP_FORWARDS_CREDENTIAL_ENV): a credential must come from a sensitive userConfig
    # option. 1.5.1 removed ODOO_HTTP_BEARER, which the server read but never used.
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    env, options = plugin["mcpServers"]["odoo"]["env"], plugin["userConfig"]
    names = _env_names_the_server_reads()
    assert {"ODOO_URL", "ODOO_API_KEY", "ODOO_PASSWORD"} <= names  # the scan finds reads
    for name in sorted(n for n in names if _CREDENTIAL_NAME.search(n)):
        passed = re.fullmatch(r"\$\{user_config\.([a-z0-9_]+)\}", env.get(name, ""))
        assert passed, f"the server reads {name}, which plugin.json does not pass"
        assert options[passed.group(1)].get("sensitive") is True, name
