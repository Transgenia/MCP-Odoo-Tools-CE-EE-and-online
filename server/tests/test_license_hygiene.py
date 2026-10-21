# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Nothing under a license incompatible with MIT may enter this public repository.

CONTRIBUTING.md and NOTICE forbid copying code from AGPL-licensed Odoo MCP projects
and from proprietary Odoo modules, such as the third-party ``mcp_server`` module on
Odoo Apps (Odoo Proprietary License v1.0, OPL-1), whose license forbids publishing or
distributing copies. The repository is public and the plugin installs from its root,
so every file counts, not only the shipped code.

These checks catch a copied file by its license DECLARATIONS (a manifest ``license``
key, a non-permissive SPDX header, or a license title in a file that is not Markdown,
such as a copied LICENSE or a code header), not by a mention, so Markdown
documentation may still explain how to work with such modules over the network. They
cannot prove that no idea was paraphrased: that is what the clean-room rule is for.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Files that discuss these licenses on purpose; each one is reviewed by hand.
ALLOWED = {
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "NOTICE",
    "docs/third-party-ideas.md",
    "server/tests/test_license_hygiene.py",
}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
             ".ruff_cache", "dist", "build"}
# Licenses MIT code may include with attribution.
COMPATIBLE_SPDX = {"MIT", "MIT-0", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC",
                   "0BSD", "CC0-1.0"}
# An Odoo manifest, or a JSON/TOML file, declaring a license MIT cannot absorb.
MANIFEST_LICENSE = re.compile(
    r"""["']license["']\s*[:=]\s*["'](OPL-1|OEEL-1|Other proprietary|A?GPL[^"']*|LGPL[^"']*)["']""",
    re.IGNORECASE)
LICENSE_TITLES = re.compile(r"Odoo Proprietary License|GNU Affero General Public License")
SPDX = re.compile(r"SPDX-License-Identifier:[ \t]*([^\r\n]*)")
# License ids and exceptions start with a letter or digit; AND/OR/WITH join them.
SPDX_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")
SPDX_OPERATORS = {"AND", "OR", "WITH"}
OWN_CODE = ("hooks", "scripts", "server/src", "server/run_stdio.py")


def _files(root: Path = ROOT) -> list[str]:
    try:
        # -z: names with spaces or accents come back unquoted and whole
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root, check=True, capture_output=True, text=True,
        ).stdout.split("\0")
        return [name for name in out if name]
    except (OSError, subprocess.CalledProcessError):  # a release zip has no .git
        return [str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*")
                if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(root).parts)]


def _text(name: str) -> str | None:
    try:
        return (ROOT / name).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None  # binary assets carry no license text


def violations(text: str, name: str = "") -> list[str]:
    found = [m.group(0) for m in MANIFEST_LICENSE.finditer(text)]
    if not name.endswith(".md"):  # a copied LICENSE file or code header, not a doc sentence
        found += [m.group(0) for m in LICENSE_TITLES.finditer(text)]
    for m in SPDX.finditer(text):
        # every id in a compound expression must be compatible ("MIT AND GPL-3.0-only" fails)
        ids = [i for i in SPDX_ID.findall(m.group(1)) if i not in SPDX_OPERATORS]
        if not ids or any(i not in COMPATIBLE_SPDX for i in ids):
            found.append(m.group(0).strip())
    return found


def test_no_incompatible_license_in_the_repository() -> None:
    hits = []
    for name in _files():
        if name in ALLOWED:
            continue
        text = _text(name)
        if text is not None:
            hits += [f"{name}: {hit}" for hit in violations(text, name)]
    assert not hits, "license declarations that MIT cannot absorb:\n" + "\n".join(hits)


def test_own_python_code_declares_mit() -> None:
    missing = [
        name for name in _files()
        if name.endswith(".py") and any(name == p or name.startswith(p + "/") for p in OWN_CODE)
        and "SPDX-License-Identifier: MIT" not in "".join((_text(name) or "").splitlines(True)[:3])
    ]
    assert not missing, f"no MIT SPDX header in the first lines: {missing}"


def test_manifests_declare_mit() -> None:
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    pyproject = (ROOT / "server/pyproject.toml").read_text(encoding="utf-8")
    assert plugin["license"] == "MIT"
    assert market["plugins"][0]["license"] == "MIT"
    assert re.search(r'^license = \{ text = "MIT" \}$', pyproject, re.MULTILINE)


@pytest.mark.parametrize("name", ["NOTICE", "CONTRIBUTING.md"])
def test_the_clean_room_rule_covers_proprietary_modules(name: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8")  # both ship in the release zip too
    assert "AGPL" in text and "OPL-1" in text


@pytest.mark.parametrize("sample", [
    '"license": "OPL-1",',
    "'license': 'LGPL-3',",
    "Odoo Proprietary License v1.0",
    "# SPDX-License-Identifier: AGPL-3.0-or-later",
    "# SPDX-License-Identifier: MIT AND GPL-3.0-only",
    "// SPDX-License-Identifier: (MIT OR Apache-2.0) AND LGPL-2.1-or-later",
    "This program is free software: you can redistribute it under the GNU Affero General Public License",
])
def test_a_copied_declaration_is_caught(sample: str) -> None:
    assert violations(sample)


def test_a_license_title_in_markdown_is_a_mention() -> None:
    sentence = "Some Odoo Apps modules use the Odoo Proprietary License; talk to them over the network."
    assert not violations(sentence, "SUPPORT.md")
    assert violations(sentence, "LICENSE")


@pytest.mark.parametrize("sample", [
    "# SPDX-License-Identifier: MIT",
    "# SPDX-License-Identifier: Apache-2.0",
    "# SPDX-License-Identifier: MIT OR Apache-2.0",
    "<!-- SPDX-License-Identifier: MIT -->",
    "/* SPDX-License-Identifier: BSD-3-Clause */",
    "Talk to the OPL-1 mcp_server module over the network only.",
    "AGPL projects inform ideas, never code.",
])
def test_mentions_and_compatible_licenses_are_allowed(sample: str) -> None:
    assert not violations(sample)


def test_unusual_file_names_are_scanned(tmp_path: Path) -> None:
    # git quotes non-ASCII names unless -z is used; a quoted name would be skipped.
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    repo = tmp_path / "repo"
    (repo / "skills").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for name in ("manifest copy.json", "módulo.json"):
        (repo / "skills" / name).write_text('{"license": "OPL-1"}', encoding="utf-8")
    names = _files(repo)
    assert sorted(names) == ["skills/manifest copy.json", "skills/módulo.json"]
    assert all(violations((repo / n).read_text(encoding="utf-8")) for n in names)
