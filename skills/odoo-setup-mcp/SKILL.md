---
name: odoo-setup-mcp
description: Configure the Odoo MCP server (primary surface). Run once, or when odoo_version fails. Sets credentials via environment and verifies the connection across CE/EE/online, Odoo 10-19.
---

# Setup — Odoo MCP server (primary)

This configures the **MCP server** that ships with this plugin. It is the
recommended surface: native tools (`odoo_search`, `odoo_read`, `odoo_create`,
`odoo_export_records_json`, `odoo_version`, ...) with an automatic cross-version
compatibility layer.

## Step 1 — Check the runtime

The server runs via `uvx` (from the `uv` toolchain). Verify:

```bash
uvx --version || echo "install uv: https://docs.astral.sh/uv/getting-started/installation/"
```

`uv` ships a self-contained Python; no separate Python install is required.
(Alternative runtimes: `pipx run` or `python -m odoo_mcp` from the bundled
`server/` directory — see the repo README.)

## Step 2 — Gather Odoo credentials

Ask the user, one by one:
1. **ODOO_URL** — e.g. `https://my-company.odoo.com` or `https://erp.example.com`
2. **ODOO_DB** — database name (Settings → shows it, or the login URL)
3. **ODOO_LOGIN** — the login email
4. **ODOO_API_KEY** — Preferences → Account Security → New API Key (shown once).
   On Odoo < 14 (no API keys), use **ODOO_PASSWORD** instead.

Optional: **ODOO_TRANSPORT_PREF** = `auto` (default), `jsonrpc`, or `xmlrpc`.

## Step 3 — Export the environment

These variables are read by the MCP server declared in `plugin.json`. Set them
in your shell profile (persisted) so Claude launches the server with them:

```bash
# macOS/Linux (~/.bashrc or ~/.zshrc)
export ODOO_URL="https://my-company.odoo.com"
export ODOO_DB="my-company-main"
export ODOO_LOGIN="me@example.com"
export ODOO_API_KEY="xxxxxxxxxxxxxxxx"
```

```powershell
# Windows PowerShell (persist for the user)
setx ODOO_URL "https://my-company.odoo.com"
setx ODOO_DB "my-company-main"
setx ODOO_LOGIN "me@example.com"
setx ODOO_API_KEY "xxxxxxxxxxxxxxxx"
```

Credentials live only in your environment. They are never sent to Anthropic or
written to disk by this plugin.

## Step 4 — Reload the plugin and verify

Restart Claude (or reload the MCP server) so it picks up the environment, then
call the `odoo_version` tool. A successful response reports the version, edition
(community/enterprise), deployment (onprem/saas) and the active transport —
which confirms the connection end-to-end.

If it fails:
- auth error → re-check ODOO_DB / ODOO_LOGIN / ODOO_API_KEY
- transport error → re-check ODOO_URL (scheme + host, no trailing path)
