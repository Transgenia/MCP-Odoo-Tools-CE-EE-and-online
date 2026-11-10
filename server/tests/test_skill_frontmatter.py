# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Every skill, command and agent of the full plugin has a frontmatter a strict YAML reader accepts.

The ``description`` of ``odoo-mcp-tools`` and ``odoo-setup-mcp`` held an unquoted ``: `` since
1.6.0 (commit 666e6ae), which a strict YAML parser reads as a mapping: both files failed to
load for a reader stricter than Claude Code's own (the review portal lists INVENTORY_GAPS
without naming a file). The stdlib check always runs; PyYAML, where it is installed, is the
independent reading of the same frontmatters. Both read what git tracks.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _preflight() -> Any:
    spec = importlib.util.spec_from_file_location("directory_preflight",
                                                  ROOT / "scripts" / "directory_preflight.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["directory_preflight"] = module
    spec.loader.exec_module(module)
    return module


def _tracked() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                             check=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("not a git checkout")
    return [name for name in out.decode("utf-8").split("\0") if name]


def test_the_full_plugins_frontmatters_parse_for_a_strict_reader() -> None:
    # Two skills had an unquoted ': ' in their description since 1.6.0, which a strict
    # YAML parser reads as a mapping (the portal lists INVENTORY_GAPS without a file).
    preflight = _preflight()
    bad = []
    for rel in _tracked():
        path = ROOT / rel
        if rel.endswith(".md") and rel.startswith(("skills/", "commands/", "agents/")):
            bad += [f"{f.path}:{f.line}" for f in preflight.check_frontmatter(
                rel, path.read_text(encoding="utf-8")) if f.severity == "error"]
    assert not bad, bad


def test_every_frontmatter_loads_with_pyyaml_when_it_is_installed() -> None:
    # The stdlib check above is the guard that always runs; PyYAML, where it is installed,
    # is the independent reading of the same frontmatters, those of the edition included.
    yaml = pytest.importorskip("yaml")
    preflight = _preflight()
    names = [rel for rel in _tracked() if rel.endswith(".md")
             and rel.startswith(("skills/", "commands/", "agents/", "distribution/directory/"))]
    assert names
    for rel in names:
        block = preflight.split_frontmatter((ROOT / rel).read_text(encoding="utf-8"))
        if block is None:
            continue
        loaded = yaml.safe_load("\n".join(line for _, line in block))
        assert isinstance(loaded, dict) and loaded.get("description"), rel
