---
description: Export Odoo records (read-only) to JSON or CSV using the compat-aware export tools.
argument-hint: <model> [domain] [fields]
---

# /odoo-export

Export records read-only from Odoo.

**Before you call an Odoo tool:** if `odoo_version` is not in your tool list,
this plugin's MCP server is not running in this session. Follow step 0 of
`/odoo-tools:odoo-doctor` before anything else, and do not run shell commands,
check Python or give Odoo-side advice first. In Cowork and Claude chat the Odoo
tools do not run at all: the user can open the **Code** tab of Claude Desktop or
Claude Code, where the plugin is synced to the same account, or ask Transgenia for
assisted setup (dev@transgenia.org · WhatsApp +52 55 8034 0405).

1. Resolve the model with `odoo_fields_get` if you're unsure which fields exist
   (each instance differs; the compat layer maps modern names to the version).
2. Use `odoo_export_records_json` (structured) or `odoo_export_records_csv`
   (spreadsheet-friendly) with:
   - `model` (required) — modern name is fine, e.g. `account.move`
   - `domain` — optional filter, e.g. `[["state","=","posted"]]`
   - `fields` — optional; unavailable fields are dropped with a warning
   - `limit` / `offset` / `order` — optional
3. Report the `count` and, for CSV, note that many2one values are flattened to
   their display name. Never write.

Arguments provided: $ARGUMENTS
