# Compatibility matrix (Odoo 10-19)

The MCP server resolves model/field names and capabilities per detected version,
edition and deployment. The authoritative, testable source is
[`server/src/odoo_mcp/compat/deltas.py`](../server/src/odoo_mcp/compat/deltas.py);
this page summarizes it.

## Detection

- **Version** — major and minor from the `common.version()` keys
  (`server_version_info`, or parsed from `server_version`), major clamped to
  10-19 for the tables. The minor is 0 on a stable series and N on Odoo
  Online's `saas~<major>.N` lines, which sit between two stable series:
  18.0 < saas~18.1 < … < saas~18.4 < 19.0. With `ODOO_TRANSPORT_PREF` `auto`
  or `json2` the version is read without signing in and without a deprecated
  endpoint, so it adds no line to the Odoo log: first the web client's own
  `POST /web/webclient/version_info` (10.0 to master), then `GET /json/version`
  (19.0+), and only then the legacy `common.version`. `jsonrpc` and `xmlrpc`
  keep `common.version` first. The transport keeps the **unclamped** series
  (e.g. 20.0, saas~21.1) for its own choice, and caches the payload.
- **Edition** — `+e` suffix in the version string, else a probe of the
  `web_enterprise` module (`ir.module.module`), else `unknown`.
- **Deployment** — `*.odoo.com` host ⇒ `saas`, else `onprem`.
  `odoo_online_profile` also says how sure that is (`deployment_confidence`):
  `version` when the version string is a `saas~` line, which only Odoo Online
  runs (it then reports `saas` even on a custom domain); `host` when only the
  host name decides, since `*.odoo.com` is also used by Odoo.sh and an Online
  database on a stable series behind its own domain looks like `onprem`.

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
`dispatch_rpc`, 14-19), and are the only credential JSON-2 accepts. The `auto`
transport still falls back to XML-RPC when a proxy blocks or alters `/jsonrpc`.

## Methods

| Method | Change | Use instead |
|--------|--------|-------------|
| `name_get` | deprecated at v17, removed at v18 | read `display_name` (10-19) |
| `read_group` (classic) | deprecated in 19.0; **absent on saas~19.1 to saas~19.4**; back in 20.0 with the `_read_group` signature (`domain, groupby, aggregates, having, offset, limit, order`, returning tuples) | `formatted_read_group` (saas~18.4+) |
| `formatted_read_group` | new in saas~18.4 (web module) | |
| `check_access_rights` | deprecated in 19.0, removed from saas~19.1 | `has_access` (18.0+) |

The method entries are data too (`METHOD_DELTAS`, with `resolve_method` and
`method_available` in `compat/resolve.py`). `odoo_read_group` calls
`formatted_read_group` from saas~18.4 on (a clamped 20+ included) and keeps the
classic arguments and output: a date(time) groupby without granularity means
`:month`; `field` takes the field's default aggregator (`fields_get`
attribute `aggregator`), and a field without one is listed in an additive
`dropped_fields`; `lazy` groups by the first groupby only, names the count
`<groupby>_count` and adds `__context`; `__domain` is the call's domain AND the
group's; a date group's value is its label, with `__range` rebuilt from the
group domain; `orderby` becomes `order`.

## RPC endpoints and transports

| Endpoint | Series | Credential | Notes |
|----------|--------|------------|-------|
| `/xmlrpc/2` | 10.0 to 21.0 | password, or API key 14+ | deprecated in 19.0 (moved to the auto-installed `rpc` module); every call logs a WARNING on the Odoo server; removed in **Odoo 22** and **Odoo Online saas~21.1** |
| `/jsonrpc` | 12.0 to 21.0 | password, or API key 14+ | same as `/xmlrpc/2` (both go through `dispatch_rpc`, 14-19) |
| JSON-2 `POST /json/2/<model>/<method>` | **saas~18.4, 19.0+** | **API key only** (`Authorization: bearer`) | named arguments only; `X-Odoo-Database` header; no deprecation log; a JSON error body means Odoo rolled the call back |

`ODOO_TRANSPORT_PREF=auto` (default) decides from the unclamped series S, the
credential (API key or password) and whether `ODOO_URL` carries `user:pass@`
(basic auth for a gateway, which needs the same `Authorization` header as the
JSON-2 key):

| Case | Order | Notes |
|------|-------|-------|
| S < saas~18.4 | JSON-RPC → XML-RPC | as before |
| saas~18.4 ≤ S < saas~21.1, API key, no `user:pass@` | JSON-2 → JSON-RPC → XML-RPC | JSON-2 is pinned after the first sign-in |
| same range, password or `user:pass@` | JSON-RPC → XML-RPC | from 19.0 `odoo_version` returns a `transport_notice` and the server logs it once |
| S ≥ saas~21.1 (Online saas~21.1, Odoo 22), API key | JSON-2 only | no legacy endpoint left |
| S ≥ saas~21.1, password or `user:pass@` | `ConfigError` | set `ODOO_API_KEY`, remove `user:pass@` |

`json2` forces JSON-2 (a password or `user:pass@` is a `ConfigError`, and so is
a server older than saas~18.4; a server that answers but not with JSON-2 gets
"needs saas~18.4 / 19.0 or newer, or a proxy blocks /json/2", and a host that
cannot be reached at all gets "check `ODOO_URL` and that this machine can reach
it"); `jsonrpc` and `xmlrpc` force that endpoint and never switch. On JSON-2 a sign-in is `res.users.context_get` (the key names its
user) plus a read of that user's login, which must be `ODOO_LOGIN`.

Positional arguments are named from a table of the base definitions of every
method the plugin calls (`transport/json2_signatures.py`, keyed by series where
the base names differ: `default_get`, `fields_list` on saas~18.4 and `fields`
on 19.0+, and `read_group`). For other methods `odoo_execute` reads the
signature from `/doc-bearer/<model>.json` (19.0+, admin keys), or asks for
named `kwargs` plus a top-level `ids`.

JSON-2 binds the body to the model's own override, which may use other names:
on saas~18.4 `write(values)` on `res.company`, `product.pricelist` and every
`mail.thread` model, and `res.partner.default_get(default_fields)`; an addon
may do the same on any series (the 19.0 core has no such mismatch). Odoo then
answers HTTP 422 `UnprocessableEntity` with the bind error before running the
method. The transport sends the call again with the signature from
`/doc-bearer`, or, when it named a single argument, with the name Odoo reports
as missing, and remembers it per database, model and method. When neither
works, `auto` sends that one call over JSON-RPC / XML-RPC (JSON-2 stays
pinned) and `json2` asks for named `kwargs`. Names given in `kwargs` are never
changed; the 422 is reported. `odoo_api_catalog` gives exact names only from
`/doc-bearer`; its built-in table gives the base names from saas~18.4 on and no
names (`parameters: null`) on 10.0 to saas~18.3, where `odoo_execute` takes
positional `args` anyway. `@api.readonly` methods run on a read-only cursor on JSON-2,
a replica when the host sets `db_replica_host`, so a read right after a write
may lag there.

A call is retried on the next transport only when that cannot run it twice:
version, sign-in and reads always; writes only when the request never reached
Odoo (connection refused, HTTP 3xx/405/415, an HTML 4xx page). A timeout, an
HTTP 5xx without an Odoo body or a cut reply on a write is reported as "may or
may not have been applied". HTTP 429 never switches transport: reads wait for
`Retry-After` (at most 30 s, 3 tries), writes are reported.

## Odoo Online tools

The six Online tools work on any Odoo 10-19 and degrade per version. Checked in
the Odoo source of every series they use, and live on 18.0 and 19.0 Community
with an administrator and a regular internal user.

| Tool | Odoo calls | Version notes |
|------|------------|---------------|
| `odoo_online_profile` | `res.users.context_get`, `res.users.read`, `res.users.apikeys.search_read` (names, scope and dates; the model has no field with key material), one `ir.module.module.search_read`, `/doc-bearer/res.partner.json` | API keys 14+, `expiration_date` 18+; `totp_enabled` when `auth_totp` is installed; `imported` when `base_import_module` is. On 19.0 `ir.module.module` is readable by administrators only: for other users the module list is `null` and `unavailable` says why |
| `odoo_api_catalog` | `/doc-bearer/<model>.json` (ETag-cached), else the built-in table; `fields_get` checks that the model exists | `/doc-bearer` needs 19.0+ and an administrator's API key (group `api_doc.group_allow_doc`); a regular user gets 403 and the built-in table. `fields_get` is used instead of `ir.model`, which a regular user cannot read on 19.0 (it needs the Access Rights group) |
| `odoo_access_check` | `has_access(operation)` 18+; `check_access_rights(operation, raise_exception=False)` 10-17; `res.users.has_group('base.group_allow_export')` | `has_access` with ids is record level (record rules); `check_access_rights` is gone from saas~19.1; `has_group` is `@api.model` on 16-17 and a record method from 18.0; the export group exists from 16 |
| `odoo_record_documents` | `ir.attachment.search_read` of `res_model`/`res_id`; `read` of `message_main_attachment_id` and `invoice_pdf_report_id` when the model has them; `read(['datas'])` of one attachment | `invoice_pdf_report_id` 17+. The invoice PDF sits in a binary field, so its attachment has `res_field` set and a plain search hides it; the tool reads it by id. Reports cannot be rendered over RPC on 14+ (`_render_qweb_pdf` is private) |
| `odoo_import_preview` | `base_import.import.create`, `execute_import(fields, columns, options, dryrun=True)`, `unlink` | `execute_import` 16+. No header row and `has_headers` off, so Odoo stores no column mapping; server date and number formats. The rolled-back run can still consume sequence numbers and fire webhooks |
| `odoo_import` | `load(fields, data)` | atomic on every version: any error saves nothing and returns `ids: False` |

Both import tools run on JSON-2 or JSON-RPC only. Odoo's XML-RPC marshaller
cannot send `None`, which import results contain (seen on 18.0 with
`execute_import`), so an import that Odoo saved could come back as a fault.
The import calls are therefore never sent or replayed over XML-RPC, and a
session on XML-RPC (Odoo 10-11, or `ODOO_TRANSPORT_PREF=xmlrpc`) refuses them
before any request.

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
