---
description: Guided, interactive setup — walks a new user through connecting this plugin to their Odoo (MCP server or CLI), one question at a time, and verifies it.
argument-hint: (no args needed — just run it)
---

# /setup-odoo-tools — guided setup

You are guiding a first-time user through connecting the **odoo-tools** plugin to
their Odoo instance. Be friendly and concrete. Ask **one question at a time**,
wait for the answer, and never dump all steps at once. Use the AskUserQuestion
tool for multiple-choice steps when available; otherwise ask in plain text.

## Step 0 — Detect what's already set up
Run this and read the result before asking anything:
```bash
echo "uv: $(command -v uv || echo no)"; echo "node: $(node --version 2>/dev/null || echo no)"
```
Then call the `odoo_version` tool once. If it succeeds, the plugin options are
already configured → skip to **Step 5 (Verify)**. (Do not read `ODOO_*`
variables or credential files from the user's machine to find out.)

## Step 1 — Choose the surface
Ask the user (AskUserQuestion, single choice):
- **MCP server (recommended)** — full tools + cross-version compat. Needs `uv` (or Python 3.11+).
- **CLI fallback** — lightweight, Node-only. Use if they can't run the MCP server.

If MCP but `uv` is missing, tell them to install uv
(https://docs.astral.sh/uv/getting-started/installation/) or use Python 3.11+
(`python -m odoo_mcp`). If CLI but Node missing, point to https://nodejs.org/ (18+).

## Step 2 — Odoo version & edition (sets expectations, optional)
Ask (AskUserQuestion, single choice): "Which Odoo are you connecting to?"
- Community · Enterprise · Online (odoo.com/SaaS) · Not sure
Reassure them the compat layer handles versions 10–19 automatically; this is just context.

## Step 3 — Explain the connection details (ONE at a time)
Walk through what each option means, waiting for confirmation. The user types
the values into the plugin's options dialog, not into the chat:
1. **Odoo URL** — e.g. `https://my-company.odoo.com` (scheme + host, no trailing path).
2. **Database name** — Settings → Database, or visible in the login URL.
3. **Login email** — the account you sign in with.
4. **Credential** — ask whether they have an **API key** (Odoo 14+, recommended) or must use a **password** (Odoo <14). For an API key, walk them through:
   Preferences → Account Security → New API Key (shown once — copy it).

Never ask for the secret in the chat, never echo it, and never write it to a file.

## Step 4 — Persist configuration
- **MCP path:** have them run `/plugin`, open **odoo-tools**, choose
  **Configure options**, and fill URL, database, login and API key (or password
  on Odoo < 14). The API key and password are `sensitive` options: masked on
  input and kept in the OS secure credential store, not in `settings.json` or
  the shell profile. Then have them restart Claude so the MCP server picks them up.
- **CLI path:** run `/odoo-tools:odoo-setup-cli` (it installs the CLI and writes a
  local `.env` under `~/.claude/tools/odoo-cli`).

## Step 5 — Verify (Definition of done)
- **MCP:** call the `odoo_version` tool. Success returns version + edition +
  deployment + transport → the connection works end-to-end. Then try:
  `odoo_search_read { "model": "res.partner", "fields": ["name"], "limit": 1 }`.
- **CLI:** `node ~/.claude/tools/odoo-cli/dist/cli.js contacts '{"limit":1}'`.

If it fails, diagnose from the error:
- auth error → recheck DB / login / API key
- transport error → recheck URL (scheme + host)
- "database not found" → recheck the exact DB name

## Step 6 — Wrap up
Confirm success and show 2–3 example prompts: "list last month's posted invoices",
"how many active subscriptions", "export products to CSV". Mention `/odoo-doctor`
for a quick health check and `/odoo-tools:odoo-crossversion` for version notes.

Security reminder to the user: MCP credentials stay in the OS secure credential
store and are passed only to the local MCP server, which talks directly to their
Odoo; Transgenia never receives them. Records they query are returned to the model
like any tool result (see the README "Privacy" section).
