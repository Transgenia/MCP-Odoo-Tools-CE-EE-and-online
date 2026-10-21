# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""``--check-policy FILE``: check a permission policy file offline, and explain it.

``run_stdio.py --check-policy FILE [--profile P] [--explain MODEL:OP[:METHOD] ...]
[--json]`` loads the file as the server would at start (``load_policy``), with
Read-only mode off, and prints the profile and the digest, the normalised rules
under their source keys, the openings with their reason and expiry, the
warnings, the hidden tools, and one decision line per ``--explain``, for example
``res.users write: REFUSED (tier:security)``. The digest covers the read-only
flag, so a server started with ODOO_READONLY=1 reports another one.

Exit codes: 0 when the file is valid, 1 when it has an error (an E-code: the
server would start locked), 2 on bad usage (``__main__`` reports it). It never
contacts Odoo: the loader and ``Policy.decide`` are pure, and the alias closure
is static. A team's policy repository can run it in CI.

FILE is made absolute against the current folder, so a relative name can be
checked; the plugin option itself must hold an absolute path (E2). An empty
FILE checks the profile alone.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from types import SimpleNamespace
from typing import Any

from .loader import load_policy
from .model import DEFAULT_PROFILE, Policy, parse_explain


def _shown(text: str) -> str:
    """A path or a name for one line of output: printable characters only."""
    return "".join(ch if ch.isprintable() else "?" for ch in text)


def _value(value: Any) -> str:
    if isinstance(value, frozenset):
        return "[" + ", ".join(sorted(value)) + "]"
    return "true" if value is True else "false"


def _rule_text(rule: Any) -> str:
    parts = [f"{op} {_value(value)}" for op, value in rule.ops] or ["no operation set"]
    text = f"{rule.key}: {', '.join(parts)}"
    if rule.expires is not None:
        text += f"; expires {rule.expires.isoformat()}"
    if rule.reason:
        text += f"; reason: {rule.reason}"
    return text


def _rule_json(rule: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"key": rule.key}
    for op, value in rule.ops:
        entry[op] = sorted(value) if isinstance(value, frozenset) else value
    entry["reason"] = rule.reason or None
    entry["expires"] = rule.expires.isoformat() if rule.expires else None
    return entry


def _opening_text(entry: dict[str, Any]) -> str:
    ops = ", ".join(entry["ops"])
    methods = f" ({', '.join(entry['methods'])})" if entry.get("methods") else ""
    until = f" until {entry['expires']}" if entry.get("expires") else ""
    return f"{entry['model']}: {ops}{methods} ({entry['tier']} tier){until}: {entry['reason']}"


def explanations(policy: Policy, specs: Iterable[str]) -> list[dict[str, Any]]:
    """One decision per ``MODEL:OP[:METHOD]``; ValueError on a malformed spec."""
    out = []
    for spec in specs:
        model, op, method = parse_explain(spec)
        decision = policy.decide(op, model, method)
        out.append({"model": model, "op": op, "method": method,
                    "allowed": decision.allowed, "rule": decision.rule,
                    "line": policy.explain(model, op, method)})
    return out


def load_for_check(path: str, profile: str | None, tool_names: Iterable[str]) -> Policy:
    """The policy the server would build from this file and profile (read-only off)."""
    absolute = os.path.abspath(os.path.expanduser(path)) if path else ""
    settings = SimpleNamespace(policy_profile=profile or DEFAULT_PROFILE,
                               policy_file=absolute, readonly=False)
    return load_policy(settings, tool_names)


def check_policy_main(path: str, *, profile: str | None, explain: Sequence[str],
                      as_json: bool, tools: Sequence[Any], out: Any) -> int:
    """Print the check of ``path``; 0 valid, 1 invalid. ``explain`` was parsed by
    the caller already (``parse_explain``), so a malformed spec never gets here."""
    policy = load_for_check(path, profile, [tool.name for tool in tools])
    lines = explanations(policy, explain)
    if as_json:
        report = policy.describe(tools)
        report["valid"] = not policy.locked
        report["rules"] = [_rule_json(rule) for rule in policy.rules]
        report["withheld_fields"] = sorted(policy.withhold)
        report["disabled_tools"] = sorted(policy.disabled)
        report["explain"] = lines
        out.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return 1 if policy.locked else 0
    write = out.write
    write(f"policy file: {_shown(policy.source) if policy.source else 'none (the profile alone)'}\n")
    write(f"profile: {_shown(policy.profile_name)}\n")
    if policy.locked:
        write(f"error: {policy.error_code} {policy.error}\n")
        for entry in lines:
            write(f"explain: {entry['line']}\n")
        write("result: INVALID. The server would start locked: every Odoo tool except "
              "odoo_version is disabled until this error is fixed.\n")
        return 1
    write(f"digest: {policy.digest}\n")
    write(f"rules ({len(policy.rules)}):\n")
    for rule in policy.rules:
        write(f"  {_rule_text(rule)}\n")
    if policy.withhold:
        write(f"withheld fields: {', '.join(sorted(policy.withhold))}\n")
    for name, reason in policy.allow:
        write(f"released field: {name}: {reason}\n")
    if policy.disabled:
        write(f"disabled tools: {', '.join(sorted(policy.disabled))}\n")
    openings = policy.opened_sensitive()
    write(f"openings ({len(openings)}):\n")
    for entry in openings:
        write(f"  {_opening_text(entry)}\n")
    write(f"warnings ({len(policy.warnings)}):\n")
    for code, text in policy.warnings:
        write(f"  {code} {text}\n")
    hidden = [tool.name for tool in tools if not policy.tool_visible(tool)]
    write(f"hidden tools ({len(hidden)}): {', '.join(hidden) or 'none'}\n")
    for entry in lines:
        write(f"explain: {entry['line']}\n")
    write("result: valid\n")
    return 0
