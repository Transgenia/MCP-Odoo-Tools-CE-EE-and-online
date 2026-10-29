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

import json
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
    # Versions 1.4.1 and 1.5.0 were held by the directory policy ("Update adds credential
    # forward") while a session-start hook read CLAUDE_PLUGIN_OPTION_* variables. Claude
    # Code exports every saved option, the API key included, to hook processes, so a
    # hook must not read any of them: what a hook needs comes from the plugin's own
    # diagnostics folder.
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
