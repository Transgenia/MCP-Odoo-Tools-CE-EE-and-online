# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""CLI entry point: ``odoo-mcp`` / ``python -m odoo_mcp``."""

from __future__ import annotations

import argparse
import logging
import sys

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
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,  # never pollute stdout (the MCP channel)
    )
    serve(Settings.from_env())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
