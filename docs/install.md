# Install & run

## As a Claude plugin (recommended)

```
/plugin marketplace add Transgenia/MCP-Odoo-Tools-CE-EE-and-online
/plugin install odoo-tools
/odoo-tools:odoo-setup-mcp
```

The `mcpServers` entry launches the server with:

```
uvx --from ${CLAUDE_PLUGIN_ROOT}/server odoo-mcp
```

so `uv` builds and runs the bundled server from source — no PyPI release needed.

## Run the MCP server directly

```bash
# with uv (recommended; brings its own Python)
uvx --from ./server odoo-mcp

# or from a checkout with your own Python 3.11+
cd server && pip install -e . && python -m odoo_mcp
```

Environment (see the root README for the full table): `ODOO_URL`, `ODOO_DB`,
`ODOO_LOGIN`, `ODOO_API_KEY` (or `ODOO_PASSWORD`).

Optional extras:

```bash
pip install -e "./server[cache]"    # TTL schema cache (cachetools)
pip install -e "./server[metrics]"  # Prometheus /metrics
pip install -e "./server[otel]"     # OpenTelemetry OTLP tracing
```

## CLI fallback (optional)

```
/odoo-tools:odoo-setup-cli
```
Requires Node.js 18+. Installs the CLI to `~/.claude/tools/odoo-cli`.

## Docker (HTTP transport, optional)

See [`../docker/`](../docker/). Useful for a shared/multi-tenant deployment
where clients pass `X-Odoo-Url/Db/Login` + `Bearer` headers.

## Verify

Call `odoo_version` (or run `/odoo-tools:odoo-doctor`). A successful response
reporting version/edition/deployment/transport confirms the setup end-to-end.
