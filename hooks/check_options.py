#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""SessionStart hook: say when the Odoo connection options are missing.

Claude Code exports each saved plugin option to hooks as CLAUDE_PLUGIN_OPTION_<KEY>
and exports nothing for an option without a saved value. Cowork and claude.ai chat
never prompt for plugin options, so there the variables are absent.

This hook looks only at the three required, non-sensitive options (URL, database,
login), and only at whether they are present. It never reads the API key or the
password option (since v1.2.0 no plugin hook does: a directory finding), never
prints or stores a value, prints nothing when the three are set, and always exits 0:
a SessionStart hook must not get in the way of the session. A missing credential is
reported by the MCP server itself (odoo_version) and by the guided route.

Output, as Claude Code hook JSON: "systemMessage" is shown to the user, on a new
session (source "startup") and at most once a day; "additionalContext" goes to Claude
on every SessionStart, so the reason survives /clear and compaction. With the
container mode's env file present, only Claude is told.

Standard library only; it must run on Python 3.9. hooks.json starts it only when
python3 is 3.9 or newer, so an old or missing Python never shows a hook error.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REQUIRED = ("odoo_url", "odoo_db", "odoo_login")
# /odoo-tools:deploy-local container mode runs the server from this env file instead of
# the plugin options (commands/deploy-local.md, Mode B). Only its existence is checked.
CONTAINER_ENV = (".odoo-tools", "mcp", "odoo.env")
NOTICE_EVERY = 24 * 3600  # seconds between two notices shown to the user
MARKER = "options-notice"


def _is_set(key: str) -> bool:
    value = os.environ.get("CLAUDE_PLUGIN_OPTION_" + key.upper(), "").strip()
    # Same rule as the server (config.py): an unresolved ${...} counts as unset.
    return bool(value) and not (value.startswith("${") and value.endswith("}"))


def missing_options() -> list[str]:
    return [key for key in REQUIRED if not _is_set(key)]


def _container_env_exists() -> bool:
    try:
        return Path.home().joinpath(*CONTAINER_ENV).exists()
    except (OSError, RuntimeError):  # no resolvable home directory
        return False


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


def build_output(gaps: list[str], source: str | None, notice_due: bool,
                 container_env: bool = False) -> dict | None:
    if not gaps:
        return None
    listed = ", ".join(gaps)
    context = (
        f"odoo-tools plugin status: the required connection options {listed} have no "
        "saved value in this session, so the plugin's Odoo MCP server has no connection "
        "settings and its odoo_* tools are unavailable or answer with a configuration "
        "error. Claude Code collects these options in /plugin (Configure options), and "
        "`claude plugin configure <name@marketplace> --values-stdin` sets them without "
        "the dialog. Cowork and claude.ai chat have no form for plugin options. The user "
        "enters the API key or password in that form, never in the chat. An Odoo "
        "connector added separately in Claude does not depend on these options. The "
        "guided route /odoo-tools:odoo-setup-mcp (Phase 0b) covers this case."
    )
    if container_env:
        context += (
            " The file ~/.odoo-tools/mcp/odoo.env exists, so the container server "
            "odoo-tools-docker from /odoo-tools:deploy-local may be the one in use."
        )
    output: dict = {
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}
    }
    if source in (None, "startup") and notice_due and not container_env:
        output["systemMessage"] = (
            f"odoo-tools: the Odoo tools are off because these plugin options are not set: "
            f"{listed}. In Claude Code, open /plugin, select odoo-tools and choose Configure "
            "options. Cowork and claude.ai chat cannot ask for plugin options (see the "
            "plugin README, \"If the Odoo tools do not appear\"). If you reach Odoo through "
            "a remote connector instead, this notice does not apply."
        )
    return output


def _read_event() -> dict:
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None or sys.stdin.isatty():
        return {}
    try:
        # Bytes, so json detects the UTF-8 that Claude Code sends whatever the locale's
        # encoding is (Windows pipes default to the ANSI code page).
        raw = stream.read()
        event = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        return {}
    return event if isinstance(event, dict) else {}


def main() -> int:
    try:
        source = _read_event().get("source")
        source = source if isinstance(source, str) else None
        gaps = missing_options()
        container = bool(gaps) and _container_env_exists()
        wants_notice = bool(gaps) and source in (None, "startup") and not container
        due = _notice_due(time.time()) if wants_notice else False
        output = build_output(gaps, source, due, container)
        if output:
            sys.stdout.write(json.dumps(output))
    except Exception:  # a notice must never break the session
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
