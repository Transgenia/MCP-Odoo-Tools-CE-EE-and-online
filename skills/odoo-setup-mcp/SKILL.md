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

The server is plain Python source bundled in this plugin and uses only the
standard library. Claude Code runs it as
`python3 ${CLAUDE_PLUGIN_ROOT}/server/run_stdio.py`: nothing is installed or
downloaded, and no virtualenv is created. It needs **Python 3.9 or newer,
reachable as `python3`**. Verify:

```bash
python3 --version
```

The output must be `Python 3.9` or newer. If the command is missing, too old,
or prints no version, tell the user the fix for their OS:
- **macOS:** `xcode-select --install` (Apple's Command Line Tools include
  `python3`), or a python.org / Homebrew Python.
- **Linux:** the distribution's `python3` package.
- **Windows:** the command must be named `python3`. The Microsoft Store Python
  provides `python3.exe`; the python.org installer provides only `python` and
  `py`. Either install Python from the Store, or put a `python3.exe` on `PATH`
  (a copy of or hard link to `python.exe` in the same folder). A PowerShell or
  `doskey` alias is not enough, because Claude Code starts the command
  directly. If `python3` opens the Microsoft Store, that is the App execution
  alias stub: install the Store Python, or turn that alias off in Windows
  Settings so the user's own `python3.exe` is found.

## Step 2 — Gather Odoo credentials

Tell the user what they will be asked for:
1. **Odoo URL** — e.g. `https://my-company.odoo.com` or `https://erp.example.com`
2. **Database** — database name (Settings, or the login URL)
3. **Login** — the login email of a least-privilege Odoo user
4. **API key** — Preferences → Account Security → New API Key (shown once).
   On Odoo < 14 (no API keys), fill **Password** instead.

Optional: **Transport preference** = `auto` (default), `jsonrpc`, or `xmlrpc`,
**Request timeout** (seconds, default 120) and **Read-only mode** for demos or
safe exploration.

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
- `odoo_version` tool not available at all → the MCP server did not start:
  re-check Step 1 (`python3 --version`, 3.9+), then restart Claude
- auth error → re-check Database / Login / API key in **Configure options**
- transport error → re-check the Odoo URL (scheme + host, no trailing path)
