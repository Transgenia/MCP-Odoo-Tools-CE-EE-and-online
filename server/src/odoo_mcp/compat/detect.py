# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Detect version / edition / deployment facts of a target Odoo instance."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from ..errors import AuthError
from .deltas import MAX_VERSION, MIN_VERSION

Edition = str  # "community" | "enterprise" | "unknown"
Deployment = str  # "onprem" | "saas" | "unknown"


# Minor given to a version clamped down from a newer major: it is past every
# saas~19.x line, so removals made on those lines apply to it too.
NEWER_THAN_KNOWN_MINOR = 99


@dataclass(frozen=True)
class EnvFacts:
    version: int
    edition: Edition
    deployment: Deployment
    raw_version: str = ""
    # 0 on a stable series (18.0); N on Odoo Online's saas~<major>.N lines,
    # which sit between two stable series: 18.0 < saas~18.1 < ... < 19.0.
    minor: int = 0

    @property
    def series(self) -> tuple[int, int]:
        return (self.version, self.minor)

    def clamp(self) -> EnvFacts:
        v = max(MIN_VERSION, min(MAX_VERSION, self.version))
        if v == self.version:
            return self
        minor = NEWER_THAN_KNOWN_MINOR if self.version > MAX_VERSION else 0
        return EnvFacts(v, self.edition, self.deployment, self.raw_version, minor)


def parse_version(version_info: dict[str, Any]) -> tuple[int, int, str]:
    """Major, minor and raw string of a ``common.version()`` payload.

    ``server_version_info`` is ``[18, 0, ...]`` on a stable series and
    ``["saas~18", 1, ...]`` on Odoo Online (``server_version`` "saas~18.1+e").
    """
    raw = str(version_info.get("server_version", "")) if version_info else ""
    info = version_info.get("server_version_info") if version_info else None
    if isinstance(info, (list, tuple)) and info:
        major = re.search(r"(\d+)", str(info[0]))
        if major:
            minor = info[1] if len(info) > 1 and isinstance(info[1], int) else 0
            return int(major.group(1)), minor, raw
    # fall back to parsing the string, e.g. "16.0", "saas~17.2+e", "10.0"
    m = re.search(r"(\d+)(?:\.(\d+))?", raw)
    if m:
        return int(m.group(1)), int(m.group(2) or 0), raw
    return MAX_VERSION, 0, raw  # optimistic default: newest


def parse_major(version_info: dict[str, Any]) -> tuple[int, str]:
    """Extract the major version integer from a ``common.version()`` payload."""
    major, _minor, raw = parse_version(version_info)
    return major, raw


def detect_edition_from_version(version_info: dict[str, Any]) -> Edition:
    """Cheap edition hint from the version string ('+e' suffix => Enterprise)."""
    raw = str(version_info.get("server_version", "")) if version_info else ""
    if "+e" in raw:
        return "enterprise"
    return "unknown"


def detect_deployment(base_url: str) -> Deployment:
    # Compare the host name only: a substring test would call
    # "https://example.com/?next=.odoo.com" an Odoo Online instance.
    host = (urlsplit(base_url if "//" in base_url else f"//{base_url}").hostname or "").lower()
    host = host.rstrip(".")  # a fully qualified name ("acme.odoo.com.") is the same host
    if host == "odoo.com" or host.endswith(".odoo.com"):
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
    version, minor, raw = parse_version(version_info)
    edition = detect_edition_from_version(version_info)
    if edition == "unknown" and module_installed is not None:
        try:
            edition = "enterprise" if module_installed("web_enterprise") else "community"
        except AuthError:
            raise  # bad credentials must fail here, not pass as "edition unknown"
        except Exception:
            edition = "unknown"
    deployment = detect_deployment(base_url)
    return EnvFacts(
        version=version, edition=edition, deployment=deployment, raw_version=raw, minor=minor
    ).clamp()
