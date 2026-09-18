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

Built and maintained by [Transgenia](https://transgenia.org), a **Registered
partner of Anthropic**. (Registered tier — this plugin is an independent
open-source project, not an Anthropic-certified or first-party product.)

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

This is the **public generic core**: it talks to Odoo and nothing else. Any
localization-, governance- or tenant-specific engines (e.g. country e-invoicing,
approval workflows, backups, document AI) are intentionally **out of scope** and
are not part of this repository.

## Commercial support

Need help implementing this against your Odoo, or a custom AI/ERP integration?
[Transgenia](https://transgenia.org) offers AI and Odoo implementation services.
Contact **dev@transgenia.org**. (This is the only Transgenia-specific content in
the repo; the plugin itself is vendor-neutral and works with any Odoo instance.)

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
