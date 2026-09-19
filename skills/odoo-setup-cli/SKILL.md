---
name: odoo-setup-cli
description: Configure the TypeScript CLI fallback (XML-RPC). Use when you cannot run the MCP server (no uv/Python) or want a lightweight scriptable surface. Odoo 17/18/SaaS tested.
---

# Setup — Odoo CLI (fallback)

The CLI is a lightweight XML-RPC client (Node.js only, no Python). Use it when
the MCP server can't run in your environment, or for scripted batch access.
The MCP server remains the primary, fuller surface.

## Step 1 — Node.js

```bash
node --version   # need 18+
```
If missing: https://nodejs.org/ (LTS), `brew install node`, or `apt install nodejs npm`.

## Step 2 — Locate the bundled CLI

```bash
PLUGIN_CLI="${CLAUDE_PLUGIN_ROOT}/cli"
# or, if the variable is not set in your shell:
PLUGIN_CLI=$(find ~/.claude/plugins/cache -path "*/odoo-tools/cli" -type d 2>/dev/null | head -1)
echo "$PLUGIN_CLI"
```

## Step 3 — Install to a stable location

```bash
CLI_DIR="$HOME/.claude/tools/odoo-cli"
mkdir -p "$CLI_DIR/src/commands"
cp "$PLUGIN_CLI/package.json" "$CLI_DIR/"
cp "$PLUGIN_CLI/package-lock.json" "$CLI_DIR/" 2>/dev/null
cp "$PLUGIN_CLI/tsconfig.json" "$CLI_DIR/"
cp "$PLUGIN_CLI/src/odoo-client.ts" "$CLI_DIR/src/"
cp "$PLUGIN_CLI/src/cli.ts" "$CLI_DIR/src/"
cp "$PLUGIN_CLI/src/commands/"*.ts "$CLI_DIR/src/commands/"
```

## Step 4 — Credentials (.env)

```bash
cat > "$HOME/.claude/tools/odoo-cli/.env" << 'ENVEOF'
ODOO_URL=<url>
ODOO_DB=<db>
ODOO_USER=<login-email>
ODOO_API_KEY=<api-key>
ENVEOF
```

## Step 5 — Build and verify

```bash
cd "$HOME/.claude/tools/odoo-cli" && npm install && npm run build
node dist/cli.js contacts '{"limit":1}'
```

A returned contact confirms the connection.

## Usage

```bash
node ~/.claude/tools/odoo-cli/dist/cli.js invoices '{"state":"posted","limit":20}'
node ~/.claude/tools/odoo-cli/dist/cli.js fields '{"model":"res.partner"}'
```

> Note: the CLI targets modern model names (e.g. `account.move`). Accounting is
> a merge, not a rename: on Odoo ≤ 12 `account.move` (journal entries) and
> `account.invoice` (invoices) coexist, so name explicitly the model you mean.
> For Odoo ≤ 12 instances prefer the MCP server, whose compat layer maps
> `account.invoice` → `account.move` only on v13+ and never rewrites
> `account.move` backwards.
