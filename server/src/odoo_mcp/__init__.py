# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Clean-room MCP server for Odoo CE/EE/online, versions 10-19.

This package is an original implementation. It does NOT derive from any
AGPL-licensed Odoo MCP project; it only relies on Odoo's public XML-RPC /
JSON-RPC interfaces and publicly known model/field naming, which are not
themselves copyrightable.
"""

# The one runtime version: the plugin runs this package from source, where an
# older odoo-mcp-tools installed in site-packages would otherwise answer an
# importlib.metadata lookup. scripts/check_release_version.py keeps it equal to
# pyproject.toml and the plugin manifests.
__version__ = "1.3.0"
