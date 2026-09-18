# Compatibility matrix (Odoo 10-19)

The MCP server resolves model/field names and capabilities per detected version,
edition and deployment. The authoritative, testable source is
[`server/src/odoo_mcp/compat/deltas.py`](../server/src/odoo_mcp/compat/deltas.py);
this page summarizes it.

## Detection

- **Version** — major integer from `common.version()` (`server_version_info[0]`,
  or parsed from `server_version`), clamped to 10-19.
- **Edition** — `+e` suffix in the version string, else a probe of the
  `web_enterprise` module (`ir.module.module`), else `unknown`.
- **Deployment** — `*.odoo.com` host ⇒ `saas`, else `onprem`.

## Model renames and merges

| Modern name | Historical name | Kind | Boundary |
|-------------|-----------------|------|----------|
| `account.move` | `account.invoice` | merge | invoices folded into `account.move` at v13 |
| `account.move.line` | `account.invoice.line` | merge | folded at v13 |
| `stock.package` | `stock.quant.package` | rename | new at v19 (best-effort) |

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
| `product.template` | `uom_po_id` | removed (use `uom_id`) | v17 (best-effort) |
| `res.partner` | `company_type` | removed (use `is_company`) | v19 (best-effort) |

Removed fields are dropped from a query with a `dropped_fields` warning rather
than failing the whole call.

## Capabilities

| Feature | Availability |
|---------|--------------|
| `api_key_auth` | Odoo ≥ 14 (older needs password) |
| `jsonrpc_api_key` | Odoo ≤ 16 only; v17+ rejects API keys on `/jsonrpc` → auto XML-RPC fallback |
| `update_field_translations` | Odoo ≥ 16 (older uses lang-context write) |

## Editions

Enterprise-only models (heuristic list: `documents.document`, `sign.request`,
`account.consolidation.period`, `quality.check`, `helpdesk.ticket`,
`planning.slot`, `appraisal.appraisal`) raise a `CompatError` when the instance
is detected as Community. Runtime module probing is authoritative.

## "Best-effort" boundaries

Some version boundaries (marked above) are approximate and should be confirmed
against a live instance. Because the map is plain data covered by table-driven
tests, correcting a boundary is a one-line edit plus a test row.
