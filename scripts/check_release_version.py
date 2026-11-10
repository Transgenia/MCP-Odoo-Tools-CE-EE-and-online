#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Check that a release version agrees with the manifests and the CHANGELOG.

Used by release.yml before a tag is created (manual runs) and after it is
checked out (every run): ``python3 scripts/check_release_version.py 1.3.0``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The image tag the docs and the deploy command pin: it must be the version being released.
IMAGE_PIN = re.compile(r"ghcr\.io/transgenia/odoo-mcp-tools:([0-9]+(?:\.[0-9]+)*)")
PIN_FILES = ("docs/install.md", "commands/deploy-local.md")


def problems(version: str) -> list[str]:
    found = {
        "plugin.json": json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"],
        "marketplace.json": json.loads(
            (ROOT / ".claude-plugin/marketplace.json").read_text()
        )["plugins"][0]["version"],
    }
    pyproject = re.search(
        r'^version = "([^"]+)"', (ROOT / "server/pyproject.toml").read_text(), re.MULTILINE
    )
    found["pyproject.toml"] = pyproject.group(1) if pyproject else "<missing>"
    # the version the MCP server reports (serverInfo, telemetry)
    runtime = re.search(
        r'^__version__ = "([^"]+)"',
        (ROOT / "server/src/odoo_mcp/__init__.py").read_text(),
        re.MULTILINE,
    )
    found["odoo_mcp/__init__.py"] = runtime.group(1) if runtime else "<missing>"
    issues = [f"{name} has {value}" for name, value in found.items() if value != version]
    for rel in PIN_FILES:
        tags = set(IMAGE_PIN.findall((ROOT / rel).read_text(encoding="utf-8")))
        issues += [f"{rel} pins the image {tag}" for tag in sorted(tags) if tag != version]
    # release.yml publishes this section as the release notes, and it runs after the tag exists:
    # a heading that is not at the start of a line, or an empty section, would leave a tag
    # and a failed release.
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", changelog, re.MULTILINE | re.DOTALL
    )
    if section is None:
        issues.append(f"CHANGELOG.md has no '## [{version}]' section")
    elif not section.group(1).strip():
        issues.append(f"CHANGELOG.md '## [{version}]' section is empty")
    return issues


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not re.fullmatch(r"v?\d+\.\d+\.\d+", argv[0]):
        print("usage: check_release_version.py X.Y.Z", file=sys.stderr)
        return 2
    version = argv[0].removeprefix("v")
    issues = problems(version)
    for issue in issues:
        print(f"::error::release {version}: {issue}")
    if not issues:
        print(f"release {version}: manifests and CHANGELOG agree")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
