# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Nothing under a license incompatible with MIT may ship in this plugin.

CONTRIBUTING.md and NOTICE forbid copying code from AGPL-licensed Odoo MCP projects
and from proprietary Odoo modules such as the Odoo Apps ``mcp_server`` module (much.
Consulting, Odoo Proprietary License v1.0), whose license forbids distributing copies.
These checks catch a copied file by its license markers; they cannot prove that no
idea was paraphrased, which is what the clean-room rule is for.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Everything that is installed with the plugin or shipped as a package or image.
SHIPPED = (".claude-plugin", "agents", "cli", "commands", "context", "docker",
           "hooks", "packages", "scripts", "server/src", "skills")
MARKERS = (
    re.compile(r"Odoo Proprietary License"),
    re.compile(r"\bOPL-1\b"),
    re.compile(r"GNU Affero General Public License"),
    re.compile(r"much\.? ?Consulting|muchconsulting", re.IGNORECASE),
    re.compile(r"SPDX-License-Identifier:\s*(?!MIT\b)[A-Za-z0-9.+-]+"),
)
OWN_CODE = ("hooks", "scripts", "server/src")


def _tracked(prefix: str) -> list[Path]:
    try:
        # untracked files too, so a copied file is caught before it is committed
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", prefix],
            cwd=ROOT, check=True, capture_output=True, text=True,
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):  # a release tarball has no .git
        out = [str(p.relative_to(ROOT)) for p in (ROOT / prefix).rglob("*") if p.is_file()]
    return [ROOT / name for name in out]


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None  # binary assets carry no license header


@pytest.mark.parametrize("prefix", SHIPPED)
def test_no_incompatible_license_marker_ships(prefix: str) -> None:
    hits = []
    for path in _tracked(prefix):
        text = _text(path)
        if text is None:
            continue
        for marker in MARKERS:
            for match in marker.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                hits.append(f"{path.relative_to(ROOT)}:{line}: {match.group(0)}")
    assert not hits, "license markers in shipped files:\n" + "\n".join(hits)


def test_own_python_code_declares_mit() -> None:
    missing = [
        str(path.relative_to(ROOT))
        for prefix in OWN_CODE
        for path in _tracked(prefix)
        if path.suffix == ".py"
        and "SPDX-License-Identifier: MIT" not in "".join((_text(path) or "").splitlines(True)[:3])
    ]
    assert not missing, f"no MIT SPDX header in the first lines: {missing}"


def test_manifests_declare_mit() -> None:
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    pyproject = (ROOT / "server/pyproject.toml").read_text(encoding="utf-8")
    assert plugin["license"] == "MIT"
    assert market["plugins"][0]["license"] == "MIT"
    assert re.search(r'^license = \{ text = "MIT" \}$', pyproject, re.MULTILINE)


def test_the_clean_room_rule_covers_proprietary_modules() -> None:
    for name in ("CONTRIBUTING.md", "NOTICE"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "AGPL" in text and "OPL-1" in text, name


def test_the_markers_catch_a_copied_header() -> None:
    # Guards the patterns themselves: a pasted OPL-1 manifest or AGPL header must hit.
    samples = ('"license": "OPL-1",', '"author": "much. Consulting",',
               "Odoo Proprietary License v1.0",
               "# SPDX-License-Identifier: AGPL-3.0-or-later",
               "GNU Affero General Public License")
    for sample in samples:
        assert any(marker.search(sample) for marker in MARKERS), sample
    assert not any(marker.search("# SPDX-License-Identifier: MIT") for marker in MARKERS)
