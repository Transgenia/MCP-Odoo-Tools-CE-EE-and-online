# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""CLI entry point: ``odoo-mcp`` / ``python -m odoo_mcp``.

Without options it serves MCP over stdio. Two offline checks exit instead, and
neither contacts Odoo:

  * ``--check-policy FILE [--profile P] [--explain MODEL:OP[:METHOD] ...]
    [--json]`` checks a permission policy file as the server would load it and
    explains decisions (``policy/cli.py``): 0 when it is valid, 1 when it has an
    error (the server would start locked), 2 on bad usage;
  * ``--verify-audit FILE`` checks the hash chain of one audit file: 0 when it
    holds, 1 at the first broken line (which it names), 2 when the file cannot
    be read.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .audit import verify_main
from .config import Settings
from .policy.cli import check_policy_main
from .policy.model import PROFILES, parse_explain
from .registry import registry
from .server import serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="odoo-mcp", description=__doc__)
    parser.add_argument(
        "--transport",
        choices=["stdio"],
        default="stdio",
        help="MCP transport (only stdio is supported in this build)",
    )
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--verify-audit",
        metavar="FILE",
        help="check the hash chain of an audit file (odoo-tools-audit-YYYY-MM-DD.jsonl) "
        "and exit; it never contacts Odoo",
    )
    parser.add_argument(
        "--check-policy",
        metavar="FILE",
        help="check a permission policy file (docs/policy.md) as the server would load it "
        "and exit: 0 valid, 1 invalid, 2 bad usage; an empty FILE checks the profile alone. "
        "It never contacts Odoo",
    )
    parser.add_argument(
        "--profile",
        help="with --check-policy: the permission profile the file layers on "
        f"({', '.join(PROFILES)}; default standard)",
    )
    parser.add_argument(
        "--explain",
        metavar="MODEL:OP[:METHOD]",
        action="append",
        default=[],
        help="with --check-policy: print the decision for one operation, e.g. "
        "res.users:write or sale.order:call:action_confirm (repeatable)",
    )
    parser.add_argument("--json", action="store_true",
                        help="with --check-policy: print the report as JSON")
    args = parser.parse_args(argv)
    checking = args.check_policy is not None
    if args.verify_audit is not None and checking:
        parser.error("use --verify-audit or --check-policy, not both")
    if not checking and (args.profile is not None or args.explain or args.json):
        parser.error("--profile, --explain and --json need --check-policy FILE")
    if args.verify_audit is not None:
        return verify_main(args.verify_audit, sys.stdout)
    if checking:
        for spec in args.explain:
            try:
                parse_explain(spec)
            except ValueError as exc:
                parser.error(f"--explain: {exc}")
        return check_policy_main(args.check_policy, profile=args.profile,
                                 explain=args.explain, as_json=args.json,
                                 tools=registry.all(), out=sys.stdout)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,  # never pollute stdout (the MCP channel)
    )
    serve(Settings.from_env())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
