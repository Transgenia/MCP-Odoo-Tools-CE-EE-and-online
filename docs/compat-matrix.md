# Compatibility matrix (Odoo 10-19)

The MCP server resolves model/field names and capabilities per detected version,
edition and deployment. The authoritative, testable source is
[`server/src/odoo_mcp/compat/deltas.py`](../server/src/odoo_mcp/compat/deltas.py);
this page summarizes it.

## Detection

- **Version** — major and minor from `common.version()` (`server_version_info`,
  or parsed from `server_version`), major clamped to 10-19. The minor is 0 on a
  stable series and N on Odoo Online's `saas~<major>.N` lines, which sit between
  two stable series: 18.0 < saas~18.1 < … < saas~18.4 < 19.0.
- **Edition** — `+e` suffix in the version string, else a probe of the
  `web_enterprise` module (`ir.module.module`), else `unknown`.
- **Deployment** — `*.odoo.com` host ⇒ `saas`, else `onprem`.

## Model renames and merges

| Modern name | Historical name | Kind | Boundary |
|-------------|-----------------|------|----------|
| `account.move` | `account.invoice` | merge | invoices folded into `account.move` at v13 |
| `account.move.line` | `account.invoice.line` | merge | folded at v13 |
| `stock.package` | `stock.quant.package` | rename | new at v19 |

For a **rename** (e.g. `stock.package`) you may pass either name and the resolver
returns the one valid on the target version.

> **Accounting is a merge, not a rename.** `account.move` (journal entries) exists
> on **all** versions 10-19. On v10-12 `account.invoice` (invoices) is a **separate
> model** that was folded into `account.move` at v13. The resolver therefore:
>
> - maps `account.invoice` -> `account.move` only on **v13+** (where the invoice
>   model no longer exists), and
> - **never** rewrites `account.move` -> `account.invoice` on older versions
>   (doing so would redirect a journal-entry call to the invoice model).
>
> On v10-12, name the model you actually mean (`account.invoice` for invoices,
> `account.move` for journal entries), especially for writes/deletes.

## Field changes

| Model | Field | Change | Boundary |
|-------|-------|--------|----------|
| `account.move.line` | `analytic_account_id` → `analytic_distribution` | rename | v16 |
| `product.template` | `uom_po_id` | removed (use `uom_id`) | saas~18.1 (Online) and 19.0 |
| `res.partner` | `company_type` | removed (use `is_company`) | saas~19.1 (Online); still in 19.0 |

The two removals were checked against the public Odoo source of every stable
and saas branch from 16.0 to saas-19.4.

Removed fields are dropped from a query with a `dropped_fields` warning rather
than failing the whole call.

## Capabilities

| Feature | Availability |
|---------|--------------|
| `api_key_auth` | Odoo ≥ 14 (older needs password) |
| `update_field_translations` | Odoo ≥ 16 (older uses lang-context write) |

API keys are accepted on `/jsonrpc` and `/xmlrpc/2` alike (both call Odoo's
`dispatch_rpc`, 14-19). The `auto` transport still falls back to XML-RPC when a
proxy blocks or alters `/jsonrpc`.

## Methods

| Method | Change | Use instead |
|--------|--------|-------------|
| `name_get` | deprecated at v17, removed at v18 | read `display_name` (10-19) |

## RPC endpoints

`/xmlrpc`, `/xmlrpc/2` and `/jsonrpc` are deprecated in Odoo 19 and scheduled for
removal in Odoo 22 (they moved to the auto-installed `rpc` module in 19.0).
Odoo's replacement is the JSON-2 API.

## Editions

Enterprise-only models (heuristic list: `documents.document`, `sign.request`,
`account.consolidation.period`, `quality.check`, `helpdesk.ticket`,
`planning.slot`, `appraisal.appraisal`) raise a `CompatError` when the instance
is detected as Community. Runtime module probing is authoritative.

## "Best-effort" boundaries

Boundaries that have not been confirmed against Odoo's source or a live
instance are marked "best-effort". Because the map is plain data covered by
table-driven tests, correcting a boundary is a one-line edit plus a test row.
The sandbox matrix workflow also checks the `res.partner` entries against a
live Odoo Community 10.0-19.0 every week.
