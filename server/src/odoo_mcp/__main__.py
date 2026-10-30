# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""CLI entry point: ``odoo-mcp`` / ``python -m odoo_mcp``.

Without options it serves MCP over stdio. Five offline commands exit instead,
and none contacts Odoo:

  * ``--check-policy FILE [--profile P] [--explain MODEL:OP[:METHOD] ...]
    [--json]`` checks a permission policy file as the server would load it and
    explains decisions (``policy/cli.py``): 0 when it is valid, 1 when it has an
    error (the server would start locked), 2 on bad usage;
  * ``--verify-audit FILE`` checks the hash chain of one audit file: 0 when it
    holds, 1 at the first broken line (which it names), 2 when the file cannot
    be read;
  * ``--diagnose [--diag-dir DIR] [--audit-dir DIR] [--json]`` prints the support
    report (``diagnostics.py``): the plugin, Python and OS versions, the last
    diagnostics events, a 7-day audit summary and the policy, with no keys, URLs,
    logins or record data. The folders default to ODOO_DIAG_DIR and
    ODOO_AUDIT_DIR. It exits 0, files present or not (2 on bad usage);
  * ``--check-copies [--json]`` reads ``claude plugin list --json`` on stdin and
    checks that one odoo-tools copy, 1.5.0 or newer, is active
    (``install_check.py``);
  * ``--check-options [--json]`` reads ``claude plugin configure <id> --json`` on
    stdin and checks that copy's options. Both exit 0 when there is nothing to
    fix, 1 when there is, 2 when the input is not that JSON; neither runs a
    program or prints a secret.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .audit import verify_main
from .config import Settings
from .diagnostics import diagnose_main
from .install_check import check_main
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
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="print a support report from the local diagnostics and audit files (no keys, "
        "URLs, logins or record data) and exit 0; it never contacts Odoo",
    )
    parser.add_argument("--diag-dir", metavar="DIR",
                        help="with --diagnose: the diagnostics folder (default ODOO_DIAG_DIR)")
    parser.add_argument("--audit-dir", metavar="DIR",
                        help="with --diagnose: the audit folder (default ODOO_AUDIT_DIR)")
    parser.add_argument(
        "--check-copies",
        action="store_true",
        help="read `claude plugin list --json` on stdin and check that one odoo-tools "
        "copy, 1.5.0 or newer, is active; prints the commands that fix it (exit 0 ok, "
        "1 to fix, 2 bad input). It runs no program and never contacts Odoo",
    )
    parser.add_argument(
        "--check-options",
        action="store_true",
        help="read `claude plugin configure <id> --json` on stdin and check that copy's "
        "options: connection, credential, URL, permission options (exit 0 ok, 1 to fix, "
        "2 bad input). It prints no secret and never contacts Odoo",
    )
    parser.add_argument("--json", action="store_true",
                        help="with --check-policy, --diagnose, --check-copies or "
                        "--check-options: print the report as JSON")
    args = parser.parse_args(argv)
    checking = args.check_policy is not None
    commands = [flag for flag, used in (("--verify-audit", args.verify_audit is not None),
                                        ("--check-policy", checking),
                                        ("--diagnose", args.diagnose),
                                        ("--check-copies", args.check_copies),
                                        ("--check-options", args.check_options)) if used]
    if len(commands) > 1:
        parser.error(f"use one of {', '.join(commands)}, not several")
    if not checking and (args.profile is not None or args.explain):
        parser.error("--profile and --explain need --check-policy FILE")
    if args.json and not (checking or args.diagnose or args.check_copies
                          or args.check_options):
        parser.error("--json needs --check-policy FILE, --diagnose, --check-copies or "
                     "--check-options")
    if not args.diagnose and (args.diag_dir is not None or args.audit_dir is not None):
        parser.error("--diag-dir and --audit-dir need --diagnose")
    if args.verify_audit is not None:
        return verify_main(args.verify_audit, sys.stdout)
    if args.check_copies or args.check_options:
        return check_main("copies" if args.check_copies else "options", sys.stdin,
                          sys.stdout, as_json=args.json)
    if args.diagnose:
        return diagnose_main(diag_dir=args.diag_dir, audit_dir=args.audit_dir,
                             as_json=args.json, tools=registry.all(), out=sys.stdout)
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
