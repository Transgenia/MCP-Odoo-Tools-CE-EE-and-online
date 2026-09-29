# JSON-2 transport, Odoo Online tools, light LSP and TypeSafe gate: design and scope

| | |
|---|---|
| Date | 2026-09-28 |
| Status | Proposed. Fixes the implementation scope of the **next iteration** of `odoo-tools` (after 1.3.0) |
| For | Saurat (VoBo), and the lead who implements it |
| Repo | `Transgenia/MCP-Odoo-Tools-CE-EE-and-online` at `2ae7e5e` (= `main`, 1.3.0 plus `[Unreleased]`) |
| Evidence | Odoo source (`raw.githubusercontent.com/odoo/odoo/<branch>/…`, saas-18.4, 19.0, saas-19.1 to 19.4, 20.0, master), the official `odoo/documentation` sources, live Odoo 18.0 CE (`:8069`) and 19.0 CE (`:8070`) sandboxes |
| Clean room | Other Odoo MCP projects gave **ideas only**, and each one is named with its licence (§2.5). No code from them, and no Odoo source, goes into this repo |
| WebMCP | Not applicable. Nothing here changes transgenia.org, and no WebMCP tool (`contactTransgenia`, `applyToTransgenia`, `getTransgeniaCatalog`, `getTransgeniaLiveCatalog`) is created, modified or retired |
| Business value | The plugin keeps working on Odoo 19+ and on Odoo Online after XML-RPC is removed (Online saas~21.1, winter 2027). It adds Online-specific tools that no surveyed project offers, and it is the entry point to Transgenia's Odoo + Claude services |

## 0. Decisions for this iteration

| # | Area | Decision | This iteration | Needs Saurat |
|---|---|---|---|---|
| 1 | JSON-2 transport | Build it. `auto` prefers JSON-2 on saas~18.4 / 19.0+ when an API key is set, and falls back to JSON-RPC, then XML-RPC | **Implement** (§1) | Go-ahead given ("abordarlos de una vez"). Please confirm the §1.2 policy |
| 2 | `odoo_read_group` | Use `formatted_read_group` from (18, 4) on, and keep the tool's current output shape. Required even without JSON-2 | **Implement** (§1.9) | No |
| 3 | Odoo Online tools | 6 new tools: 4 read, 2 gated write (imports) | **Implement** (§2.2) | No |
| 4 | Online compat fixes | Deployment detection, pacing, auth cool-off, a clear `odoo_report` error | **Implement** (§2.3) | No |
| 5 | Light LSP | Build it, as a separate MIT plugin `odoo-tools-lsp-lite` | **Plan only** (§3). v0.1 comes next iteration | Yes: 4 VoBos (§3.4) |
| 6 | TypeSafe gate | Trusted-scorer design like the landing's. Only the secretless phase 0 goes in now | **Phase 0 files** (§4.4). No Jev workflow yet | Yes: the secret and variable (§4.3) |
| 7 | Out of scope | §6 | | |

Suggested order: 2, then 4 (detection and deltas), then 1, then 4 (pacing), then 3, then 6. Docs and the CHANGELOG come last, then the live runs on sbx18 and sbx19.

---

## 1. JSON-2 transport

### 1.1 What JSON-2 is (verified in source and live on 19.0)

| Item | Fact |
|---|---|
| Where | saas~18.4: `addons/web/controllers/json2.py`. 19.0+: `addons/rpc/controllers/json2.py`, the auto-installed `rpc` module that also hosts the deprecated `/xmlrpc`, `/xmlrpc/2` and `/jsonrpc` |
| Call | `POST /json/2/<model>/<method>`, `Authorization: bearer <API key>`, `X-Odoo-Database: <db>`, `Content-Type: application/json`, and a JSON **object** body `{"ids": […], "context": {…}, <named args>}` |
| Arguments | **Named only.** A key `"args"` is just an unknown keyword (422). Sending `ids` to an `@api.model` method gives 422 |
| Result | A bare JSON value with no envelope. A recordset becomes a list of ids, so `create(dict)` returns `[id]`, where `execute_kw` returns an `int` |
| Auth | API key only (scope NULL or `rpc`, not expired). Passwords are refused. A `user:pass@` URL cannot work, because basic auth and the bearer key both need the `Authorization` header |
| Transaction | One per call. A JSON error body means Odoo rolled back |
| Server log | No deprecation warning. Every `/xmlrpc` or `/jsonrpc` call on 19.0 logs one WARNING in the customer's Odoo log (verified: 1 per call. The web version probes below log nothing) |
| Removal of the legacy endpoints | Odoo 22 on-premise (fall 2028); **Odoo Online saas~21.1 (winter 2027)** (odoo/documentation 20.0 `external_rpc_api.rst`) |

### 1.2 Selection policy

`ODOO_TRANSPORT_PREF` accepts `auto` (default), **`json2` (new)**, `jsonrpc` or `xmlrpc`. The `auto` policy decides from three inputs:
- **S**, the **unclamped** series `(major, minor)` (`MAX_VERSION = 19` clamps `EnvFacts`, so the transport must keep the raw parse);
- **K**, the credential kind: `api_key` when `ODOO_API_KEY` is set, else `password`;
- **U**, whether `ODOO_URL` contains `user:pass@`.

"Legacy" below means JSON-RPC then XML-RPC, which is today's order. The legacy endpoints exist while S < (21, 1): this single bound matches both on-premise 21.0 (still has them) and Online saas~21.1 (does not).

| Case | `auto` order | Notes |
|---|---|---|
| S < (18, 4) | legacy | unchanged |
| (18, 4) ≤ S < (21, 1), K = api_key, not U | **json2 → jsonrpc → xmlrpc** | pin json2 after the first successful sign-in |
| (18, 4) ≤ S < (21, 1), K = password or U | legacy | deprecation notice when S ≥ (19, 0) (§1.6) |
| S ≥ (21, 1), K = api_key, not U | json2 only | no legacy endpoints left |
| S ≥ (21, 1), otherwise | `ConfigError` | remediation: set `ODOO_API_KEY`, remove `user:pass@` |

| Explicit preference | Behaviour |
|---|---|
| `json2` | JSON-2 only, and never switches. At session start, K = password or U gives `ConfigError`. `Json2Unavailable` gives an error saying JSON-2 needs saas~18.4 / 19.0+ or is blocked by a proxy, and suggests `auto`; `Json2Unreachable` (connect, DNS, TLS, bad URL) says to check `ODOO_URL` and reachability instead; `Json2SignatureMismatch` asks for named `kwargs` (§1.3) |
| `jsonrpc` / `xmlrpc` | unchanged, plus the §1.6 notice on 19+ and `ConfigError` from (21, 1) |

**Version detection, which costs no login and leaves no server log line.** In `auto` and `json2` mode:
1. `POST /web/webclient/version_info` with a JSON-RPC envelope. This is the web client's own `auth='none'` route, 10.0 to master, and not a deprecated endpoint. It returns the `common.version()` keys. Re-checked today on 18.0 and 19.0: it adds no deprecation line to the 19.0 log, while one `/jsonrpc common.version` adds one.
2. If that fails, `GET /json/version` (19.0+).
3. If that fails too, legacy `common.version`, as today.

`jsonrpc` and `xmlrpc` keep `common.version`. The payload is cached in the transport, so `session.facts()` makes no second call.

**Sign-in (whoami).**
1. `POST /json/2/res.users/context_get` `{}` returns `uid`.
2. `POST /json/2/res.users/read {"ids":[uid],"fields":["login"]}` must match `ODOO_LOGIN` (case-insensitive). Otherwise `AuthError`: "the API key belongs to another user".

This keeps today's guarantee that `ODOO_LOGIN` is the user who owns the credential. It is two calls, once per session.

**Credential kind.** `Credentials` gets `secret_kind: "api_key" | "password"`, set by `ConnectionManager.default()` from `Settings`. It is not part of the fingerprint and never appears in `repr`. The multi-tenant `from_headers` path is dormant (§6).

### 1.3 Positional to named mapping (every method the plugin calls)

The mapping is a data table, `transport/json2_signatures.py`. M marks an `@api.model` method, which must not receive `ids`. For a non-M method, `args[0]` becomes `ids`. `kwargs["context"]` always moves to the top-level `"context"` key.

| Model.method | Called by | M | `execute_kw` today | JSON-2 body | Series notes |
|---|---|---|---|---|---|
| `ir.module.module.search_count` | `session.module_installed` | M | `[domain]` | `{domain}` | |
| `<m>.fields_get` | `session.fields_get`, tools | M | `[]`, `{attributes}` | `{attributes}` | |
| `<m>.read` | `session.name_get`, `odoo_read`, `odoo_translate_get`, JSON-2 sign-in (login check), new tools | | `[ids]`, `{fields}` | `{ids, fields}` | missing ids are skipped |
| `<m>.search` | `odoo_search` | M | `[domain]`, `{offset, limit, order}` | `{domain, offset, limit, order}` | |
| `<m>.search_count` | `odoo_search_count` | M | `[domain]` | `{domain}` | |
| `<m>.search_read` | `odoo_search_read`, exports, `odoo_list_models`, `odoo_module_info`, new tools | M | `[domain]`, `{fields, offset, limit, order}` | same names | |
| `<m>.create` | `odoo_create`, studio (3 sites), `odoo_import_preview` | M | `[vals]` | `{vals_list}`, and unwrap `[id]` → `id` when `vals` was a dict | |
| `<m>.write` | `odoo_write` | | `[ids, vals]` | `{ids, vals}` | |
| `<m>.unlink` | `odoo_unlink`, studio, import cleanup | | `[ids]` | `{ids}` | |
| `<m>.read_group` (classic) | `odoo_read_group` up to (18, 3); `odoo_execute` | M | `[domain, fields, groupby]`, `{offset, limit, orderby, lazy}` | ≤ 19.0: same names | **absent** saas~19.1 to 19.4. **20.0 and master**: `(domain, groupby, aggregates, having, offset, limit, order)`, returning tuples |
| `<m>.formatted_read_group` | `odoo_read_group` from (18, 4) | M | `[domain]`, `{groupby, aggregates, offset, limit, order}` | same names | saas~18.4+ |
| `ir.model.search` | studio `_model_id` | M | `[domain]`, `{limit}` | `{domain, limit}` | |
| `<m>.update_field_translations` | `odoo_translate_set` 16+ | | `[[id], field, {lang: v}]` | `{ids, field_name, translations}` | |
| `ir.actions.report._render_qweb_pdf` | `odoo_report` | private | | refused on every transport | §2.3 |
| `res.users.context_get` | JSON-2 sign-in, `odoo_online_profile` | M | `[]` | `{}` | |
| `res.users.apikeys.search_read` | `odoo_online_profile` | M | `[domain]`, `{fields}` | `{domain, fields}` | `expiration_date` 18+ |
| `<m>.has_access` | `odoo_access_check` 18+ | | `[ids, operation]` (empty ids = model level) | `{ids, operation}` | |
| `<m>.check_access_rights` | `odoo_access_check` on 10-17 | M | `[operation]`, `{raise_exception: false}` | same names | deprecated 19.0, **removed saas~19.1** |
| `res.users.has_group` | `odoo_access_check` 16+ | 16-17 M; 18+ record | `[group]` / `[[uid], group]` | `{ids: [uid], group_ext_id}` | |
| `base_import.import.execute_import` | `odoo_import_preview` 16+ | | `[[id], fields, columns, options]`, `{dryrun: true}` | `{ids, fields, columns, options, dryrun}` | |
| `<m>.load` | `odoo_import` | M | `[fields, data]` | `{fields, data}` | |
| `<m>.default_get` | `odoo_execute` | M | `[fields]` | saas~18.4: `{fields_list}`; 19.0+: `{fields}` | the only base name that differs between JSON-2 series; `res.partner` overrides it as `default_fields` on saas~18.4 (below) |
| `<m>.name_search` | `odoo_execute` | M | `[name, domain, operator, limit]` | `{name, domain, operator, limit}` | |
| `<m>.copy` / `name_create` / `web_read` / `web_search_read` / `get_field_translations` / `export_data` | `odoo_execute` | per source | positional | named per source | |
| anything else | `odoo_execute` | | caller's `args` | see below | |

**`odoo_execute` outside the table.** With no positional `args`, `kwargs` goes through as-is. With positional args, the transport:
1. introspects `/doc-bearer/<model>.json` (19.0+, admin keys only), cached per (url, db, model) with its `ETag`;
2. otherwise raises `CompatError`: "pass named arguments in `kwargs` and record ids in `ids`".

**Overrides with other names (found in review).** The table holds the base definitions' names, but JSON-2 calls `inspect.signature(func).bind(records, **body)` on the model's top override. On saas~18.4 `write(self, values)` (`res.company`, `product.pricelist`, `mail.thread` models) and `res.partner.default_get(self, default_fields)` differ from the base `vals` / `fields_list`; any addon may do the same on any series (a scan of the 146 models of the 19.0 sandbox found no mismatch in the core). A failed bind is HTTP 422 `werkzeug.exceptions.UnprocessableEntity` whose message is the `TypeError` text (`missing a required argument: 'values'`, `got an unexpected keyword argument 'x'`, ...), raised **before** the method runs. The transport maps exactly that (422 + that name + a bind message) to `Json2SignatureMismatch(Json2Unavailable)`; other 422s stay `OdooFault`. When the plugin named the positional args itself it sends the call once more with the `/doc-bearer` signature, or, if it named a single argument, with the name Odoo reports as missing, and remembers the result per (db, model, method). If it cannot correct them, `auto` sends that call over JSON-RPC / XML-RPC while they exist (no pin: JSON-2 stays in use), and `json2` raises the mismatch with "pass them by name in kwargs". Names the caller gave in `kwargs` are never rewritten or replayed: the 422 becomes an `OdooFault` that points at `odoo_api_catalog`.

`odoo_execute` gains an **optional top-level `ids`** argument, an additive change to its schema. Legacy transports prepend it to `args`; JSON-2 sends it as `"ids"`. The same call then works on every transport. The description gains "(write operation)" and explains both forms.

### 1.4 Error mapping (JSON-2 replies to the existing error classes)

| Reply | Meaning | Raised as | Replay allowed |
|---|---|---|---|
| 200 JSON | success | result (`create(dict)` unwrapped) | |
| 401 JSON `Invalid apikey` | bad, expired or wrong-scope key | `AuthError` ("create a new API key; keys expire from 18.0") | never |
| 401 JSON `User not authenticated…` although the header was sent | a proxy dropped `Authorization` | `Json2Unavailable` + warning | yes (`auto` only) |
| 422 `werkzeug.exceptions.UnprocessableEntity` whose message is an `inspect.Signature.bind` error | the argument names do not match the model's override; the method never ran | `Json2SignatureMismatch(Json2Unavailable)`; corrected and resent once, or sent over legacy in `auto` (§1.3) | yes (never ran) |
| 400/403/404/409/422/500 with an Odoo body (`name` + `message` + `arguments`/`debug`) | Odoo ran the call and rolled back | `OdooFault("<name>: <message>")`, **`debug` (server traceback) stripped** | never |
| 404 HTML "nodb" page | `ODOO_DB` is not served on this host (dbfilter) | `ConfigError` | never |
| 3xx, 405, 415, other HTML 4xx | never reached a JSON-2 handler | `Json2Unavailable(JsonRpcUnavailable)` | yes |
| connect, DNS or TLS error, bad URL | nothing was sent to Odoo | `Json2Unreachable(Json2Unavailable)`: with `json2` the hint is "check `ODOO_URL` and reachability", not the version/proxy one | yes |
| 429 (any transport) | rate limited upstream | new `RateLimited(TransportError)` | reads only, after `Retry-After` on the same transport, no pin |
| 5xx without an Odoo body, timeout after send, cut reply, 2xx not JSON | outcome unknown | `TransportError` | version, sign-in and reads only |
| model or method name fails `^[a-z0-9_.]+$` / `^[A-Za-z][A-Za-z0-9_]*$` | refused locally before sending | `CompatError` | |

Local name validation matters: urllib raises `InvalidURL` for a space, which is an `HTTPException`. Without the check it would read as an uncertain outcome.

### 1.5 Replay and no-duplicate-write guarantees (same as `FallbackTransport` today)

| Operation | `*Unavailable` (never ran) | `TransportError` (unknown) | `RateLimited` | `OdooFault` / `AuthError` / `ConfigError` |
|---|---|---|---|---|
| version, sign-in | next transport | next transport | wait, retry the same transport (≤ 3 tries, ≤ 30 s each) | raise |
| read (`READ_METHODS`) | next transport | next transport | wait, retry the same | raise |
| any other method (write) | next transport | raise "may or may not have been applied in Odoo; check before retrying" | raise "refused (HTTP 429); retry later" | raise |

- `READ_METHODS` gains `formatted_read_group`, `web_read_group`, `context_get`, `has_access`, `has_groups` and `get_field_translations`.
- After one transport fails and another answers, the one that answered is pinned for the session, with one warning.
- An explicit preference never switches.
- An `OdooFault` is never replayed. That includes XML-RPC "cannot marshal None" faults, which can follow a committed write.
- Fix in passing: today an HTTP 429 on `/jsonrpc` is a `JsonRpcUnavailable`, so it pins XML-RPC and replays. It becomes `RateLimited` on every transport.
- `odoo_version` keeps reading `transport.active`. The values become `json2`, `jsonrpc`, `xmlrpc`, or `jsonrpc(auto)` before a sign-in.
- Readonly mode is unchanged: `check_readonly` runs before any transport call.
- Documented caveat: JSON-2 sends `@api.readonly` methods to a read-only cursor, which is a replica when the host sets `db_replica_host`. A read right after a write may lag, and the client cannot force the primary.

### 1.6 Deprecation messaging

| When | Message (server log once per session, plus the additive field `transport_notice` in `odoo_version`, `/odoo-doctor` and `odoo_online_profile`) |
|---|---|
| S ≥ (19, 0), legacy active, K = password | "Odoo 19 deprecates /xmlrpc and /jsonrpc; Odoo 22 (Odoo Online saas~21.1) removes them, and each call logs a deprecation warning on your Odoo server. Create an API key and set ODOO_API_KEY to switch to JSON-2." |
| S ≥ (19, 0), legacy active because of U | the same, plus "basic auth in ODOO_URL uses the Authorization header that JSON-2 needs; move the gateway credentials elsewhere" |
| S ≥ (19, 0), legacy forced by `jsonrpc` / `xmlrpc` | the same, plus "set ODOO_TRANSPORT_PREF=auto or json2" |
| S ≥ (21, 1), JSON-2 not possible | `ConfigError` with the same remediation |

### 1.7 Code changes

| File | Change |
|---|---|
| `transport/json2.py` (new) | `Json2Transport` (the `Transport` protocol: `version`, `authenticate`, `execute_kw`), `Json2Unavailable`, `api_doc(model)` for `/doc-bearer`. Stdlib `urllib`, no cookies, no `Accept-Language`, no redirects (`_NoRedirect`), gzip as in `jsonrpc.py` |
| `transport/json2_signatures.py` (new) | the §1.3 table, keyed by series where names differ |
| `transport/fallback.py` | kinds `json2`/`jsonrpc`/`xmlrpc`; the §1.2 policy; `_pin(kind)`; series and version cache; `READ_METHODS`; notice; `api_doc` delegation; pacing hook (§2.3) |
| `transport/jsonrpc.py`, `xmlrpc.py` | 429 → `RateLimited` |
| `config.py` | `TRANSPORT_CHOICES += ("json2",)`; `ODOO_RATE_LIMIT`, `ODOO_DEPLOYMENT` (§2.3) |
| `session.py`, `tenancy.py` | `Credentials.secret_kind`; auth cool-off (§2.3) |
| `tools/meta.py` | `odoo_version`: additive `transport_notice`, `deployment_confidence` |
| `telemetry.py` | `TRANSPORT_LABELS += {"json2"}`; `KNOWN_TOOLS` += the 6 new tools |
| `.claude-plugin/plugin.json` | `odoo_transport_pref` description "auto (default), json2, jsonrpc or xmlrpc"; optional `odoo_rate_limit` and `odoo_deployment` |
| Docs | README env table, `server/README.md`, `docs/compat-matrix.md` (RPC endpoints, method deltas, detection), `docs/architecture.md`, skills `odoo-connect`, `odoo-crossversion`, `odoo-mcp-tools`, command `odoo-doctor`, `docs/packaging.md` (22 → 28 tools), `docs/third-party-ideas.md`, CHANGELOG `[Unreleased]` |

The scratch prototype (about 250 lines) passed a parity run on 19.0: 20 of 25 tool results were identical to XML-RPC, and all 5 differences were expected. It is a starting point for the lead, not repo code.

### 1.8 Tests (every behaviour change)

Unit tests use canned HTTP replies on a local `HTTPServer`, like `test_transports_stdlib.py`.
1. Body mapping per method and series, table-driven: `default_get` on saas~18.4 vs 19.0, the three `read_group` variants, `ids` for M vs non-M, context hoisting, the `odoo_execute` `ids` argument on every transport.
2. `create` unwrap: a dict vs a list.
3. Every row of §1.4, including `debug` stripping and the two 401 texts.
4. The `auto` order for each (S, K, U) combination, including the (21, 1) `ConfigError` and a clamped 20.0 target.
5. The replay rules of §1.5, including "a write is not replayed after a timeout" and "429 does not pin".
6. The version probe order, and zero `/jsonrpc` calls on a 19.0 target in `auto`.
7. The sign-in login mismatch.
8. The notice is emitted exactly once.
9. Name validation.

Live tests (opt-in `live` marker):
- the tool-handler parity run on sbx19 (JSON-2 vs XML-RPC);
- sbx18 in `auto` stays on legacy with no notice;
- sbx19 with a password-only config gives the notice.

Adding a JSON-2 smoke run to `sandbox-matrix.yml` needs keys minted and masked in CI, so it comes next iteration (§6).

### 1.9 `odoo_read_group` routing (independent of the transport)

From (18, 4) on, including a clamped 20+, the tool calls `formatted_read_group`. The tool name, its arguments and the classic output shape stay the same. The tool contract wins over fidelity.

| Classic input or output | Adapter |
|---|---|
| `fields: ["stage_id", "amount:sum"]` | `aggregates: ["amount:sum", "__count"]` (the groupby fields drop out) |
| `fields: ["amount"]` (no operator) | the operator comes from `fields_get(attributes=["aggregator"])`; without an aggregator the field is dropped and reported in an additive `dropped_fields` |
| `lazy=True` (default) | `groupby[:1]`, `__count` renamed `<g0>_count`, `__context: {"group_by": groupby[1:]}` |
| `lazy=False` | all groupbys, `__count` |
| key `amount:sum` | renamed back to `amount` |
| `__extra_domain` | `__domain = domain + extra` (concatenating two valid domains is their AND) |
| `orderby` | `order` (a bare aggregated field becomes `field:agg`) |
| date `field:month` value `[value, label]` | the label as the value; `__range` rebuilt from `__extra_domain` when both bounds are present, else omitted |

`compat/deltas.py` gets method deltas: `read_group` → `formatted_read_group` from (18, 4), `check_access_rights` removed from (19, 1), `has_access` since 18.

---

## 2. Odoo Online tools

### 2.1 Online constraints that shape the tools

| Constraint | Consequence |
|---|---|
| No custom Python and no Apps Store modules, only data modules. Every Apps Store "MCP server" module is unusable there | A client-side server such as ours is the only option, which is a selling point |
| External API only on Custom plans | a documented hint; the error on other plans is undocumented |
| In practice an API key is the credential (odoo.com logins, 2FA). Keys expire from 18.0, and a non-admin group gets a 1-day maximum by default | `odoo_online_profile` shows the expiry |
| AUP: about 1 call/s with no parallel calls; forum reports of HTTP 429 (search snippets only, page not fetched) | pacing in the transport (§2.3) |
| saas lines every 2-3 months. Online currently runs 17.0, 18.0, 19.0 and saas~19.2 to 19.4 | `read_group` is gone on saas~19.1 to 19.4 (§1.9); `check_access_rights` is gone from saas~19.1 |
| RPC cannot render PDFs on 14-20 (`_render_qweb_pdf` is private; `/report/pdf` needs a web session) | `odoo_record_documents` reads the stored PDFs |
| Imports are the sanctioned bulk path ("Odoo provides batch APIs for imports") | `odoo_import_preview` + `odoo_import` |

### 2.2 The six new tools

Shared rules for all six:
- stdlib only; the same behaviour over XML-RPC, JSON-RPC and JSON-2, unless a row says otherwise;
- write tools have `read_only=False`, say "(write operation)" and "refused in read-only mode (ODOO_READONLY)" in their description, and are therefore blocked before touching Odoo;
- nothing chains or runs by itself.

"Verified here" means checked against the CE sandboxes during implementation. The research already checked the methods live on 18.0 and 19.0.

| Tool | Args | R/W | Odoo methods | Versions | Verified here | Online-only, not testable here |
|---|---|---|---|---|---|---|
| `odoo_online_profile` | none | read | cached version; `res.users.context_get`; `res.users.read([uid], [login, company_id, company_ids, totp_enabled*])`; `res.users.apikeys.search_read([["user_id","=",uid]], [name, scope, create_date, expiration_date*])` (**never** key material); `ir.module.module.search_read` of installed applications, and of `imported=True`* modules; `web_studio` installed. (\* only when `fields_get` shows the field) | 10-19, degrading per version (API keys 14+, expiry 18+) | 18.0, 19.0 | the saas-line label (unit tests with canned payloads), Custom-plan refusal, the real 1-day expiry on Online groups, imported data modules |
| `odoo_api_catalog` | `model` (req), `method` (optional substring filter) | read | `GET /doc-bearer/<model>.json` (bearer, `ETag` cache); otherwise the plugin's built-in signature table (§1.3): the base definitions' names from saas~18.4 on (the note says an override may rename one), and `parameters: null` on 10.0 to saas~18.3, whose names differ (`name_search(args)`, classic `web_read_group`, `default_get`/`write` overrides) and were not verified per series; `name_get` listed up to 17.0. Returns method names, ordered parameter names and model/readonly flags, capped at 100, with `source` | `/doc-bearer` 19.0+ with an admin (`api_doc.group_allow_doc`) key; built-in table on every version | 19.0 (admin 200, non-admin 403 → built-in), 18.0 (built-in) | `/doc-bearer` on saas~19.x (source says identical; `bearer_scope='rpc'` from saas~19.4) |
| `odoo_access_check` | `model` (req), `operations` (subset of read/write/create/unlink, default all), `ids` (optional, record level on 18+) | read | `has_access(operation)` 18+; `check_access_rights(operation, raise_exception=False)` on 10-17; `res.users.has_group("base.group_allow_export")` 16+ (`export_allowed`) | 10-19 (record level 18+; export flag 16+) | 18.0, 19.0, admin and a non-admin | the least-privilege bot users recommended for Online |
| `odoo_record_documents` | `model` (req), `res_id` (req), `attachment_id` (opt), `include_content` (bool, default false), `max_bytes` (default 1 MiB, hard cap 5 MiB), `limit` (default 50) | read | `ir.attachment.search_read([res_model, res_id], [name, mimetype, file_size, create_date])`; content only for `attachment_id` **within that record**, via `read([id], ["datas"])` when `file_size ≤ max_bytes`; flags `message_main_attachment_id` and `account.move.invoice_pdf_report_id` (17+) when those fields exist | 10-19 (the invoice flag 17+) | 18.0, 19.0 | Online documents; the portal PDF path is out of scope (§6) |
| `odoo_import_preview` | `model` (req), `fields` (req, ≤ 100), `rows` (req, arrays of strings, ≤ 500) | **write** (dry run) | builds a CSV (stdlib `csv`); `base_import.import.create({res_model, file, file_type: "text/csv", file_name})`; `execute_import(fields, columns, options, dryrun=True)`; best-effort `unlink` of the temporary record. Returns row messages and `would_import: n`, never the rolled-back ids | 16-19; **JSON-RPC or JSON-2 only** (the dry-run result contains `None`, which XML-RPC cannot marshal; seen live on 18.0) | 18.0 (JSON-RPC), 19.0 (JSON-2) | behaviour under Online pacing and 429 |
| `odoo_import` | `model` (req), `fields` (req, ≤ 100), `rows` (req, ≤ 500 per call) | **write** | `load(fields, rows)`: atomic, so any error writes nothing and returns `ids: False` plus messages. An `id` column upserts by external id, which **updates existing records**; the description says so | 10-19 by source, **JSON-RPC or JSON-2 only** (a result with `None` over XML-RPC could report failure after a commit); live on 18.0, 19.0 | 18.0, 19.0 (success and error paths) | batch pacing under the AUP |

Outputs, in brief:
- `odoo_online_profile`: series and line (stable or saas), deployment and confidence, active transport, `json2_available`, `doc_bearer`, `transport_notice`, the legacy-RPC removal dates (on-premise Odoo 22, Online saas~21.1), user and companies, API-key names and expiry, installed applications and imported data modules, and static Online hints (Custom plan, pacing, the 5-200 e-mails/day quota, data modules only).
- `odoo_api_catalog`: `{model, source: "doc-bearer" | "builtin", methods: [{name, parameters (a list, or null from the built-in table before saas~18.4), model_level, readonly}], truncated, note}`. Fields stay with `odoo_fields_get`.

Implementation notes:
- The preview must pass neutral `options` (Odoo's default formats), so the dry run checks exactly the values `load` will receive. The lead confirms the minimal `options` keys for 16-19 from `base_import` source.
- The dry run can fire side effects that are not transactional (webhook server actions) and consumes sequence numbers. The description says so.
- On a session pinned to XML-RPC, both import tools raise `CompatError`: "needs JSON-RPC or JSON-2".

### 2.3 Online compat fixes (not new tools)

| Fix | Behaviour | Test |
|---|---|---|
| Deployment detection | `saas` with confidence `version` when the version string is `saas~`, **including custom domains** (today reported as `onprem`). `*.odoo.com` with a stable version stays `saas` with confidence `host`, because it may also be Odoo.sh (production `<name>.odoo.com`, staging `*.dev.odoo.com`). Override: `ODOO_DEPLOYMENT=saas\|onprem` (confidence `override`). The value set stays `onprem\|saas\|unknown`, so telemetry and skills keep working. `odoo.sh` as a separate value waits for RFC-SAAS (§5) | table-driven |
| Pacing | `ODOO_RATE_LIMIT`: `auto` (default: 1 request/s and one call in flight when the deployment is `saas`, off otherwise), `0` (off), or a number of requests per second. Serialised per session. Exports on Online get slower (5,000 rows at 500 per page is about 10 s) | fake clock |
| 429 / 503 | `Retry-After` honoured (seconds or HTTP date, capped at 30 s, default 10 s) for version, sign-in and reads only; never switches transport (§1.5) | canned replies |
| Auth cool-off | After an `AuthError` the session fails fast for 60 s without calling Odoo. Odoo locks a login for 60 s after 5 failures, and an agent loop would otherwise keep it locked | fake clock |
| `odoo_report` | On 14+ it raises `CompatError` **before** calling Odoo: "Odoo 14+ cannot render reports over RPC (private method); use `odoo_record_documents` for stored PDFs". 10-13 is unchanged. Retiring, aliasing or supporting 10-13 is Saurat's decision (§6) | unit |
| `odoo_execute` | optional `ids`; "(write operation)" in the description (§1.3) | unit |

### 2.4 Kept out of this iteration's tools, and why

| Candidate | Reason |
|---|---|
| `odoo_chatter` / `odoo_post_note`, `odoo_schedule_activity` / `odoo_complete_activity` | generic rather than Online-specific; next candidates (a note posts with `mail.mt_note` by default because of the Online e-mail quota) |
| `odoo_online_databases` / `odoo_online_audit_logs` (www.odoo.com JSON-2) | needs a new `ODOO_COM_API_KEY`; www.odoo.com is unreachable from here; premium candidate |
| Portal PDF fetch, `odoo_share_link` | a share link writes a public `access_token`; opt-in only, later |
| **Never:** data-module upload, minting API keys through MCP, web-session login, db-manager tools, e-mail sending, parallel or background polling against Online | largest blast radius or AUP abuse |

### 2.5 Sources of ideas (ideas only, no code)

| Idea | Project (licence) |
|---|---|
| JSON-2 on 19+ and automatic transport choice | erpipe-org/mcp-odoo (MIT); Vauxoo/mcp.odoo (MIT) |
| `formatted_read_group` on 19+ | erpipe-org/mcp-odoo `aggregate_records` (MIT) |
| Profile, health and capabilities report | erpipe-org/mcp-odoo (MIT); nicolasramos/odooclaw-mcp `odoo_get_capabilities` (MIT); oconsole/odoo-mcp-server `odoo_doctor` (MIT); ivnvxd/mcp-server-odoo `get_current_context` (MPL-2.0) |
| API index from `/doc-bearer` | AlanOgic/odoo-mcp-19 `odoo://api-index` (MIT) |
| Access diagnosis | erpipe-org/mcp-odoo `diagnose_access` (MIT); edubolivar/odoo-mcp-server (MIT); parth-unjiya/odoo-mcp-gateway `debug_access` (MIT) |
| Size-capped attachment reads | erpipe-org/mcp-odoo `read_attachment` (MIT); ivnvxd/mcp-server-odoo (MPL-2.0) |
| `load()` imports and external-id upsert | pantalytics/odoo-mcp-pro `import_records` (Elastic-2.0); Vauxoo/mcp.odoo (MIT); infovpcs/odoo18_mcp_project (MIT) |
| Rate limiting and read-only backoff | erpipe-org/mcp-odoo (MIT); parth-unjiya/odoo-mcp-gateway (MIT); bmya/claude-odoo-api (MIT per its README; no licence file) |

The AGPL/GPL projects (rosenvladimirov/odoo-claude-mcp, rachmataditiya/odoo-rust-mcp, hamzatrq/odoo-forge, altinkaya-opensource/odoo-mcp, AlanOgic/mcp-odoo-adv) and projects whose licence file and manifest conflict (vzeman, mah007, elewa-git) were read for their READMEs only. Nothing from them is used. Odoo source (LGPL-3) was used for facts, never copied.

---

## 3. Light LSP (`odoo-tools-lsp-lite`)

### 3.1 Recommendation

**Build it, starting next iteration, as a minimal v0.1.** This iteration only records the plan below. It is a free, zero-setup checker: no network, no credentials, no Odoo index. It brings developers to the public plugin, and from there to the premium server and Transgenia's migration services.

### 3.2 Shape

| Item | Plan |
|---|---|
| Placement | a **separate** plugin at `packages/odoo-lsp-lite/`, a second entry in the public marketplace `transgenia-odoo-tools`. It is not inside `odoo-tools`, because Claude Code gives each extension to the first registered server and premium users keep `odoo-tools` for the MCP. A scratch manifest passed `claude plugin validate --strict` |
| Code | new MIT code, stdlib only, Python 3.9+, about 2.8k lines plus about 3k lines of tests. It never opens premium source |
| File claims ("hybrid") | LSP for **`.xml` and `.csv`** (no official plugin claims them). **`.py`: a PostToolUse hook** after each Claude Edit/Write (`__manifest__.py` in v0.1, Python rules in v0.2), so `pyright-lsp` keeps `.py`. **`.js`: not claimed**; it stays with `typescript-lsp` |
| Rules v0.1 (15, all `error`, `verified-in-source`, file-local, 0 FP in the premium's triaged runs) | XML/CSV: `xml.view.attrs-states-removed`, `xml.view.tree-renamed-list`, `xml.action.view-mode-tree`, `xml.form.oe-chatter-removed`, `xml.kanban.legacy-card-template-19`, `xml.search.group-expand-string-19`, `xml.data.act-window-report-tags-removed`, `xml.data.group-ids-rename-19`, `xml.data.ir-cron-fields`, `csv.access-file-structure`. Manifest (hook): `MAN-LITERAL-EVAL`, `MAN-LICENSE-INVALID`, `MAN-VERSION-INVALID`, `MAN-AUTO-INSTALL-NOT-DEPENDENCY`, `sem.manifest-file-missing`. Plus `syntax.xml` and `env.version-unknown` |
| v0.2 (+5 Python rules through the hook) / v0.3 | `PY-OPENERP-NAMESPACE-REMOVED`, `PY-EXCEPTIONS-LEGACY-REMOVED`, `PY-API-DECORATOR-REMOVED`, `PY-USER-HAS-GROUPS-REMOVED`, `PY-NAME-GET-OBSOLETE` / 4 Odoo Online data-module rules (premium catalog first), a PyPI package, and a cloud recipe |
| Version model | `(major, minor)` points with saas minors from day one (a small RFC-SAAS pilot). Unknown version: only version-free rules run. A target newer than a rule's `verified_through` suppresses it with one notice |
| Upgrade contract | Same rule ids, severities, windows, `<message> Fix: <suggestion>` format (≤ 10 per file) and `.odoo-tools-lsp.json` as premium. **Premium findings ⊇ lite findings**, enforced by premium CI running the lite's public case corpus |
| Coexistence | Lite and premium must not be enabled together. v1: the docs say so, and the lite reads `enabledPlugins` (read-only) to silence itself and log the disable command. v2: an optional handoff that needs a premium wiring change |
| Stays premium | cross-file `sem.*`, navigation, fixers, live mode, table-driven rules, JS/SCSS/QWeb rules, SARIF |
| Licence | pure MIT: no EULA acceptance, no licence check, no telemetry. Official channels appear only in the README and skill, never in diagnostics |

### 3.3 Effort and release gate

About 15 person-days for v0.1, 4.5 for v0.2 and 3.5 for v0.3. Maintenance adds about 20% to the premium's per-release work.

Release gate for v0.1:
- 0 FP on OCA sale-workflow, server-tools and web 16-19, and on core 16-19, each at its own series;
- hand-triaged cross-series samples;
- rules re-verified on the 20.0 and saas~19.4 source;
- `claude plugin validate --strict` passes;
- Saurat's WSL load check shows "Loaded 1 LSP server(s) from plugin: odoo-tools-lsp-lite".

### 3.4 VoBo needed before v0.1

1. Publish the 15 (later 20) catalog entries under MIT: id, title, severity, windows, message, suggestion, evidence.
2. The separate plugin plus the new PostToolUse diagnostics-hook pattern.
3. The premium ⊇ lite contract and the mutual-exclusion plan.
4. RFC-SAAS for premium, so premium is never less precise than the lite on Odoo Online.

**This iteration, public repo only:** correct `packages/odoo-lsp/README.md:6`. Plugin language servers do not start in cloud sessions, so the check runs "from a terminal session or in CI". The same claim in the premium README and DESIGN is fixed in that repo (§6).

---

## 4. TypeSafe (Jev) review for the MCP repos

### 4.1 State today

| Repo | State |
|---|---|
| landing-transgenia | The Jev review fails on `main`: it pins `cooksafe==0.1.2` from `pypi.typesafe.ai`, which does not resolve. The fix `d821992` (cooksafe **0.2.0** from public PyPI) is on `claude/transgenia-plugin-warnings-nerztd`, not on `main` (re-checked today). `pull_request_target` and scheduled runs use `main`'s workflow file, so the fix PR's own Jev check fails; that is expected. After merging, dispatch `aeo-jev-review` with `candidate_ref=main`. Follow-ups: `typesafe-sdk` 0.7.0 → **0.7.2** (0.7.1 stops the key leaking into connection-error messages), hash-pinned requirements, a symlink guard in the extractor |
| MCP public / premium | no TypeSafe wiring |

### 4.2 Proposal (the landing's trusted-scorer pattern, adapted)

| Item | Public MCP repo | Premium repo |
|---|---|---|
| Trigger | `pull_request_target` + dispatch; the scorer and baseline come from `main`, the PR is read as data only (sparse checkout, `persist-credentials: false`, symlinks refused) | `pull_request` + dispatch; skip Dependabot runs; fork secrets **off** |
| What is scored | the 22 (then 28) tool descriptions and schemas from a committed `docs/mcp-catalog.json`; the MCP `instructions`; the 12 skill/command/agent descriptions; README passages (gating), other docs (report-only) | only licensee-facing text that already ships: README, `lsp/README.md`, skill, command, and the `title`/`message`/`suggestion` of the 109 rules. Never DESIGN, source or contract docs |
| Questions | doc citability rubric + `overclaims_affiliation` guardrail; tool rubric; **tool routing** and **skill routing** (`Choice`, canary + sealed holdout) | per-rule diagnostic rubric; cross-plugin skill routing |
| Policy | repository variable `TYPESAFE_JEV_MODE` = `off` / `advisory` (default when unset: warn and pass) / `blocking` | same |
| Cost | about $0.06 per full run at the landing's cited $0.042 per M input tokens (unverified); PR runs re-score only changed items | about $0.004 per full run |
| Model pin | `jev-1.13.0`, resolved model checked | same |

### 4.3 What Saurat configures (phase 1, next iteration)

1. GitHub → the MCP repo → Settings → Secrets and variables → Actions:
   - secret **`TYPESAFE_API_KEY`**: a separate key per repo, or one org secret scoped to landing + MCP + premium;
   - variable **`TYPESAFE_JEV_MODE=advisory`**, switched to `blocking` after 2-3 weeks.
2. The same in `odoo-tools-premium`, with "Send secrets to workflows from fork pull requests" off.
3. `CODEOWNERS`: `@Saurat` on `/.github/workflows/` and `/.github/typesafe/`.
4. After the workflow merges: dispatch with `update_baseline=true`, review the baseline artifact, and commit it.
5. Premium only: VoBo to send licensee-facing text to TypeSafe, after reading TypeSafe's retention, training and DPA terms (docs.typesafe.ai was unreachable from here).

### 4.4 Files: now vs later

**Decision: no Jev workflow in this iteration.** A workflow skipped behind the variable would be harmless, but `gate.py` does not exist yet, there is no baseline without the secret, and a new `pull_request_target` workflow on a public repo deserves its own owner-reviewed PR. **Phase 0 goes in now**, because it needs no secret and runs in the existing `ci.yml` pytest job, so it cannot break CI when the secret is absent:

| Now (phase 0) | Content |
|---|---|
| `scripts/dump_mcp_catalog.py` | stdlib, Python 3.9. Writes or `--check`s `docs/mcp-catalog.json` from `McpServer.list_tools()` + `INSTRUCTIONS`, in-process, no credentials |
| `docs/mcp-catalog.json` | the committed tool catalog: public documentation, and later the only input the secret-bearing job reads |
| `server/tests/test_mcp_catalog.py` | the snapshot is current; every `read_only=False` tool says "(write operation)" and mentions read-only mode (today `odoo_execute` misses the first, and all 7 miss the second; fixed in this iteration); scored paths contain only the official channels (dev@transgenia.org, +52 55 8034 0405, wa.me/525580340405) |

| Later (phase 1+) | |
|---|---|
| `.github/workflows/typesafe-review.yml`, `typesafe-canary.yml`, `.github/typesafe/{gate.py, extract_candidates.py, rubrics.py, requirements-typesafe.txt, data/*}`, `.github/CODEOWNERS`, "no tool removed or renamed vs `main`" check | drafts exist in scratch (actionlint-clean, SDK-validated); they land after §4.3 |

---

## 5. Answers to Saurat's questions (recommendations)

| Question | Recommendation |
|---|---|
| Default for live mode (premium LSP) | `auto` is the right target. Ship `off` until the premium's host allowlist lands (live only for hosts matching `ODOO_URL` or `live.allowedHosts`), then switch to `auto`. `auto` without the allowlist would let a workspace config send the user's key to any host |
| A catalog built from Odoo CE | Not in the MIT repo (LGPL-derived tables). The lite ships none. For premium it is a premium decision |
| Does the plugin claim `.py`/`.js`? | The hybrid of §3.2: `.xml`/`.csv` through the LSP, `.py` through a hook (pyright keeps working), `.js` left alone. Premium keeps its claims, but its docs should recommend a project-scope install in Odoo repos |
| saas version model (RFC-SAAS) | **Approve.** Use `(major, minor)` points everywhere (the MCP already does). `saas` is certain only from a `saas~` version or an override. Rule windows use exact saas bounds where verified in source. On unverified saas targets, suppress version-bound findings and write a proposal instead of fixing, which is the fixer rule you quoted. Add 20.0 when it is verified |
| `run_claude_headless.py --all` from WSL | `.hushlogin` is only Ubuntu's login banner. In a WSL terminal (not a cloud session): `npm i -g @anthropic-ai/claude-code && claude` (sign in once), `cd ~ && git clone git@github.com:Transgenia/odoo-tools-premium.git && cd odoo-tools-premium`, then `python3 lsp/tests/usability/run_claude_headless.py --load-check --allow-existing-auth` and `… --all --allow-existing-auth`. Results go to `lsp/tests/usability/out/` (exit 0 = pass). It uses real `claude -p` runs, so it consumes usage. Keep the clone under `~`, not under `/mnt/c` |
| Distribution | The public marketplace offers `odoo-tools` (and later the lite). Premium access is on request only, through dev@transgenia.org or WhatsApp +52 55 8034 0405 (https://wa.me/525580340405). The change is made in the premium repo |
| EULA | A separate deliverable (September 2026, free and premium editions). Constraint: the free-edition terms may cover warranty, support, trademarks and privacy, but cannot restrict MIT-licensed code |
| `name_get` on 18+ and "1.1.0 reported while running 1.3.0" | **Done and merged**: PR #22 (`d3fad94`), on `main` at `2ae7e5e`, under `[Unreleased]`. They ship with the next release tag |

---

## 6. Explicitly out of scope (this iteration)

- JSON-2 for the multi-tenant HTTP mode. It is dormant: `ConnectionManager.from_headers` has no caller. If it is ever wired, its session cache key must include a hash of the secret, because today a request with a known url/db/login would reuse another tenant's session.
- Odoo 20.0 and saas~20.x in the compat model. `MAX_VERSION` stays 19, and the clamp keeps the routing right. A 20.0 sandbox also needs `deploy_local.py` to stop using the RPC db service, which 20.0 removed.
- The `odoo_report` product decision (retire, alias to `odoo_record_documents`, or support 10-13 through `render_qweb_pdf`). Only the pre-call `CompatError` on 14+ is in scope.
- Chatter and activity tools, the portal PDF and share links, the odoo.com database and audit-log tools, `odoo_set_default` / `odoo_get_view` / onchange preview, the `discuss.channel` rename delta.
- `odoo.sh` as a separate deployment value, and the telemetry-schema change it implies (after RFC-SAAS).
- The JSON-2 smoke run in `sandbox-matrix.yml`, which needs API keys minted and masked in CI.
- Implementing the light LSP; any premium-repo change (RFC-SAAS adoption, cloud wording in the premium README and DESIGN, lite-exclusion docs, the live-mode default, the CE catalog, distribution, porting GUIDO's premium tools).
- The TypeSafe Jev workflows and scorer (phase 1+), the premium TypeSafe review, and the landing fixes (they live in that repo).
- The EULA text.
- n8n: in this session its MCP servers needed authorization or failed to connect. Nothing here depends on them.

## 7. Open questions

| Question | Blocks |
|---|---|
| Does Odoo Online or Odoo.sh set `db_replica_host` (JSON-2 reads lagging right after writes)? | documentation only |
| What does an Online database on a non-Custom plan return to API calls? (third parties report 403) | a better `AuthError` hint |
| The AUP wording ("1 call/s, no parallel calls") and the 429 reports were seen only in search snippets | the pacing default |
| Does Odoo 22 keep `/web/webclient/version_info` and the `rpc` module? | both probes are kept |
| saas~18.4 was checked from source only (no public image) | live verification |
| TypeSafe data terms, price, rate limits, and one key per repo or per org | §4.3 |
| Pulling `ghcr.io/transgenia/odoo:19.0` got HTTP 403 on the blob download through this environment's proxy (the sandbox fell back to Docker Hub). Probably proxy policy, not the now-public registry | CI mirrors |
