# odoo-mcp-tools (server)

Clean-room MIT MCP server for Odoo — Community, Enterprise and online (SaaS),
across major versions **10 to 19**. This is the Python package that backs the
`MCP-Odoo-Tools-CE-EE-and-online` Claude plugin.

It exposes generic Odoo tools (search / read / search_read / create / write /
unlink / execute / export / translate / report / version / connections) over a
transport layer that speaks JSON-RPC with automatic XML-RPC fallback, and a
**cross-version compatibility layer** that resolves model/field names so a
single tool call works across every supported version.

Not derived from any AGPL project; relies only on Odoo's public RPC interfaces.
It has **no third-party runtime dependencies**: the MCP stdio protocol and both
transports use only the Python standard library. Requires Python 3.9+.

## Install & run

```bash
python3 run_stdio.py               # from a checkout of server/, nothing to install
pip install . && odoo-mcp          # or install the package, then the entry point
```

The Claude plugin runs `python3 ${CLAUDE_PLUGIN_ROOT}/server/run_stdio.py`
directly, so nothing is installed when the plugin starts. A Dockerfile is in
the repository's `docker/` folder.

Configure via environment: `ODOO_URL`, `ODOO_DB`, `ODOO_LOGIN`,
`ODOO_API_KEY` (or `ODOO_PASSWORD`). Optional: `ODOO_TRANSPORT_PREF`
(`auto`|`jsonrpc`|`xmlrpc`), `ODOO_TIMEOUT`, `ODOO_CACHE_TTL`, `ODOO_METRICS`,
`ODOO_OTEL_ENDPOINT`.

See the repository root README for the full plugin, the CLI fallback, and the
compatibility matrix.

## License

MIT © Transgenia (Centrum Transgenia S.A.S. de C.V.)
