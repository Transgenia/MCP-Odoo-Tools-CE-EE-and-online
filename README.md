# MCP-Odoo-Tools — CE, EE & online (Odoo 10-19)

[![CI](https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/actions/workflows/ci.yml/badge.svg)](https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](server/pyproject.toml)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-orange)](https://modelcontextprotocol.io)
[![M8ven Score](https://m8ven.ai/badge/mcp/transgenia-mcp-odoo-tools-ce-ee-and-online-zllwvd)](https://m8ven.ai/mcp/transgenia-mcp-odoo-tools-ce-ee-and-online-zllwvd)

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

Claude Code prompts for the connection options when the plugin is enabled
(change them later in `/plugin` → **odoo-tools** → **Configure options**). The
API key and password are `sensitive` options stored in the OS secure credential
store — never in `settings.json` or your shell profile. The setup skill then
verifies the connection with `odoo_version`.

### Requirements

- **MCP server:** Python 3.9+ available as **`python3`** on `PATH`. The plugin
  runs the bundled server source directly:
  `python3 ${CLAUDE_PLUGIN_ROOT}/server/run_stdio.py`. The server uses only the
  Python standard library, so nothing is installed or downloaded when it starts.
  - Linux and macOS usually already have `python3` (on macOS it comes with
    Apple's Command Line Tools).
  - **Windows:** the command must be named `python3`. The Microsoft Store Python
    provides `python3.exe`; the python.org installer provides only `python` and
    `py`. Either install Python from the Microsoft Store, or put a `python3.exe`
    on `PATH` (e.g. a copy of or hard link to `python.exe` in the Python folder).
    A PowerShell or `doskey` alias is not enough: Claude Code starts the command
    directly, not through your shell.
- **CLI fallback (optional):** Node.js 18+.

### What runs on your machine

- **MCP server** — `python3 ${CLAUDE_PLUGIN_ROOT}/server/run_stdio.py`: readable
  Python source shipped in this plugin, with zero third-party runtime
  dependencies. It talks only to the Odoo URL you configure (plus your own
  OTLP collector, if you opt in with `ODOO_OTEL_ENDPOINT`).
- **SessionStart hook** — runs `python3 --version` and prints a warning only
  when `python3` is not runnable (the MCP server could not start). It reads no
  plugin option or secret and contacts nothing.
- **CLI fallback (only if you run `/odoo-tools:odoo-setup-cli`)** — copies the
  bundled CLI source to `~/.claude/tools/odoo-cli`, runs `npm install` and
  `npm run build` there, and creates an owner-only `.env` with placeholders that
  you fill in with your credentials yourself.

### Configuration

As a plugin, configure through the plugin options above. When you run the server
standalone (`python3 server/run_stdio.py` from a checkout, `odoo-mcp` after
`pip install ./server`, or Docker), it reads these environment variables:

| Variable | Required | Notes |
|----------|----------|-------|
| `ODOO_URL` | yes | `https://host` (no trailing path) |
| `ODOO_DB` | yes | database name |
| `ODOO_LOGIN` | yes | login email |
| `ODOO_API_KEY` | yes* | Odoo ≥ 14; created in Account Security |
| `ODOO_PASSWORD` | yes* | use on Odoo < 14 (no API keys) |
| `ODOO_TRANSPORT_PREF` | no | `auto` (default) / `jsonrpc` / `xmlrpc` |
| `ODOO_TIMEOUT` | no | seconds per Odoo call (default 120; plugin option **Request timeout**) |
| `ODOO_CACHE_TTL` | no | int (seconds) |
| `ODOO_METRICS`, `ODOO_OTEL_ENDPOINT` | no | optional observability |

\* one of `ODOO_API_KEY` or `ODOO_PASSWORD`.

The **MCP server** does not persist credentials to disk. Two caveats worth
stating plainly:

- **The optional CLI fallback keeps your credentials in a local `.env`** under
  `~/.claude/tools/odoo-cli` (owner-only; you type the secret in yourself). See
  [`SECURITY.md`](SECURITY.md).
- **When you drive Odoo through an AI agent**, the tool *results* (the Odoo records
  you query) are returned to your MCP client and sent to your model provider (e.g.
  Anthropic, for Claude) to be processed, exactly like any other tool an agent
  uses. The MCP server talking directly to Odoo means Transgenia never proxies or
  stores your data; it does not mean company data is withheld from the model.

### Telemetry (opt-in, disabled by default)

No usage data leaves your machine unless you opt in with `ODOO_TELEMETRY=opt-in`
and manually share the payload shown by `/odoo-doctor` (which calls the
read-only `odoo_telemetry_preview` tool). When enabled, only
`plugin_version`, `odoo_version_major`, edition/deployment labels and aggregate
generic tool counters are included — never URL, DB, login, secrets, PII,
modules or billing. No schedules, no boot hooks, no background sends.
(This covers the telemetry payload only; `ODOO_METRICS`/`ODOO_OTEL_ENDPOINT`
remain separate explicit opt-ins for local Prometheus/OTLP observability.)
Details: [`SECURITY.md`](SECURITY.md#opt-in-telemetry-disabled-by-default).

## Privacy

**[Privacy policy](PRIVACY.md)** · Transgenia receives and retains no data from
this plugin. It reads records (which may include personal data such as names,
emails and addresses) from your own Odoo only when asked. Services it contacts:

- **Your Odoo instance** (the URL you configure) — from the MCP server, or from
  the optional CLI fallback.
- **Your model provider** — tool results go back to your MCP client and model,
  as with any tool.
- **npm**, only if you set up the optional CLI fallback (`npm install`; no Odoo
  data sent). The MCP server downloads nothing.
- **Optional, off by default:** your own OTLP collector (`ODOO_OTEL_ENDPOINT`).

Corporate notice: <https://transgenia.org/en/legal-privacy.html>.

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
python3 -m venv .venv && . .venv/bin/activate   # or: uv venv && uv pip install ...
pip install -e ".[dev,cache]"
pytest -q -m "not live"
ruff check src tests
```

The `dev` extra adds the official `mcp` package (Python 3.10+ only) for one
interop test that drives this server with the official MCP client; the server
itself never imports it, and the plugin never installs it.

## License

MIT © Transgenia (Centrum Transgenia S.A.S. de C.V.). See `LICENSE` and
[`NOTICE`](NOTICE) for third-party attributions.
