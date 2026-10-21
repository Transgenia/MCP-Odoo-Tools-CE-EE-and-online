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

It also checks the permission policy (1.5.0), from the two policy options and
nothing else: the profile (CLAUDE_PLUGIN_OPTION_ODOO_POLICY) and the policy file path
(CLAUDE_PLUGIN_OPTION_ODOO_POLICY_FILE). When one is set, it loads them with the MCP
server's own loader (odoo_mcp.policy.loader, imported from this plugin's server/src,
so there is one validator) and, when the server would start locked, says why: a
"systemMessage" for the user on a new session at most once a day (its own timestamp
file), and the same text in "additionalContext" for Claude. The policy file is read
as the server reads it; it holds rules, never a credential.

Standard library only; it must run on Python 3.9. hooks.json starts it only when
python3 is 3.9 or newer, so an old or missing Python shows no error from this hook.
That holds wherever Claude Code runs hooks in bash (macOS, Linux, Windows with Git
Bash); without Git Bash, Windows runs shell-form hooks in PowerShell, where the
hooks.json commands do not parse (see the README, Requirements). It also checks
whether the container mode's ~/.odoo-tools/mcp/odoo.env exists, without opening it.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

REQUIRED = ("odoo_url", "odoo_db", "odoo_login")
# /odoo-tools:deploy-local container mode runs the server from this env file instead of
# the plugin options (commands/deploy-local.md, Mode B). Only its existence is checked.
CONTAINER_ENV = (".odoo-tools", "mcp", "odoo.env")
NOTICE_EVERY = 24 * 3600  # seconds between two notices shown to the user
MARKER = "options-notice"
POLICY_MARKER = "policy-notice"
# The permission policy options: the only other options this hook reads.
POLICY_PROFILE, POLICY_FILE = "odoo_policy", "odoo_policy_file"
SERVER_SRC = Path(__file__).resolve().parents[1] / "server" / "src"


def _option(key: str) -> str:
    value = os.environ.get("CLAUDE_PLUGIN_OPTION_" + key.upper(), "").strip()
    # Same rule as the server (config.py): an unresolved ${...} counts as unset.
    if value.startswith("${") and value.endswith("}"):
        return ""
    return value


def _is_set(key: str) -> bool:
    return bool(_option(key))


def missing_options() -> list[str]:
    return [key for key in REQUIRED if not _is_set(key)]


def policy_problem() -> tuple[str, str] | None:
    """(E-code, text) when the policy options would lock the MCP server, else None.

    Nothing to check while both options are unset: the server then uses profile
    'standard' and no file. A failure of the check itself says nothing: the server
    reports a locked policy through odoo_version anyway.
    """
    profile, path = _option(POLICY_PROFILE), _option(POLICY_FILE)
    if not profile and not path:
        return None
    try:
        if str(SERVER_SRC) not in sys.path:
            sys.path.insert(0, str(SERVER_SRC))
        # The loader logs an unexpected failure; this hook prints nothing on stderr.
        logging.getLogger("odoo_mcp").addHandler(logging.NullHandler())
        from odoo_mcp import tools as _tools  # noqa: F401  (registers the tool names)
        from odoo_mcp.policy.loader import load_policy
        from odoo_mcp.registry import registry

        settings = SimpleNamespace(policy_profile=profile, policy_file=path, readonly=False)
        policy = load_policy(settings, [tool.name for tool in registry.all()])
    except Exception:  # an old or partial checkout: the server explains the lock itself
        return None
    if not policy.locked:
        return None
    return str(policy.error_code or "E3"), str(policy.error or "")


def policy_texts(problem: tuple[str, str]) -> tuple[str, str]:
    """(systemMessage, additionalContext) for a policy that would lock the server."""
    code, error = problem
    what = "permission profile is not valid" if code == "E1" else (
        "permission policy file has an error")
    message = (
        f"odoo-tools: the {what}, so the Odoo tools are locked: {error} ({code}). Fix it in "
        "/plugin, odoo-tools, Configure options (Permission profile, Permission policy "
        "file) or in the file, then reconnect the server with /mcp."
    )
    context = (
        f"odoo-tools plugin status: the {what} ({code}: {error}), so the odoo-tools MCP "
        "server starts locked: only odoo_version works, and every other Odoo tool refuses "
        "without contacting Odoo. The user fixes this in /plugin (Configure options: "
        "Permission profile, Permission policy file) or in the policy file, then "
        "reconnects the server with /mcp. Tell the user; never edit the policy file or "
        "change these options yourself."
    )
    return message, context


def _container_env_exists() -> bool:
    try:
        return Path.home().joinpath(*CONTAINER_ENV).exists()
    except (OSError, RuntimeError):  # no resolvable home directory
        return False


def _notice_due(now: float, name: str = MARKER) -> bool:
    """True at most once per NOTICE_EVERY, tracked by a timestamp file in the plugin's
    data folder. Without a usable folder the notice is always due."""
    data = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    if not data:
        return True
    marker = Path(data) / name
    try:
        # A marker dated in the future (clock set back, restored backup, synced home)
        # counts as due, so it cannot silence the notice for longer than a day.
        if 0 <= now - marker.stat().st_mtime < NOTICE_EVERY:
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


def add_policy_notice(output: dict | None, problem: tuple[str, str], source: str | None,
                      notice_due: bool) -> dict:
    """``output`` with the policy texts added (the context always, the message when due)."""
    message, context = policy_texts(problem)
    if output is None:
        output = {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                         "additionalContext": context}}
    else:
        specific = output["hookSpecificOutput"]
        specific["additionalContext"] = specific["additionalContext"] + " " + context
    if source in (None, "startup") and notice_due:
        shown = output.get("systemMessage")
        output["systemMessage"] = f"{shown}\n{message}" if shown else message
    return output


def main() -> int:
    try:
        source = _read_event().get("source")
        source = source if isinstance(source, str) else None
        gaps = missing_options()
        container = bool(gaps) and _container_env_exists()
        wants_notice = bool(gaps) and source in (None, "startup") and not container
        due = _notice_due(time.time()) if wants_notice else False
        output = build_output(gaps, source, due, container)
        problem = policy_problem()
        if problem is not None:
            policy_due = (_notice_due(time.time(), POLICY_MARKER)
                          if source in (None, "startup") else False)
            output = add_policy_notice(output, problem, source, policy_due)
        if output:
            sys.stdout.write(json.dumps(output))
    except Exception:  # a notice must never break the session
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
