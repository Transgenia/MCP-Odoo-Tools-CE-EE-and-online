#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Generate the tables of docs/policy.md from the policy's own data.

``python3 scripts/policy_docs.py --check`` exits 1 when a generated block of
docs/policy.md differs from the data (``server/tests/test_policy_docs.py`` runs
the same check); ``--write`` rewrites the blocks in place. A block sits between
``<!-- generated:NAME -->`` and ``<!-- /generated:NAME -->``; the prose around
it is written by hand. The data: the tiers, NEVER, the outbound methods and
the safe context keys (``policy/tiers.py``), the profiles (``policy/model.py``),
the error and warning texts (``policy/loader.py``) and the tools each profile
hides (the registry).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "policy.md"
sys.path.insert(0, str(ROOT / "server" / "src"))

from odoo_mcp import tools as _tools  # noqa: F401  (registers the tools)
from odoo_mcp.policy.loader import ERRORS, WARNINGS
from odoo_mcp.policy.model import PROFILES, Policy
from odoo_mcp.policy.tiers import (
    BEST_EFFORT,
    NEVER,
    OPERATIONS,
    OUTBOUND_METHODS,
    SAFE_CONTEXT_KEYS,
    TIERS,
)
from odoo_mcp.registry import registry

BLOCK = re.compile(r"(<!-- generated:([a-z-]+) -->\n)(.*?)(<!-- /generated:\2 -->)", re.DOTALL)
SEALED_PROFILES = ("readonly", "standard", "builder")


def _code(text: str) -> str:
    return f"`{text}`"


def _allowed(ops: frozenset[str]) -> str:
    if not ops:
        return "nothing"
    if ops == frozenset(OPERATIONS):
        return "everything"
    return ", ".join(op for op in OPERATIONS if op in ops)


def tiers_table() -> str:
    rows = ["| Tier | Models | `readonly` | `standard` | `builder` | Why |",
            "|---|---|---|---|---|---|"]
    for tier in TIERS:
        names = [_code(name) + (" (best-effort)" if name in BEST_EFFORT else "")
                 for name in tier.models]
        if tier.exceptions:
            names.append("except " + ", ".join(_code(name) for name in sorted(tier.exceptions)))
        cells = []
        for name in SEALED_PROFILES:
            profile_tiers = PROFILES[name].tiers
            assert profile_tiers is not None
            cells.append(_allowed(profile_tiers[tier.name]))
        rows.append(f"| `{tier.name}` | {', '.join(names)} | {' | '.join(cells)} | "
                    f"{tier.reason} |")
    return "\n".join(rows) + "\n"


def never_table() -> str:
    rows = ["| Model | Operations | Why |", "|---|---|---|"]
    for entry in NEVER:
        ops = ", ".join(op for op in OPERATIONS if op in entry.ops)
        if entry.methods:
            ops += " (" + ", ".join(_code(m) for m in sorted(entry.methods)) + ")"
        rows.append(f"| {_code(entry.model)} | {ops} | {entry.reason} |")
    return "\n".join(rows) + "\n"


def outbound_list() -> str:
    return ", ".join(_code(name) for name in sorted(OUTBOUND_METHODS)) + "\n"


def context_list() -> str:
    return ", ".join(_code(name) for name in sorted(SAFE_CONTEXT_KEYS)) + "\n"


def hidden_table() -> str:
    tools = registry.all()
    rows = ["| Profile | Tools not listed | Listed |", "|---|---|---|"]
    for name in PROFILES:
        policy = Policy(profile_name=name)
        hidden = [tool.name for tool in tools if not policy.tool_visible(tool)]
        shown = ", ".join(_code(tool) for tool in hidden) or "none"
        rows.append(f"| `{name}` | {shown} | {len(tools) - len(hidden)} |")
    readonly = Policy(profile_name="full", readonly=True)
    hidden = [tool.name for tool in tools if not readonly.tool_visible(tool)]
    rows.append(f"| any profile with Read-only mode on | "
                f"{', '.join(_code(tool) for tool in hidden)} | {len(tools) - len(hidden)} |")
    return "\n".join(rows) + "\n"


def _declared(access: object) -> str:
    """What a tool's ``Access`` declares, in words."""
    parts = []
    arg_ops = getattr(access, "arg_ops", ())
    if arg_ops:
        parts.append(", ".join(arg_ops) + " on the model asked for")
    for op, model in getattr(access, "fixed", ()):
        parts.append(f"{op} {_code(model)}")
    for op, argument in getattr(access, "optional", ()):
        parts.append(f"{op} on the model in {_code(argument)}, when given")
    if getattr(access, "dynamic", None) is not None:
        parts.append("call of the method asked for, plus its class (for example unlink)")
    if getattr(access, "columns_arg", None):
        parts.append(f"the paths of the {_code(access.columns_arg)} columns")
    if getattr(access, "degrade", False):
        parts.append("a refused section is reported, the tool still runs")
    if getattr(access, "stub", False):
        parts.append("never calls Odoo")
    return "; ".join(parts) or "no model"


def _internals(access: object) -> str:
    calls: dict[str, set[str]] = {}
    for internal in getattr(access, "internal", ()):
        calls.setdefault(internal.model, set()).update(internal.methods)
    return "; ".join(f"{_code(model)} {', '.join(sorted(methods))}"
                     for model, methods in calls.items()) or "none"


def mapping_table() -> str:
    tools = registry.all()
    policies = [Policy(profile_name=name) for name in SEALED_PROFILES]
    rows = [("| Tool | Read-only | Declared (Layer A) | Internal calls, each pinned by a "
             "predicate | Hidden in readonly / standard / builder |"),
            "|---|---|---|---|---|"]
    for tool in sorted(tools, key=lambda tool: tool.name):
        hidden = " / ".join("yes" if not policy.tool_visible(tool) else "no"
                            for policy in policies)
        rows.append(f"| {_code(tool.name)} | {'yes' if tool.read_only else 'no'} | "
                    f"{_declared(tool.access)} | {_internals(tool.access)} | {hidden} |")
    return "\n".join(rows) + "\n"


def _texts_table(texts: dict[str, str]) -> str:
    rows = ["| Code | Text |", "|---|---|"]
    for code, text in texts.items():
        rows.append(f"| {code} | {_code(text)} |")
    return "\n".join(rows) + "\n"


GENERATORS = {
    "tiers": tiers_table,
    "never": never_table,
    "outbound-methods": outbound_list,
    "context-keys": context_list,
    "hidden-tools": hidden_table,
    "tool-mapping": mapping_table,
    "errors": lambda: _texts_table(ERRORS),
    "warnings": lambda: _texts_table(WARNINGS),
}


def render(text: str) -> str:
    """``text`` with every generated block replaced by what the data says now."""
    found = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(2)
        if name not in GENERATORS:
            raise KeyError(f"docs/policy.md has an unknown generated block '{name}'")
        found.add(name)
        return match.group(1) + GENERATORS[name]() + match.group(4)

    out = BLOCK.sub(replace, text)
    missing = set(GENERATORS) - found
    if missing:
        raise KeyError(f"docs/policy.md lacks the generated blocks {sorted(missing)}")
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="exit 1 when docs/policy.md drifted")
    mode.add_argument("--write", action="store_true", help="rewrite the generated blocks")
    args = parser.parse_args(argv)
    current = DOC.read_text(encoding="utf-8")
    expected = render(current)
    if args.write:
        if expected != current:
            DOC.write_text(expected, encoding="utf-8")
        return 0
    if expected != current:
        print("docs/policy.md: a generated table differs from the policy data; run "
              "python3 scripts/policy_docs.py --write", file=sys.stderr)
        return 1
    print("docs/policy.md: the generated tables match the policy data")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
