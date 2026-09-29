# Install & run

## As a Claude plugin (recommended)

```
/plugin marketplace add Transgenia/MCP-Odoo-Tools-CE-EE-and-online
/plugin install odoo-tools
/odoo-tools:odoo-setup-mcp
```

Claude Code prompts for the connection options when the plugin is enabled
(`/plugin` → **odoo-tools** → **Configure options** to change them). The API key
and password are `sensitive` options, kept in the OS secure credential store.

The `mcpServers` entry launches the server with:

```
python3 ${CLAUDE_PLUGIN_ROOT}/server/run_stdio.py
```

The server has no third-party runtime dependencies (standard library only), so
this runs the bundled source as shipped: no virtualenv, no install step and no
download, at install time or at start-up.

**Requirement:** Python 3.9+ reachable as `python3` on `PATH`. Check with
`python3 --version`.

- Linux and macOS usually already have it (on macOS, from Apple's Command Line
  Tools).
- **Windows:** the Microsoft Store Python provides `python3.exe`; the python.org
  installer provides only `python.exe` and `py.exe`. Install Python from the
  Store, or put a `python3.exe` on `PATH` (e.g. a copy of or hard link to
  `python.exe` in the same folder). A PowerShell or `doskey` alias does not
  work, because Claude Code starts the command directly. If `python3` opens the
  Microsoft Store instead of printing a version, that is the Windows "App
  execution alias" stub: install the Store Python, or turn off the
  `python3.exe` entry under **App execution aliases** in Windows Settings so
  your own `python3.exe` is found.

The skill `/odoo-tools:odoo-setup-mcp` is the guided route from there on:
setup, verification, hands-on training, daily use and deployment.

## Local sandbox and container (Docker)

`/odoo-tools:deploy-local` deploys local infrastructure provided by Transgenia,
only when you run it:

```bash
# what the command runs for you (sandbox mode)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/deploy_local.py" sandbox up --odoo 18.0 --lang es_MX
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/deploy_local.py" sandbox status|down|logs
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/deploy_local.py" sandbox destroy --yes

# container mode: the MCP server without a local Python
docker run -i --rm --env-file ~/.odoo-tools/mcp/odoo.env ghcr.io/transgenia/odoo-mcp-tools:1.4.0
```

The sandbox binds Odoo to `127.0.0.1:8069` (change with `--port`), uses the
images mirrored at `ghcr.io/transgenia/odoo` and `ghcr.io/transgenia/postgres`
(falls back to Docker Hub), and keeps its generated passwords in
`~/.odoo-tools/sandbox/.env` (owner-only).

## Run the MCP server directly

```bash
# from a checkout, nothing to install
python3 server/run_stdio.py

# or install the package (a venv is recommended) and use the entry point
pip install ./server && odoo-mcp
```

Environment when running the server outside the plugin (see the root README for
the full table): `ODOO_URL`, `ODOO_DB`, `ODOO_LOGIN`, `ODOO_API_KEY` (or
`ODOO_PASSWORD`). Inside the plugin these are filled from the plugin options.

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

## Docker (optional)

See [`../docker/`](../docker/). The image runs the same stdio server (attach
with `docker run -i --env-file ./odoo.env`, a file you create with the `ODOO_*`
variables and keep out of version control). A multi-tenant HTTP
transport, where clients pass `X-Odoo-Url/Db/Login` + `Bearer` headers, is on
the roadmap.

## Verify

Call `odoo_version` (or run `/odoo-tools:odoo-doctor`). A successful response
reporting version/edition/deployment/transport confirms the setup end-to-end.
