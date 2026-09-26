# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Entry point the plugin runs: ``python3 ${CLAUDE_PLUGIN_ROOT}/server/run_stdio.py``.

Standard library only. It puts the bundled ``src`` folder first on
``sys.path`` (so a different ``odoo_mcp`` package installed on the machine can
never shadow the reviewed code) and starts the stdio MCP server. It installs
nothing and downloads nothing.
"""

import os
import sys

# Runs before any project code, so it must also parse on older interpreters:
# hence the explicit check and %-formatting rather than an f-string.
if sys.version_info < (3, 9):  # noqa: UP036
    sys.stderr.write(
        "odoo-tools: Python 3.9 or newer is required (found %s)\n"  # noqa: UP031
        % sys.version.split()[0]
    )
    sys.exit(1)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from odoo_mcp.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
