# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""CLI entry point: ``odoo-mcp`` / ``python -m odoo_mcp``.

Without options it serves MCP over stdio. ``--verify-audit FILE`` checks the
hash chain of one audit file and exits: 0 when it holds, 1 at the first broken
line (which it names), 2 when the file cannot be read.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .audit import verify_main
from .config import Settings
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
    args = parser.parse_args(argv)
    if args.verify_audit is not None:
        return verify_main(args.verify_audit, sys.stdout)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,  # never pollute stdout (the MCP channel)
    )
    serve(Settings.from_env())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
