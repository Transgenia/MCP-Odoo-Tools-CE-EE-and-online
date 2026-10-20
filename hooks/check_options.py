#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""SessionStart hook: say when the Odoo connection options are missing.

Claude Code exports each saved plugin option to hooks as CLAUDE_PLUGIN_OPTION_<KEY>
and exports nothing for an option without a saved value. Cowork and claude.ai chat
never prompt for plugin options, so there the variables are absent. This hook reads
only whether those variables are present, never prints or stores their values, and
prints nothing when the options are set. It always exits 0: a SessionStart hook must
not get in the way of the session.

Output, as Claude Code hook JSON: "systemMessage" is shown to the user, on a new
session (source "startup") and at most once a day; "additionalContext" goes to Claude
on every SessionStart, so the reason survives /clear and compaction.

Standard library only; it must run on Python 3.9.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REQUIRED = ("odoo_url", "odoo_db", "odoo_login")
CREDENTIALS = ("odoo_api_key", "odoo_password")
# /odoo-tools:deploy-local container mode runs the server from this env file instead of
# the plugin options (commands/deploy-local.md, Mode B). Only its existence is checked.
CONTAINER_ENV = Path.home() / ".odoo-tools" / "mcp" / "odoo.env"
NOTICE_EVERY = 24 * 3600  # seconds between two notices shown to the user
MARKER = "options-notice"


def _is_set(key: str) -> bool:
    value = os.environ.get("CLAUDE_PLUGIN_OPTION_" + key.upper(), "").strip()
    # Same rule as the server (config.py): an unresolved ${...} counts as unset.
    return bool(value) and not (value.startswith("${") and value.endswith("}"))


def missing_options() -> list[str]:
    gaps = [key for key in REQUIRED if not _is_set(key)]
    if not any(_is_set(key) for key in CREDENTIALS):
        gaps.append("odoo_api_key or odoo_password")
    return gaps


def _notice_due(now: float) -> bool:
    """True at most once per NOTICE_EVERY, tracked by a timestamp file in the plugin's
    data folder. Without a usable folder the notice is always due."""
    data = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    if not data:
        return True
    marker = Path(data) / MARKER
    try:
        if now - marker.stat().st_mtime < NOTICE_EVERY:
            return False
    except OSError:
        pass
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except OSError:
        pass
    return True


def build_output(gaps: list[str], source: str | None, notice_due: bool) -> dict | None:
    if not gaps:
        return None
    listed = ", ".join(gaps)
    context = (
        f"odoo-tools plugin status: the connection options {listed} have no saved value "
        "in this session, so the plugin's Odoo MCP server has no connection settings and "
        "its odoo_* tools are unavailable or answer with a configuration error. Claude "
        "Code collects these options in /plugin (Configure options), and `claude plugin "
        "configure <name@marketplace> --values-stdin` sets them without the dialog. "
        "Cowork and claude.ai chat have no form for plugin options. The user enters the "
        "API key or password in that form, never in the chat. The guided route "
        "/odoo-tools:odoo-setup-mcp (Phase 0b) covers this case."
    )
    output: dict = {
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}
    }
    if source in (None, "startup") and notice_due:
        output["systemMessage"] = (
            f"odoo-tools: the Odoo tools are off because these plugin options are not set: "
            f"{listed}. In Claude Code, open /plugin, select odoo-tools and choose Configure "
            "options. Cowork and claude.ai chat cannot ask for plugin options (see the "
            "plugin README, \"If the Odoo tools do not appear\")."
        )
    return output


def _read_event() -> dict:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return {}
    return event if isinstance(event, dict) else {}


def main() -> int:
    try:
        if CONTAINER_ENV.exists():
            return 0
        source = _read_event().get("source")
        source = source if isinstance(source, str) else None
        gaps = missing_options()
        due = _notice_due(time.time()) if gaps and source in (None, "startup") else False
        output = build_output(gaps, source, due)
        if output:
            sys.stdout.write(json.dumps(output))
    except Exception:  # a notice must never break the session
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
