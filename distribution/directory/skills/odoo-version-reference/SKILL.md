---
name: odoo-version-reference
description: "Short reference notes on selected Odoo changes between versions 10 and 19: the account.invoice merge, a few renamed or removed fields and methods, API key and RPC endpoint changes, and Odoo Online saas lines. It is not a full changelog. Use when the user asks about one of these, or whether a named model, field, method or endpoint exists in a given Odoo version."
---

# Odoo version differences (10 to 19)

These notes are documentation, written from the compatibility map that Transgenia keeps for its separate, full Odoo Tools plugin (not part of this plugin), as of November 2026. Transgenia read the field and method boundaries for Odoo 16.0 up to the Odoo Online line saas~19.4 in Odoo's public source. They are not live checks: this edition cannot look at the user's Odoo, and Odoo changes between releases. A boundary marked (best-effort) is not confirmed. These notes stop at Odoo 19: for Odoo 20.0 or later, say that you have no notes.

## How to use these notes

- Ask the user for the exact version and edition of their Odoo (Community, Enterprise or Odoo Online; for Odoo Online also the saas line, for example saas~18.2) before you answer a question that depends on it.
- Say that the user should confirm anything important in their own instance. If something is not covered here, say so; do not invent a boundary.
- Never ask for credentials. See the credential rule of the `odoo-start-here` skill.

## Models

- Accounting is a merge, not a rename: `account.move` (journal entries) exists on every version from 10 to 19. On Odoo 10 to 12, `account.invoice` is a separate invoice model; it is folded into `account.move` from Odoo 13, and `account.invoice.line` into `account.move.line`. On Odoo 10 to 12, name the model you actually mean, especially for writes and deletes.
- `stock.quant.package` (Odoo 18 and earlier) is `stock.package` from Odoo 19 (best-effort).

## Fields and methods

- `account.move.line`: `analytic_account_id` before Odoo 16 became `analytic_distribution` from Odoo 16 (analytic accounting became distribution-based, so the new field holds a distribution, not a single account).
- `product.template.uom_po_id` is gone from Odoo Online saas~18.1 and from Odoo 19.0: use `uom_id`. Odoo 17.0 and 18.0 still have it.
- `res.partner.company_type` is gone from Odoo Online saas~19.1: use `is_company`. Odoo 19.0 still has `company_type`.
- `name_get` is gone in Odoo 18 (deprecated in 17): read the `display_name` field, which works on Odoo 10 to 19.
- `check_access_rights` is removed from saas~19.1; `has_access` (from Odoo 18.0) replaces it.
- `read_group` is deprecated in Odoo 19.0 and absent on Odoo Online saas~19.1 to saas~19.4; `formatted_read_group` exists from saas~18.4.
- Translations: Odoo 16 and later have a native `update_field_translations` API; older versions write a translation with a language context.

## Odoo Online

- Odoo Online runs `saas~<major>.N` lines between two stable series (18.0 is older than saas~18.1, which is older than 19.0). An Online database can therefore differ from the same major version installed on a company's own server.
- External API access on Odoo Online depends on the plan (the Custom plan, at the time of writing), and API keys can expire from Odoo 18. This is background for a question about Odoo, not a way to diagnose a connection: this edition cannot connect.

## API endpoints and authentication

- API keys exist from Odoo 14. Odoo 10 to 13 have no API keys: external calls use the user's password.
- `/xmlrpc`, `/xmlrpc/2` and `/jsonrpc` are deprecated in Odoo 19. Odoo has announced that it will remove them in Odoo 22 (planned for fall 2028) and in Odoo Online saas~21.1 (planned for winter 2027); these are Odoo's plans as of November 2026 and can change. Their replacement is JSON-2 (`/json/2/<model>/<method>`), available from saas~18.4 and from Odoo 19.0, which accepts an API key only.

## Where to go next

For connecting Claude to the user's Odoo, follow the ways forward of the `odoo-start-here` skill.
