# MCP-Odoo-Tools — CE, EE & online (Odoo 10-19)

A **Claude Code / Cowork plugin** that unifies Odoo tooling into one install:

- **MCP server (primary)** — a clean-room, MIT-licensed Python server exposing
  native Odoo tools (`odoo_search`, `odoo_read`, `odoo_create`, `odoo_write`,
  `odoo_export_records_json/csv`, `odoo_version`, ...) over JSON-RPC with
  automatic XML-RPC fallback, and a **cross-version compatibility layer** that
  makes a single tool call work across **Community, Enterprise and online (SaaS)
  from Odoo 10 through 19**.
- **CLI fallback** — a lightweight TypeScript XML-RPC CLI (Node-only) for when
  you can't run the MCP server, or for scripted batch access.
- **Agents, skills, commands and domain context** to drive both surfaces.

Maintained by [Transgenia](https://transgenia.org).

## Why this exists

Odoo's model and field names drift across versions (`account.invoice` →
`account.move` at v13, analytic fields at v16, package models near v19, API-key
behavior on `/jsonrpc` at v17, and more), and Enterprise adds models Community
lacks. This plugin absorbs those differences behind one stable tool surface so
you don't hand-branch per version.

## Install

```
/plugin marketplace add Transgenia/MCP-Odoo-Tools-CE-EE-and-online
/plugin install odoo-tools
/odoo-tools:odoo-setup-mcp
```

The setup skill collects credentials (via environment) and verifies the
connection with `odoo_version`.

### Requirements

- **MCP server:** `uv`/`uvx` (ships its own Python), or Python 3.11+ to run
  `python -m odoo_mcp` from `server/`.
- **CLI fallback (optional):** Node.js 18+.

### Configuration (environment)

| Variable | Required | Notes |
|----------|----------|-------|
| `ODOO_URL` | yes | `https://host` (no trailing path) |
| `ODOO_DB` | yes | database name |
| `ODOO_LOGIN` | yes | login email |
| `ODOO_API_KEY` | yes* | Odoo ≥ 14; created in Account Security |
| `ODOO_PASSWORD` | yes* | use on Odoo < 14 (no API keys) |
| `ODOO_TRANSPORT_PREF` | no | `auto` (default) / `jsonrpc` / `xmlrpc` |
| `ODOO_TIMEOUT`, `ODOO_CACHE_TTL` | no | ints (seconds) |
| `ODOO_METRICS`, `ODOO_OTEL_ENDPOINT` | no | optional observability |

\* one of `ODOO_API_KEY` or `ODOO_PASSWORD`.

Credentials stay in your environment; nothing is sent to Anthropic or persisted
by the plugin.

## Support matrix

| Dimension | Coverage |
|-----------|----------|
| Versions | Odoo 10 – 19 (compat map + version detection) |
| Editions | Community & Enterprise (EE-only models gated with clear errors) |
| Deployment | Self-hosted & online/SaaS (transport auto-selected) |

Details and the delta table: [`docs/compat-matrix.md`](docs/compat-matrix.md).

## Architecture

See [`docs/architecture.md`](docs/architecture.md). In short: transport
(xmlrpc/jsonrpc/fallback) → session (auth + version/edition facts + schema
cache) → compat (resolve model/field/capability) → tools → MCP stdio.

## Scope

This is the **public generic core**. Localization-, governance- and
tenant-specific engines (e.g. CFDI/SAT, VoBo enforcement, S3 backup, invoice
vision) are intentionally **out of scope** here and live in a separate private
layer.

## Development

```bash
cd server
uv venv && uv pip install -e ".[dev,cache]"   # or python -m venv + pip
pytest -q
ruff check src tests
```

## License

MIT © Transgenia (Centrum Transgenia S.A.S. de C.V.). See `LICENSE` and
[`NOTICE`](NOTICE) for third-party attributions.
