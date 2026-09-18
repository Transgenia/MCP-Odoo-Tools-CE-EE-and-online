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
echo "uv: $(command -v uvx || echo no)"; echo "node: $(node --version 2>/dev/null || echo no)"; \
echo "env: url=${ODOO_URL:-unset} db=${ODOO_DB:-unset} login=${ODOO_LOGIN:-unset} \
key=$([ -n "$ODOO_API_KEY" ] && echo set || echo unset) pass=$([ -n "$ODOO_PASSWORD" ] && echo set || echo unset)"
```
- If `ODOO_URL` + a secret are already set and `uvx` exists → skip to **Step 5 (Verify)**.

## Step 1 — Choose the surface
Ask the user (AskUserQuestion, single choice):
- **MCP server (recommended)** — full tools + cross-version compat. Needs `uv`/`uvx` (or Python 3.11+).
- **CLI fallback** — lightweight, Node-only. Use if they can't run the MCP server.

If MCP but `uvx` is missing, tell them to install uv
(https://docs.astral.sh/uv/getting-started/installation/) or use Python 3.11+
(`python -m odoo_mcp`). If CLI but Node missing, point to https://nodejs.org/ (18+).

## Step 2 — Odoo version & edition (sets expectations, optional)
Ask (AskUserQuestion, single choice): "Which Odoo are you connecting to?"
- Community · Enterprise · Online (odoo.com/SaaS) · Not sure
Reassure them the compat layer handles versions 10–19 automatically; this is just context.

## Step 3 — Collect connection details (ONE at a time)
Ask each, waiting for the answer:
1. **Odoo URL** — e.g. `https://my-company.odoo.com` (scheme + host, no trailing path).
2. **Database name** — Settings → Database, or visible in the login URL.
3. **Login email** — the account you sign in with.
4. **Credential** — ask whether they have an **API key** (Odoo 14+, recommended) or must use a **password** (Odoo <14). For an API key, walk them through:
   Preferences → Account Security → New API Key (shown once — copy it).

Never echo the secret back in plain text. Do not write it to any file the repo tracks.

## Step 4 — Persist configuration
- **MCP path:** help them export the env vars so Claude launches the server with them.
  - macOS/Linux (append to `~/.bashrc` or `~/.zshrc`):
    ```bash
    export ODOO_URL="…"; export ODOO_DB="…"; export ODOO_LOGIN="…"; export ODOO_API_KEY="…"
    ```
  - Windows PowerShell (persist for the user): `setx ODOO_URL "…"` (repeat per var).
  - Then have them restart Claude so the plugin's MCP server picks up the env.
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

Security reminder to the user: credentials stay in their environment; this plugin
never sends them to Anthropic or writes them into the repository.
