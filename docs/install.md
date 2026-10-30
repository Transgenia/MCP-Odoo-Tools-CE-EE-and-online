# Install & run

## As a Claude plugin (recommended)

Inside Claude Code (typed in a session):

```text
/plugin install odoo-tools --marketplace Transgenia/MCP-Odoo-Tools-CE-EE-and-online
/odoo-tools:odoo-setup-mcp
```

Or in a terminal (PowerShell, Terminal or bash), then `/odoo-tools:odoo-setup-mcp`
inside Claude Code:

```bash
claude plugin install odoo-tools --marketplace Transgenia/MCP-Odoo-Tools-CE-EE-and-online --scope user
```

`/plugin` commands go inside Claude Code; `claude plugin` commands go in a
terminal. On Claude Code older than 2.1.275, which has no `--marketplace` flag,
run `/plugin marketplace add Transgenia/MCP-Odoo-Tools-CE-EE-and-online` and then
`/plugin install odoo-tools` instead of the first line.

Install one copy only. The Claude plugin directory can offer an older version (it
publishes a version after Anthropic reviews it), and two copies with the same name
can be active at once: see [Two copies of odoo-tools](../README.md#two-copies-of-odoo-tools).
`run_stdio.py --check-copies` and `--check-options` check the copies and the saved
options; `/odoo-tools:odoo-doctor` runs them.

Claude Code prompts for the connection options when the plugin is enabled
(`/plugin` → **odoo-tools** → **Configure options** to change them). The API key
and password are `sensitive` options, kept in the OS secure credential store.

Two more options set the permission policy (1.5.0), both with defaults:
**Permission profile** (`standard`; `readonly`, `builder` or `full`) and
**Permission policy file** (empty, or an absolute path to a JSON file of
per-model rules). To keep the 1.4 behaviour, set the profile to `full`. See
[`policy.md`](policy.md). The server also writes an audit line per tool call to
the plugin's data folder (`${CLAUDE_PLUGIN_DATA}/audit`, kept 90 days).

These options are a Claude Code feature. Cowork does not prompt for plugin options
and ignores this plugin's MCP server because its connection options have no
default, and Claude chat ignores a plugin's local MCP server, so the Odoo tools are
not available in either (the plugin's skills and
commands still load). See [Where it works](../README.md#where-it-works) and
[If the Odoo tools do not appear](../README.md#if-the-odoo-tools-do-not-appear).

Without the interactive dialog (scripts, remote or headless machines; Claude Code
2.1.285 or later), `claude plugin configure <id> --json` lists the options without
a saved value (the unused credential and the options with defaults stay listed on
a working setup), and `claude plugin configure <id> --values-stdin` saves values
read from stdin as a JSON object of single-line strings; restart Claude Code
afterwards. `<id>` is the full `name@marketplace` id shown
by `claude plugin list` (for example `odoo-tools@synced`). Pipe the JSON from a
protected file or a secret manager; never put the key in the command line.

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
  your own `python3.exe` is found. Without `python3`, `claude mcp list` reports
  the plugin's server as `Failed to connect` with `Connection closed`, and
  nothing names Python. The session-start hooks are shell commands and need Git for Windows (Git Bash);
  without it Claude Code runs them in PowerShell and shows a SessionStart hook
  error (set `CLAUDE_CODE_GIT_BASH_PATH` if Git Bash is installed but not found).
  The MCP server is not affected.

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
docker run -i --rm --env-file ~/.odoo-tools/mcp/odoo.env ghcr.io/transgenia/odoo-mcp-tools:1.6.0
```

The sandbox binds Odoo to `127.0.0.1:8069` (change with `--port`), uses the
images mirrored at `ghcr.io/transgenia/odoo` and `ghcr.io/transgenia/postgres`
(falls back to Docker Hub), and keeps its generated passwords in
`~/.odoo-tools/sandbox/.env` (owner-only). On Odoo 14.0 and newer the same file
holds the API key that Odoo creates for the sandbox's admin user, for the
plugin's **Odoo API key** option.

## Run the MCP server directly

```bash
# from a checkout, nothing to install
python3 server/run_stdio.py

# or install the package (a venv is recommended) and use the entry point
pip install ./server && odoo-mcp
```

Environment when running the server outside the plugin (see the root README for
the full table): `ODOO_URL`, `ODOO_DB`, `ODOO_LOGIN`, `ODOO_API_KEY` (or
`ODOO_PASSWORD`), and optionally `ODOO_POLICY` (default `standard`),
`ODOO_POLICY_FILE`, `ODOO_AUDIT_DIR` (a folder, `stderr` by default, or `off`) and
`ODOO_AUDIT_RETENTION_DAYS` (default 90). Inside the plugin these are filled from
the plugin options.

Check a policy file before you configure it (offline, nothing is sent to Odoo):

```bash
python3 server/run_stdio.py --check-policy ~/.config/odoo-tools/policy.json --explain res.users:write
```

Optional extras:

```bash
pip install -e "./server[cache]"    # TTL schema cache (cachetools)
pip install -e "./server[metrics]"  # Prometheus /metrics
pip install -e "./server[otel]"     # OpenTelemetry OTLP tracing
```

## CLI fallback (optional)

Inside Claude Code:

```text
/odoo-tools:odoo-setup-cli
```
Requires Node.js 18+. Installs the CLI to `~/.claude/tools/odoo-cli`.

## Docker (optional)

See [`../docker/`](../docker/). The image runs the same stdio server (attach
with `docker run -i --env-file ./odoo.env`, a file you create with the `ODOO_*`
variables and keep out of version control). The env file may also set the
permission policy and the audit folder; mount the policy file read-only and the
audit folder writable by the container's user (`mcp`):

```
# in odoo.env
# ODOO_POLICY=standard
# ODOO_POLICY_FILE=/policy/policy.json
# ODOO_AUDIT_DIR=/audit

docker run -i --rm --env-file ./odoo.env \
  -v ~/.config/odoo-tools/policy.json:/policy/policy.json:ro \
  -v ~/.odoo-tools/audit:/audit ghcr.io/transgenia/odoo-mcp-tools:1.6.0
```

Without an audit folder the audit lines go to `docker logs`. A remote HTTP mode, where the
server keeps the Odoo credential and clients authenticate to it, is on the
roadmap and needs its own design.

## Verify

Call `odoo_version` (or run `/odoo-tools:odoo-doctor`). A successful response
reporting version/edition/deployment/transport confirms the setup end-to-end.
