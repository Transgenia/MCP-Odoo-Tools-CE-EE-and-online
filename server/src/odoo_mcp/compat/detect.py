# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Detect version / edition / deployment facts of a target Odoo instance."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .deltas import MAX_VERSION, MIN_VERSION

Edition = str  # "community" | "enterprise" | "unknown"
Deployment = str  # "onprem" | "saas" | "unknown"


@dataclass(frozen=True)
class EnvFacts:
    version: int
    edition: Edition
    deployment: Deployment
    raw_version: str = ""

    def clamp(self) -> EnvFacts:
        v = max(MIN_VERSION, min(MAX_VERSION, self.version))
        if v == self.version:
            return self
        return EnvFacts(v, self.edition, self.deployment, self.raw_version)


def parse_major(version_info: dict[str, Any]) -> tuple[int, str]:
    """Extract the major version integer from a ``common.version()`` payload."""
    raw = str(version_info.get("server_version", "")) if version_info else ""
    info = version_info.get("server_version_info") if version_info else None
    if isinstance(info, (list, tuple)) and info:
        try:
            return int(info[0]), raw
        except (TypeError, ValueError):
            pass
    # fall back to parsing the string, e.g. "16.0", "saas~17.2+e", "10.0"
    m = re.search(r"(\d+)", raw)
    if m:
        return int(m.group(1)), raw
    return MAX_VERSION, raw  # optimistic default: newest


def detect_edition_from_version(version_info: dict[str, Any]) -> Edition:
    """Cheap edition hint from the version string ('+e' suffix => Enterprise)."""
    raw = str(version_info.get("server_version", "")) if version_info else ""
    if "+e" in raw:
        return "enterprise"
    return "unknown"


def detect_deployment(base_url: str) -> Deployment:
    host = base_url.lower()
    if ".odoo.com" in host:
        return "saas"
    return "onprem"


def probe(
    base_url: str,
    version_info: dict[str, Any],
    module_installed: Callable[[str], bool] | None = None,
) -> EnvFacts:
    """Build :class:`EnvFacts` from a version payload plus optional module probe.

    ``module_installed`` is an authoritative check (queries ``ir.module.module``)
    used to confirm Enterprise when the version string alone is inconclusive.
    """
    version, raw = parse_major(version_info)
    edition = detect_edition_from_version(version_info)
    if edition == "unknown" and module_installed is not None:
        try:
            edition = "enterprise" if module_installed("web_enterprise") else "community"
        except Exception:
            edition = "unknown"
    deployment = detect_deployment(base_url)
    return EnvFacts(version=version, edition=edition, deployment=deployment, raw_version=raw).clamp()
