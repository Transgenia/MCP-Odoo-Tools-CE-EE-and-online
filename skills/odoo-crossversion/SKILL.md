---
name: odoo-crossversion
description: How the compatibility layer resolves model/field names across Odoo 10-19 so a single tool call works everywhere. Reference when a field is dropped or a model name differs by version.
---

# Cross-version behavior (Odoo 10-19)

The MCP server routes every model/field name through a compatibility layer
before hitting the ORM. For **clean renames** you write the modern name and it
resolves to whatever exists on the target version. **Accounting is a merge,
not a rename** (see below): on Odoo 10-12 name explicitly the model you mean.

## Model name resolution

| You pass | Odoo ≤ 12 | Odoo ≥ 13 |
|----------|-----------|-----------|
| `account.move` (journal entries) | `account.move` (unchanged — never rewritten to invoices) | `account.move` |
| `account.move.line` (journal items) | `account.move.line` (unchanged) | `account.move.line` |
| `account.invoice` (historical invoices) | `account.invoice` | → `account.move` (invoices were merged at v13) |

> **Merge rule:** `account.move` (journal entries) already exists on v10-12 as
> a distinct model alongside `account.invoice` (invoices). The resolver maps
> `account.invoice` → `account.move` only on v13+ and **never** rewrites
> `account.move` → `account.invoice` on older versions. For writes/deletes on
> v10-12, verify with `odoo_fields_get` before writing.

| You pass | Odoo ≤ 18 | Odoo ≥ 19 |
|----------|-----------|-----------|
| `stock.package` | → `stock.quant.package` | `stock.package` |

Unknown/unchanged models pass through untouched.

## Field resolution

- `account.move.line.analytic_distribution` ↔ `analytic_account_id` (boundary v16).
- Removed fields return a **dropped_fields** warning in the response instead of
  failing the whole call (e.g. `product.template.uom_po_id` on v17+,
  `res.partner.company_type` on v19+ → use `is_company`).

## Capabilities

- API keys exist from v14 (older needs a password).
- `/jsonrpc` rejects API keys on v17+ — the transport auto-falls back to XML-RPC
  and logs one warning; you don't need to do anything.
- Translations use the native `update_field_translations` API on v16+, and a
  language-context write on older versions — `odoo_translate_set` picks the path.

## When a call still fails

A `CompatError` carries a human-readable remediation. Boundaries marked
"best-effort" in `server/src/odoo_mcp/compat/deltas.py` (e.g. the stock package
rename) can be confirmed against the live instance and adjusted there — the map
is plain data covered by table-driven tests.
