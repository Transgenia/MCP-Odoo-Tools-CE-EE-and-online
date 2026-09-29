# MCP-Odoo-Tools — CE, EE & online (Odoo 10-19)

[![CI](https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/actions/workflows/ci.yml/badge.svg)](https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](server/pyproject.toml)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-orange)](https://modelcontextprotocol.io)
[![Claude Code plugin](https://img.shields.io/badge/Claude_Code-plugin-D97757?logo=claude&logoColor=white)](https://claude.com/claude-code)
[![Claude AI](https://img.shields.io/badge/Claude-AI-D97757?logo=claude&logoColor=white)](https://claude.ai)
[![Odoo ERP 10-19](https://img.shields.io/badge/Odoo_ERP-10--19-714B67?logo=odoo&logoColor=white)](https://www.odoo.com)
[![Odoo CE | EE | Online](https://img.shields.io/badge/Odoo-CE_%7C_EE_%7C_Online-714B67?logo=odoo&logoColor=white)](docs/compat-matrix.md)
[![M8ven Score](https://m8ven.ai/badge/mcp/transgenia-mcp-odoo-tools-ce-ee-and-online-zllwvd)](https://m8ven.ai/mcp/transgenia-mcp-odoo-tools-ce-ee-and-online-zllwvd)

A **Claude Code / Cowork plugin** that unifies Odoo tooling into one install:

- **MCP server (primary)** — a clean-room, MIT-licensed Python server exposing
  native Odoo tools (`odoo_search`, `odoo_read`, `odoo_create`, `odoo_write`,
  `odoo_export_records_json/csv`, `odoo_version`, ...) over **JSON-2** (Odoo's
  new API, saas~18.4 / 19.0+) or JSON-RPC, with automatic XML-RPC fallback, and
  a **cross-version compatibility layer** that
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
`account.move` at v13, analytic fields at v16, package models near v19, the
RPC API itself from v19, and more), and Enterprise adds models Community
lacks. This plugin absorbs those differences behind one stable tool surface so
you don't hand-branch per version.

## Install

```
/plugin marketplace add Transgenia/MCP-Odoo-Tools-CE-EE-and-online
/plugin install odoo-tools
/odoo-tools:odoo-setup-mcp
```

**`/odoo-tools:odoo-setup-mcp` is the guided route**: it detects what is already
set up and walks you through **setup → verification → hands-on training →
daily use → deployment** to your team or production, one question at a time.
No Odoo to practise with? It offers a local sandbox (below).

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
- **Local infrastructure (only if you run `/odoo-tools:deploy-local` and
  confirm)** — Docker containers on your machine: the sandbox (PostgreSQL + Odoo
  on `127.0.0.1`, files in `~/.odoo-tools/sandbox`) or the MCP server image.
  Nothing starts automatically; no hook runs Docker.
- **CLI fallback (only if you run `/odoo-tools:odoo-setup-cli`)** — copies the
  bundled CLI source to `~/.claude/tools/odoo-cli`, runs `npm install` and
  `npm run build` there, and creates an owner-only `.env` with placeholders that
  you fill in with your credentials yourself.

### Local infrastructure: `/odoo-tools:deploy-local`

Provided by Transgenia, started only when you run the command (Docker required):

- **Sandbox** — PostgreSQL + **Odoo Community** 10.0 to 19.0 on your machine, bound to
  `127.0.0.1`, with a database (demo data optional) ready for the plugin. Images
  come from `ghcr.io/transgenia` (mirrors of the official `odoo` and `postgres`
  images) with automatic fallback to Docker Hub. Passwords are generated locally
  into `~/.odoo-tools/sandbox/.env` (owner-only) and never printed. Script:
  [`scripts/deploy_local.py`](scripts/deploy_local.py) (standard library only).
  `status`, `down`, `logs` and `destroy --yes` manage it afterwards. Odoo
  10.0-16.0 are for testing and migrations only (Odoo S.A. maintains the three
  latest series); images up to 15.0 are amd64-only (ARM Linux needs binfmt/QEMU
  emulation). Each series gets a PostgreSQL it supports.
  **Community (CE) only**: Transgenia cannot provide Odoo Enterprise (licensed by
  Odoo S.A.) or Odoo Online (Odoo S.A.'s SaaS) instances — connect your own
  instance to use them (on Odoo Online, the plan must include external API access).
- **MCP server as a container** — `ghcr.io/transgenia/odoo-mcp-tools`, for
  machines without Python 3.9+, connected to an existing Odoo.

### Configuration

As a plugin, configure through the plugin options above. When you run the server
standalone (`python3 server/run_stdio.py` from a checkout, `odoo-mcp` after
`pip install ./server`, or Docker), it reads these environment variables:

| Variable | Required | Notes |
|----------|----------|-------|
| `ODOO_URL` | yes | `https://host` (no trailing path) |
| `ODOO_DB` | yes | database name |
| `ODOO_LOGIN` | yes | login email |
| `ODOO_API_KEY` | yes* | Odoo ≥ 14; created in Account Security. The only credential JSON-2 accepts |
| `ODOO_PASSWORD` | yes* | use on Odoo < 14 (no API keys) |
| `ODOO_TRANSPORT_PREF` | no | `auto` (default) / `json2` / `jsonrpc` / `xmlrpc` (see [Transports](#transports)) |
| `ODOO_TIMEOUT` | no | seconds per Odoo call (default 120; plugin option **Request timeout**) |
| `ODOO_CACHE_TTL` | no | int (seconds) |
| `ODOO_METRICS`, `ODOO_OTEL_ENDPOINT` | no | optional observability |

\* one of `ODOO_API_KEY` or `ODOO_PASSWORD`.

### Tools

28 MCP tools. With Read-only mode (`ODOO_READONLY=1`) every write tool is
refused before anything reaches Odoo.

| Group | Tools |
|-------|-------|
| Connection | `odoo_version`, `odoo_connections`, `odoo_telemetry_preview` |
| Read | `odoo_search`, `odoo_search_count`, `odoo_read`, `odoo_search_read`, `odoo_read_group`, `odoo_fields_get`, `odoo_list_models`, `odoo_module_info`, `odoo_translate_get`, `odoo_report` |
| Export | `odoo_export_records_json`, `odoo_export_records_csv` |
| Write | `odoo_create`, `odoo_write`, `odoo_unlink`, `odoo_execute`, `odoo_translate_set` |
| Studio-style (write) | `odoo_add_field`, `odoo_add_automation` |
| Odoo Online (useful on any Odoo) | read: `odoo_online_profile`, `odoo_api_catalog`, `odoo_access_check`, `odoo_record_documents`; write: `odoo_import_preview`, `odoo_import` |

The Odoo Online tools cover what an Online database makes hard: no custom
Python, API access on Custom plans only, API keys that expire (18+), a new
saas~X.Y line every few months, no PDF rendering over RPC, and imports as the
sanctioned bulk path.

| Tool | What it does | Odoo |
|------|--------------|------|
| `odoo_online_profile` | One read: series and line (`19.0` or `saas~19.2`), deployment and how sure that is, the transport, whether JSON-2 and Odoo's `/doc-bearer` catalog are usable, the deprecation notice and when `/xmlrpc` and `/jsonrpc` disappear, the user and companies, 2FA, the user's API keys with their expiry (names and dates only, never key material), installed applications, imported data modules, Studio, and the Online limits (Custom plan, about 1 call/s, 5-200 e-mails/day, data modules only) | 10-19; API keys 14+, expiry 18+; on 19.0 the module list needs an administrator |
| `odoo_api_catalog` | A model's methods with their parameter names in order, model-level and read-only flags, for JSON-2 and `odoo_execute` (`ids` + `kwargs`). Exact names from Odoo's own per-database catalog (`/doc-bearer`, custom and Studio methods included) with an administrator's API key on 19.0+; otherwise the plugin's built-in table: base names from saas~18.4 (a model's override may rename one), flags only (`parameters: null`) on 10.0 to saas~18.3 | 10-19 |
| `odoo_access_check` | Whether the signed-in user may read, write, create and unlink on a model, record by record with `ids` on 18+, and whether the user may export | 10-19; record level 18+, export group 16+ |
| `odoo_record_documents` | A record's attachments with the main one and an invoice's stored PDF flagged (17+), and one file's content on request (at most 5 MiB). Use it for PDFs on 14+, where reports cannot be rendered over RPC | 10-19 |
| `odoo_import_preview` | Dry run with Odoo's own importer: the row errors and warnings, and `would_import`. Nothing is saved, but sequence numbers can be consumed and automated actions can fire webhooks | 16-19, JSON-RPC or JSON-2 |
| `odoo_import` | Atomic `load()`: every row is saved or none is. An `id` column holds external ids and **updates** the records that already have them | 12-19, JSON-RPC or JSON-2 |

Both import tools take at most 500 rows per call and never run by themselves:
the preview does not import, and the agent asks before `odoo_import`. Odoo's
XML-RPC cannot return the empty values an import result carries, so a session
on XML-RPC refuses them instead of risking a saved import reported as an error.
On Odoo Online, pace bulk work (about 1 call per second, no parallel calls).

### Transports

Odoo 19 deprecates `/xmlrpc` and `/jsonrpc` (every call logs a warning on the
Odoo server), and **Odoo 22 and Odoo Online saas~21.1 remove them**. Their
replacement, **JSON-2** (`/json/2/<model>/<method>`), exists from saas~18.4 and
19.0 and accepts an **API key only**.

With `ODOO_TRANSPORT_PREF=auto` (the default) the server reads the version first
(the web client's own route: no login, nothing in the Odoo log) and then:

- on Odoo 10 to 18 (and saas~18.1-18.3) it uses JSON-RPC, then XML-RPC, as before;
- on saas~18.4 / 19.0+ **with an API key** it uses JSON-2, falling back to JSON-RPC
  and XML-RPC only when a proxy blocks JSON-2;
- with a password, or with `user:pass@` in `ODOO_URL` (whose basic auth takes the
  `Authorization` header JSON-2 needs), it stays on the deprecated endpoints, and on
  19+ `odoo_version` returns a `transport_notice` saying how to switch;
- on saas~21.1 / Odoo 22+ it needs an API key (JSON-2 is the only endpoint left).

`json2` forces JSON-2; `jsonrpc` and `xmlrpc` force that endpoint. None of them
switch transport by themselves. `odoo_version` reports the transport in use.
A call moves to another transport only when that cannot run it twice, and a rate
limit (HTTP 429) never switches transport: reads wait for `Retry-After`, writes
are reported. On JSON-2, `odoo_execute` takes the record ids in `ids` and the
other arguments by name in `kwargs`. Details: [`docs/compat-matrix.md`](docs/compat-matrix.md#rpc-endpoints-and-transports).

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
(json2/jsonrpc/xmlrpc, selected per version and credential) → session (auth + version/edition facts + schema
cache) → compat (resolve model/field/capability) → tools → MCP stdio.

## Scope

This is the **public generic core**: it talks to Odoo and nothing else. Any
localization-, governance- or tenant-specific engines (e.g. country e-invoicing,
approval workflows, backups, document AI) are intentionally **out of scope** and
are not part of this repository.

## Support — Transgenia

[Transgenia](https://transgenia.org) builds and maintains this plugin and provides
**maintenance, support, training and assisted deployment** of Claude + Odoo
(hosting, migrations, integrations, customizations). Official channels only:

- Email: **dev@transgenia.org**
- WhatsApp: **+52 55 8034 0405** — https://wa.me/525580340405

The plugin points you to these channels at the moments they matter (setup
blocked, end of training, deployment); it does not add them to unrelated
answers. It works with any Odoo instance, with or without a support contract.
See also [`SUPPORT.md`](SUPPORT.md).

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
