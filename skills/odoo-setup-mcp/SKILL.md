---
name: odoo-setup-mcp
description: Configure the Odoo MCP server (primary surface). Run once, or when odoo_version fails. Collects credentials as plugin options (secrets in secure storage) and verifies the connection across CE/EE/online, Odoo 10-19.
---

# Setup — Odoo MCP server (primary)

This configures the **MCP server** that ships with this plugin. It is the
recommended surface: native tools (`odoo_search`, `odoo_read`, `odoo_create`,
`odoo_export_records_json`, `odoo_version`, ...) with an automatic cross-version
compatibility layer.

## Step 1 — Check the runtime

The server runs with `uv` from the source bundled in this plugin, pinned by
`server/uv.lock` (`uv run --frozen`), so every install resolves the same
dependency versions. Verify:

```bash
uv --version || echo "install uv: https://docs.astral.sh/uv/getting-started/installation/"
```

`uv` ships a self-contained Python; no separate Python install is required.
The virtualenv lives in the plugin's data directory, not in your project.

## Step 2 — Gather Odoo credentials

Tell the user what they will be asked for:
1. **Odoo URL** — e.g. `https://my-company.odoo.com` or `https://erp.example.com`
2. **Database** — database name (Settings, or the login URL)
3. **Login** — the login email of a least-privilege Odoo user
4. **API key** — Preferences → Account Security → New API Key (shown once).
   On Odoo < 14 (no API keys), fill **Password** instead.

Optional: **Transport preference** = `auto` (default), `jsonrpc`, or `xmlrpc`,
and **Read-only mode** for demos or safe exploration.

## Step 3 — Enter them in the plugin's options

These values are plugin options (`userConfig` in `plugin.json`). Claude Code
prompts for them when the plugin is enabled. To enter or change them later:
run `/plugin`, open **odoo-tools**, choose **Configure options**.

- The API key and password are marked `sensitive`: input is masked and they are
  stored in the operating system's secure credential store, not in
  `settings.json` and not in your shell profile.
- Never ask the user to paste the secret into the chat, and do not export it in
  `~/.bashrc`, `~/.zshrc` or with `setx`.

## Step 4 — Reload the plugin and verify

Restart Claude (or reload the MCP server) so it picks up the options, then
call the `odoo_version` tool. A successful response reports the version, edition
(community/enterprise), deployment (onprem/saas) and the active transport —
which confirms the connection end-to-end.

If it fails:
- auth error → re-check Database / Login / API key in **Configure options**
- transport error → re-check the Odoo URL (scheme + host, no trailing path)
