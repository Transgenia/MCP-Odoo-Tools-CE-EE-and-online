---
name: odoo-crossversion
description: How the compatibility layer resolves model/field names across Odoo 10-19 so a single tool call works everywhere. Reference when a field is dropped or a model name differs by version.
---

# Cross-version behavior (Odoo 10-19)

The MCP server routes every model/field name through a compatibility layer
before hitting the ORM. You write against the **modern** name; it resolves to
whatever exists on the target version.

## Model name resolution

Accounting is a **merge, not a rename**: `account.move` (journal entries)
exists on all versions 10-19. On v10-12 `account.invoice` is a **separate**
invoice model folded into `account.move` at v13.

| You pass | Odoo ≤ 12 | Odoo ≥ 13 |
|----------|-----------|-----------|
| `account.move` | `account.move` (journal entries — never rewritten) | `account.move` |
| `account.move.line` | `account.move.line` (never rewritten) | `account.move.line` |
| `account.invoice` (historical) | `account.invoice` | → `account.move` |
| `account.invoice.line` (historical) | `account.invoice.line` | → `account.move.line` |

> On v10-12 name the model you actually mean (`account.invoice` for invoices,
> `account.move` for journal entries), especially for writes/deletes.

| You pass | Odoo ≤ 18 | Odoo ≥ 19 |
|----------|-----------|-----------|
| `stock.package` | → `stock.quant.package` | `stock.package` |

Unknown/unchanged models pass through untouched.

## Field resolution

- `account.move.line.analytic_distribution` ↔ `analytic_account_id` (boundary v16).
- Removed fields return a **dropped_fields** warning in the response instead of
  failing the whole call (e.g. `product.template.uom_po_id` from saas~18.1 and
  19.0 → use `uom_id`; `res.partner.company_type` from saas~19.1 → use
  `is_company`; self-hosted 19.0 still has `company_type`).
- Odoo Online runs `saas~<major>.N` lines between two stable series
  (18.0 < saas~18.1 < … < 19.0); `odoo_version` reports the exact line, and the
  resolver uses it, so an Online database can differ from the same major
  on-premise.

## Capabilities

- API keys exist from v14 (older needs a password).
- API keys work on `/jsonrpc` and XML-RPC alike. If a proxy in front of Odoo
  blocks or alters `/jsonrpc`, the `auto` transport falls back to XML-RPC and
  logs one warning; you don't need to do anything.
- `/xmlrpc`, `/xmlrpc/2` and `/jsonrpc` are **deprecated in Odoo 19** and
  scheduled for removal in **Odoo 22** (Odoo's replacement is the JSON-2 API).
  They work on 10-19 today; mention it when the user plans beyond Odoo 21.
- The `name_get` method is gone in v18 (deprecated in v17): read the
  `display_name` field instead, which works on 10-19.
- Translations use the native `update_field_translations` API on v16+, and a
  language-context write on older versions — `odoo_translate_set` picks the path.

## When a call still fails

A `CompatError` carries a human-readable remediation. Boundaries marked
"best-effort" in `server/src/odoo_mcp/compat/deltas.py` (e.g. the stock package
rename) can be confirmed against the live instance and adjusted there — the map
is plain data covered by table-driven tests.
