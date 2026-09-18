---
description: Export Odoo records (read-only) to JSON or CSV using the compat-aware export tools.
argument-hint: <model> [domain] [fields]
---

# /odoo-export

Export records read-only from Odoo.

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
