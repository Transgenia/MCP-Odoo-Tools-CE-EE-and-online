# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Six Odoo Online tools** (`tools/online.py`, 28 tools in total). They work on
  any Odoo 10-19, over JSON-2, JSON-RPC and XML-RPC unless noted, and degrade
  per version:
  - `odoo_online_profile` (read): the series and line (`19.0`, `saas~19.2`),
    deployment with `deployment_confidence` (a `saas~` version proves Odoo
    Online, also on a custom domain; `*.odoo.com` alone may be Odoo.sh), the
    transport, `json2_available`, `doc_bearer`, `transport_notice`, when
    `/xmlrpc` and `/jsonrpc` disappear (Odoo 22; Odoo Online saas~21.1), the
    user and companies, 2FA, the user's API keys with `expires_in_hours` (names
    and dates only, never key material) and a hint when one expires within
    48 h, installed applications, imported data modules, Studio, and the Online
    limits (Custom plan, about 1 call/s, 5-200 e-mails/day, data modules only).
  - `odoo_api_catalog` (read): a model's methods with ordered parameter names
    and model-level/read-only flags, from Odoo's `/doc-bearer` on 19.0+ with an
    administrator's API key (ETag-cached, this model's exact names), else from
    the plugin's built-in table, filtered by series: the base definitions'
    names from saas~18.4 on (a model's override may rename a parameter, which
    the note says), and on 10.0 to saas~18.3 the flags only, with
    `parameters: null`, because names differ there (`name_search(args)`, the
    classic `web_read_group`, `default_get`/`write` overrides); `name_get` is
    listed up to 17.0. At most 100.
  - `odoo_access_check` (read): read/write/create/unlink for the signed-in user
    (`has_access` on 18+, record level with `ids`; `check_access_rights` on
    10-17) and `export_allowed` (`base.group_allow_export`, 16+).
  - `odoo_record_documents` (read): a record's attachments, its main attachment
    and an invoice's stored PDF (17+), which a plain attachment search hides;
    one file's content on request, only for an attachment of that record, up to
    `max_bytes` (default 1 MiB, at most 5 MiB). The way to get PDFs on 14+,
    where reports cannot be rendered over RPC.
  - `odoo_import_preview` (write, dry run; 16-19): Odoo's own importer with
    `dryrun=True`; returns the row errors and warnings and `would_import`,
    never the rolled-back ids, and removes its temporary wizard.
  - `odoo_import` (write): atomic `load()`; an `id` column upserts by external
    id. Both import tools take at most 500 rows, are refused in read-only mode,
    never run by themselves, and run on JSON-2 or JSON-RPC only (see below).
- `session.execute(..., transports=(...))` and `FallbackTransport.execute_kw(...,
  transports=...)`: a call limited to those transports is never sent or replayed
  over another one, and a `CompatError` says so when none is left. The import
  tools use it, so an import is never replayed over XML-RPC, whose marshaller
  cannot return the `None` values an import result carries (a saved import
  could otherwise be reported as a fault).
- `OdooSession.api_doc(model)`: `/doc-bearer` for tools, keeping the secret
  inside the session.
- **JSON-2 transport** (`transport/json2.py`): Odoo's new external API,
  `POST /json/2/<model>/<method>`, on saas~18.4 and 19.0+. It sends the API key
  as `Authorization: bearer`, the database as `X-Odoo-Database` and named
  arguments only (no cookies, no `Accept-Language`, no redirects). Positional
  arguments are named from a table of the base definitions of every method the
  plugin calls (`transport/json2_signatures.py`, keyed by series where the base
  names differ: `default_get`, `read_group`); other methods use
  `/doc-bearer/<model>.json` (19.0+, admin keys, cached with its `ETag`) or ask
  for named arguments. A model's override may use other names (saas~18.4:
  `write(values)` on `res.company`, `product.pricelist` and `mail.thread`
  models, `res.partner.default_get(default_fields)`; any addon on any series):
  Odoo then answers HTTP 422 from its `signature.bind` check before running the
  method (`Json2SignatureMismatch`), and the transport sends the call again with
  the signature from `/doc-bearer` or, when one argument was named, the name
  Odoo reports as missing, and remembers it per (database, model, method). When
  it cannot, `auto` sends that one call over JSON-RPC/XML-RPC (JSON-2 stays
  pinned) and `json2` asks for named `kwargs`. Names the caller gave in
  `kwargs` are never changed: the 422 is reported with a pointer to
  `odoo_api_catalog`.
  `create` with one dict still returns an id. Model and method names are checked
  before sending. The sign-in is `res.users.context_get` plus a read of the key
  owner's login, which must be `ODOO_LOGIN`.
- `ODOO_TRANSPORT_PREF=json2`, and a new `auto` policy based on the target's
  unclamped series, the credential kind and `user:pass@` in `ODOO_URL`:
  JSON-2 → JSON-RPC → XML-RPC on saas~18.4 / 19.0+ with an API key (JSON-2 is
  pinned after the first sign-in), JSON-RPC → XML-RPC as before elsewhere, and
  JSON-2 only from saas~21.1 (Odoo Online saas~21.1 and Odoo 22 remove the
  legacy endpoints; a password there is a `ConfigError` that says what to set).
  With `json2`, a server that does not answer JSON-2 gets "needs saas~18.4 /
  19.0 or newer, or a proxy blocks /json/2"; a host that cannot be reached at
  all (connection refused, DNS, TLS: `Json2Unreachable`) gets "check ODOO_URL
  and that this machine can reach it" instead.
- The version is detected without signing in and without a deprecated endpoint
  (`/web/webclient/version_info`, then `GET /json/version`, then
  `common.version`), so it leaves no warning in the Odoo 19 log, and it is
  fetched once per session.
- **Deprecation notice**: when the deprecated `/xmlrpc` or `/jsonrpc` is in use
  on Odoo 19+, the server logs one warning per session and `odoo_version` returns
  an additive `transport_notice` with the fix (create an API key, move gateway
  basic auth out of `ODOO_URL`, or set the transport back to `auto`).
  `/odoo-doctor` shows it.
- `odoo_execute` takes an optional top-level `ids` (the records of a record
  method): JSON-2 sends it as `ids`, the legacy transports as the first
  positional argument, so the same call works on every transport.
- `Credentials.secret_kind` (`api_key` or `password`), set from the settings;
  it is not part of the session fingerprint or of `repr()`.
- `compat/deltas.py` records method deltas (`METHOD_DELTAS`, with
  `resolve_method` and `method_available`): `formatted_read_group` from
  saas~18.4, classic `read_group` absent from saas~19.1, `check_access_rights`
  removed from saas~19.1, `has_access` from 18.0.
- An opt-in live test (`-m live`, `tests/test_json2_live.py`) compares the core
  read tools over JSON-2 and XML-RPC on a 19.0 sandbox (`odoo_version`,
  `odoo_fields_get`, `odoo_search`, `odoo_search_count`, `odoo_search_read`,
  `odoo_read`, `odoo_read_group`, `odoo_export_records_csv`, `odoo_list_models`,
  `odoo_module_info`, `odoo_translate_get` and two `odoo_execute` reads), checks a
  create/write/unlink round trip over JSON-2 against XML-RPC and Odoo's real
  signature-mismatch 422, and checks the transport choice on 18.0. Not compared:
  `odoo_report`, `odoo_export_records_json`, `odoo_connections`,
  `odoo_telemetry_preview` and the Online tools.
- `packages/`: an index of the packages related to odoo-tools, and a README for
  odoo-tools-lsp, Transgenia's language server for Odoo addons (proprietary, private
  preview; documentation only, no source in this repository).
- **Sandbox for Odoo Community 10.0 to 15.0** (was 16.0-19.0), for testing and
  migrations. Each series gets a PostgreSQL major it supports (10 for 10.0/11.0,
  12 for 12.0/13.0, 13 for 14.0/15.0, 16 for 16.0+); series up to 15.0 run as
  linux/amd64 (their official images are amd64-only; Docker Desktop emulates
  them, Docker Engine on ARM Linux needs binfmt/QEMU, which the script explains).
  The script warns that 10.0-16.0 no longer receive fixes from Odoo S.A. (it
  maintains the three latest series: 17.0, 18.0, 19.0).
- **Sandbox matrix workflow** (`sandbox-matrix.yml`): starts every series from
  10.0 to 19.0 with `deploy_local.py` and checks it through the plugin's own MCP
  server (`scripts/sandbox_smoke.py`: `odoo_version` + `odoo_search_read`). Runs
  on changes to the sandbox or the server, weekly, and on demand. The smoke test
  also checks the field entries of the cross-version table against the live
  instance, for every model it has.
- The image mirror also copies `odoo:10.0`-`15.0` and `postgres:10`, `12`, `13`.
- **Odoo Online series.** Version detection keeps the minor of a `saas~N.M`
  line (e.g. saas~18.1), which sits between two stable series
  (18.0 < saas~18.1 < … < 19.0). Field removals can now start on a saas line.

### Changed
- **`odoo_read_group` uses `formatted_read_group` from saas~18.4 on** (19.0
  deprecates the classic `read_group`, and Odoo Online saas~19.1 to saas~19.4
  do not have it), on every transport. The tool keeps its arguments and its
  classic output: the `<groupby>_count` / `__count` keys, `__domain`,
  `__context` for lazy grouping, date labels with `__range`, and `orderby`. A
  field without a default aggregator is listed in an additive `dropped_fields`
  instead of being silently ignored.
- `odoo_execute` says "(write operation)" and that read-only mode refuses it,
  and explains the `ids` + `kwargs` form.
- `READ_METHODS` (calls that may be retried on another transport) gains
  `formatted_read_group`, `web_read_group`, `context_get`, `has_access`,
  `has_groups` and `get_field_translations`.
- The MCP `instructions` list the two import tools among the write tools and
  point Odoo Online users to `odoo_online_profile`; the read-only refusal
  suggests read tools by name. Telemetry's `KNOWN_TOOLS` gains the six tools.
- Docs: a tool table in the README, Odoo Online routes in the guided route
  (`odoo-setup-mcp`: API keys on Online, verify, training exercise 8, daily
  use, deployment), the `odoo-mcp-tools` index skill, the `odoo` agent,
  `/odoo-doctor` (calls `odoo_online_profile`), `SECURITY.md` and
  `docs/compat-matrix.md` (an Odoo Online tools section).

### Fixed
- `docs/telemetry-schema.json` rejected payloads counting `odoo_telemetry_preview`
  or `odoo_read_group`, which the server already counts; its tool pattern now
  equals `KNOWN_TOOLS`, and a test keeps them equal.
- The `odoo` agent listed three tools twice.
- **HTTP 429 on `/jsonrpc` switched the session to XML-RPC** and replayed the
  call. A 429 is now `RateLimited` on every transport: reads wait for
  `Retry-After` (at most 30 s, 3 tries) and retry the same transport, writes are
  reported ("retry later"), and the transport is never switched.
- The sandbox talks to Odoo over XML-RPC (`/xmlrpc/2/common`, `/xmlrpc/2/db`)
  instead of `/jsonrpc`, which does not exist before Odoo 12.0.
- **`product.template.uom_po_id` was dropped from reads and exports on Odoo 17
  and 18**, where the field exists. It is gone only from saas~18.1 (Odoo
  Online) and 19.0.
- **`res.partner.company_type` was dropped on self-hosted Odoo 19.0**, where
  the field exists. It is gone only from saas~19.1 (Odoo Online). Both
  boundaries were checked against the public Odoo source of every stable and
  saas branch from 16.0 to saas-19.4, and `uom_po_id` on a live Odoo 18.0.
- `OdooSession.name_get` failed on Odoo 18+, where the `name_get` method no
  longer exists; it now reads `display_name`, which works on 10-19.
- The server reported the version of any older `odoo-mcp-tools` installed in
  the same Python instead of its own (seen as 1.1.0 while running 1.3.0).
  `odoo_mcp.__version__` is now the single runtime version and the release
  check keeps it equal to the manifests.
- **`odoo_version` reported success with a wrong API key or password** (edition
  "unknown" on Community; always on Enterprise, whose `+e` version string skips
  the module probe). The guided route and `/odoo-doctor` use it as the
  connection check, so a broken connection read as "already connected". It now
  signs in first, and the edition probe no longer swallows `AuthError`.
- `Credentials.secret` is left out of `repr()`, so a traceback, log line or
  debugger cannot show the API key or password.
- Docs, skill and agent no longer claim that `/jsonrpc` rejects API keys on
  Odoo 17+: Odoo handles both endpoints with the same `dispatch_rpc` (14-19)
  and a live Odoo 18.0 accepts an API key on both. The `auto` transport keeps
  its XML-RPC fallback for proxies that block or alter `/jsonrpc`. One place
  still says it: the verbatim telemetry consent statement in `/odoo-doctor`
  ("Odoo 17+ `/jsonrpc` API-key refusal handling"), left unchanged on purpose
  because a change to the consent wording needs the maintainers' review; the
  correction is pending that review.

### Notes
- Odoo 19 deprecates `/xmlrpc`, `/xmlrpc/2` and `/jsonrpc` and schedules their
  removal for Odoo 22 (they now live in the auto-installed `rpc` module); Odoo
  Online removes them in saas~21.1. With an API key the plugin now uses JSON-2
  there; a password keeps working on the legacy endpoints up to Odoo 21, with
  the notice above. The compat matrix and the cross-version skill say so.
- JSON-2 sends `@api.readonly` methods to a read-only cursor, which is a
  replica when the Odoo host sets `db_replica_host`: a read right after a write
  may lag there, and a client cannot force the primary.
- saas~18.4 was checked against the Odoo source only (no public image).

## [1.3.0] - 2026-09-27

Plug and play: one guided route, local infrastructure provided by Transgenia,
and the first published Release and package.

### Added
- **Guided route `/odoo-tools:odoo-setup-mcp` (start here).** Detects what is
  already set up, then walks the user through five phases: setup, verification,
  hands-on training (7 exercises, read-only first, writes only on a sandbox or
  test database), daily use (map of commands, skills and agents) and deployment
  to a team or production (least privilege, read-only by default, pilot,
  backups, updates). `/setup-odoo-tools` now opens the same route.
- **`/odoo-tools:deploy-local`** — local infrastructure, only when the user runs
  it and confirms (Docker required):
  - *Sandbox*: PostgreSQL 16 + Odoo **Community** 16.0, 17.0, 18.0 or 19.0 bound to
    `127.0.0.1`, with a database (demo data optional) ready for the plugin.
    `scripts/deploy_local.py` (standard library only) generates the passwords
    locally into `~/.odoo-tools/sandbox/.env` (owner-only), never prints them,
    and offers `status`, `down`, `logs` and `destroy --yes`. Transgenia cannot
    provide Odoo Enterprise or Odoo Online instances (Enterprise is licensed by
    Odoo S.A., Online is its SaaS); the plugin connects to the user's own.
  - *Container*: the MCP server as `ghcr.io/transgenia/odoo-mcp-tools`, for
    machines without Python 3.9+, connected to an existing Odoo.
- **Images served by Transgenia.** The release publishes the MCP server image to
  GHCR (`X.Y.Z`, `X.Y`, `latest`; amd64 + arm64). `mirror-images.yml` copies the
  official `odoo` (16.0-19.0) and `postgres:16` images to `ghcr.io/transgenia`
  and refreshes them weekly; the sandbox uses them and falls back to Docker Hub.
- **MCP server `instructions`**: sent at `initialize`, so every session knows the
  guided route, the safe-use rules (confirm before any write) and when to point
  the user to Transgenia.
- **Transgenia support channels** at the points where they help: setup blocked
  (`/odoo-doctor`, connection errors), end of training, end of the sandbox and
  deployment phases, `SUPPORT.md` and the README: **dev@transgenia.org** and
  WhatsApp **+52 55 8034 0405** (https://wa.me/525580340405). They are not
  appended to unrelated answers.

### Changed
- Connection errors (incomplete credentials, authentication, transport) now end
  with the setup entry point and the support channels.
- `release.yml`: checks that the tag matches `plugin.json`, `marketplace.json`,
  `pyproject.toml` and the CHANGELOG; builds from the tag on manual runs (it
  built from the default branch); uses only this version's CHANGELOG section as
  release notes (it used the whole file); the plugin zip now includes
  `scripts/`, `docker/` and `SUPPORT.md`.
- PyPI publishing and the image mirror now run inside `release.yml`
  (`publish.yml` removed): a Release created with `GITHUB_TOKEN` triggers no
  other workflow, so `publish.yml` would never have run. The PyPI trusted
  publisher must name workflow `release.yml` and environment `pypi`.
- CI lints `scripts/` too.
- `release.yml` can be started from Actions → Run workflow on `main`: it creates the tag when missing.
- README badges for Claude Code / Claude AI and Odoo ERP (10-19, CE/EE/Online); `claude*` and `odoo-*` keywords in the plugin and marketplace manifests.

## [1.2.0] - 2026-09-27

Directory-submission follow-up: fixes the findings the Claude plugin directory
reported on v1.1.0.

- **Package registry redirected** (blocking) — `UV_PROJECT_ENVIRONMENT` is gone
  from the MCP server environment.
- **Runs a pinned npx or uvx package** — no package launcher: the server runs
  from the source bundled in the plugin.
- **MCP server command wasn't read** — the command is now `python3` plus a file
  under `${CLAUDE_PLUGIN_ROOT}`.
- **Uses a credential from the user's machine** (2 findings) — the SessionStart
  hook no longer reads the API key option.
- **Contains a download-and-run command** (`security.yml`) — gitleaks is built
  with `go install` instead of downloaded with `curl` and executed.

### Changed
- **The MCP server runs with `python3` (3.9+) instead of `uv`.** `plugin.json`
  starts `python3 ${CLAUDE_PLUGIN_ROOT}/server/run_stdio.py`; nothing is
  installed or downloaded when the plugin starts. **Migration:** `uv` is no
  longer needed, but a Python 3.9+ `python3` must be on `PATH`. On Windows that
  means the Microsoft Store Python, or a `python3.exe` added next to a
  python.org `python.exe` (see the README "Requirements").
- MCP stdio protocol implemented on the Python standard library (was the `mcp`
  SDK + `anyio`): `initialize` with version negotiation (2025-06-18,
  2025-03-26, 2024-11-05), `ping`, `tools/list` (with `readOnlyHint`
  annotations), `tools/call` (tool failures as `isError` results; unknown tool
  → JSON-RPC `-32602`), `notifications/cancelled` and batches. Tool calls run
  in arrival order on one worker thread; stray `print()` output goes to stderr.
- JSON-RPC transport uses `urllib` instead of `httpx`. Both transports share a
  certificate-verifying TLS context (system trust store and `SSL_CERT_FILE`,
  plus `certifi` when it happens to be installed).
- No runtime dependencies (`mcp` and `httpx` dropped); `requires-python` is now
  `>=3.9` (was `>=3.11`). The `dev` extra adds `mcp` (Python 3.10+) only for an
  interop test.
- SessionStart hook reads no plugin option at all: it runs `python3 --version`
  and prints a warning only when `python3` is not runnable.
- Default `ODOO_TIMEOUT` raised from 30 to 120 s (Odoo's default
  `limit_time_real`), and exposed as the **Request timeout** plugin option.
- In `auto` transport mode a write (`create`, `write`, any non-read
  `execute_kw`) is replayed over XML-RPC only when the JSON-RPC request certainly
  never reached Odoo (connection/TLS failure, HTTP 3xx/4xx). After a timeout,
  HTTP 5xx or a garbled 2xx reply the error is raised instead ("may or may not
  have been applied"), because the call may already have committed.
  `version`, `authenticate` and read methods (`search_read`, `read`, ...) still
  fall back; once JSON-RPC fails where XML-RPC works, XML-RPC is pinned for the
  session. A forced `jsonrpc` preference is never switched to XML-RPC.
- JSON-RPC no longer follows HTTP redirects (a redirected POST used to become a
  body-less GET whose reply was taken as the result), asks for gzip, and maps
  `http.client` protocol errors to transport errors.
- `odoo-setup-cli` creates the `.env` owner-only with placeholders and tells the
  user to paste the secret themselves; Claude never handles it. Docker examples
  use `--env-file` / `env_file:` instead of host environment variables.
- The leak-guard's organisation-specific markers moved to the
  `LEAK_GUARD_PATTERNS` repository secret (the plugin folder is the repository
  root, so the workflow file ships to every installer).
- CI secret scan: gitleaks v8.18.4 built with `go install` at a fixed tag
  (modules verified against the Go checksum database) instead of a `curl`
  download of the release binary.
- CI tests Python 3.9, 3.11, 3.12 and 3.13.

### Added
- `server/run_stdio.py` entry point (standard library only): puts the bundled
  `src` first on `sys.path`, so another installed `odoo_mcp` cannot shadow the
  shipped code, and exits with a clear message on Python < 3.9.
- Tests for the stdio protocol, argument validation, hostile input, the entry
  point under `python -S`, the `urllib` transport (basic auth, redirects, gzip,
  cut replies), fallback replay rules, the Community deadlock, TLS bundle
  fallback, the XML-RPC timeout, and interop with the official MCP client
  (dev-only, skipped when `mcp` is not installed).

### Fixed
- **Five of the six skills never loaded**: `skills/SKILL.md` sat directly in
  `skills/`, so Claude Code treated the folder as one skill and ignored its
  subfolders (`/odoo-tools:odoo-setup-mcp` and others did not exist). Moved to
  `skills/odoo-mcp-tools/SKILL.md`; all 9 skills and commands now load.
- **Deadlock on Community instances**: `OdooSession.facts()` held a
  non-reentrant lock while the edition probe authenticated through the same
  lock, hanging `odoo_version` (and every tool after it) on a cold session
  whenever the version string has no `+e`. The lock is now reentrant.
- Tool arguments are validated against each tool's input schema again (the MCP
  SDK used to do it): wrong types, missing required or misnamed properties are
  refused with `Input validation error: ...` before anything reaches Odoo.
- A malformed message (invalid id, unhashable `requestId`, deeply nested JSON,
  lone surrogates) can no longer stop the server; unexpected failures answer
  JSON-RPC `-32603` instead of leaving the request unanswered. Batched tool
  calls now run on the worker thread like single ones.
- `ODOO_URL` with `user:pass@` (HTTP basic auth in front of Odoo): JSON-RPC now
  sends it as an `Authorization` header, and neither transport's errors nor the
  startup log echo the password.
- HTTPS on Python builds without a CA file of their own (python.org macOS
  installers before "Install Certificates"): the OS CA bundle is loaded.
- The XML-RPC transport now honours `ODOO_TIMEOUT`; before, an unresponsive
  Odoo could block an XML-RPC call indefinitely. XML-RPC protocol errors
  (HTTP 5xx from a proxy, malformed replies) are reported as transport errors.

### Removed
- `server/uv.lock` (nothing to lock without runtime dependencies).

## [1.1.0] - 2026-09-25

Directory-submission hardening (Claude plugin directory lints and policy holds).

### Changed
- **Credentials are now plugin options (`userConfig`)** instead of shell
  environment variables read from the user's machine. URL, database and login
  are regular options; the API key and password are `sensitive` (masked input,
  OS secure credential store). Set them in `/plugin` → **odoo-tools** →
  **Configure options**. **Migration:** users who exported `ODOO_*` in their
  shell profile must enter the values once in the plugin options; the
  standalone server (Docker / `python -m odoo_mcp`) still reads `ODOO_*` env.
- The MCP server now runs the bundled source with dependencies pinned by the new
  `server/uv.lock` (`uv run --frozen`, venv under `${CLAUDE_PLUGIN_DATA}`),
  instead of an unpinned `uvx --from` resolution.
- SessionStart hook reads `CLAUDE_PLUGIN_OPTION_*` instead of `ODOO_*` env.
- New optional **Read-only mode** plugin option (maps to `ODOO_READONLY`).

### Added
- `PRIVACY.md` and a README "Privacy" section listing every service contacted.
- `.claude-plugin/icon.svg` and `displayName` ("Odoo Tools").
- Config treats unresolved `${...}` placeholders as unset, so an empty optional
  plugin option can never be used as a literal URL or credential.

### Fixed
- `plugin.json` no longer re-lists `hooks/hooks.json` (it is always loaded;
  listing it caused a duplicate-hooks load error).
- `marketplace.json` entry version now matches `plugin.json`.
- The release zip now ships `server/` (the MCP server the manifest launches)
  and `PRIVACY.md`.
- CI secret scan: replaced `gitleaks/gitleaks-action@v2` (requires a paid
  `GITLEAKS_LICENSE` for organization repos, so the job failed before scanning)
  with the free gitleaks CLI v8.18.4, pinned by version and SHA-256.

## [1.0.0] - 2026-09-20

First public release — the **Standard** package (free, MIT, public).
See [`docs/packaging.md`](docs/packaging.md) for the tier plan
(Standard now; Enterprise/Teams later, in separate packages).

### Added
- `odoo_telemetry_preview` read-only tool (21 tools total): renders the exact
  opt-in telemetry payload for human review, backed by server-side counters.
  Telemetry stays default-off, exact-token (`ODOO_TELEMETRY=opt-in`), PII-free
  by allowlist, with no schedules or background sends.
- `odoo_read_group` (22 tools total): server-side GROUP BY aggregation via
  classic `read_group` (Odoo 10-19), through the compat layer.
- `ODOO_READONLY=1` kill-switch: refuses every non-read-only tool centrally
  before touching Odoo (demos, safe exploration).
- Release flow (`.github/workflows/release.yml`): tag `v*` builds and verifies
  the Standard artifacts (PyPI sdist/wheel + plugin zip) and creates the
  GitHub Release; the existing `publish.yml` then publishes to PyPI.
- `docs/telemetry-schema.json` + `docs/telemetry-report-template.md`
  (synthetic example only — real user data never lives in this repo).

### Fixed (Codex review followups, PRs #6/#7)
- v10 automations link via legacy `server_action_ids`; orphan-cleanup message
  now reports accurately when the compensating unlink fails.
- safe_eval guard allows subscript stores on plain locals (`STORE_SUBSCR` is
  safe server-side) while still rejecting attribute assignment and `del`.
- Schema-cache invalidation is race-safe via per-model generations.
- CLI accepts `ODOO_PASSWORD` for Odoo < 14 (incl. 10-12); setup skill updated.
- Telemetry hardening: exact `opt-in` token only, allowlisted transport labels,
  version derived from package metadata, claims scoped vs Metrics/OTLP.

## [0.1.0] - 2026-09-17

### Added
- Clean-room MIT MCP server (`server/`, package `odoo-mcp-tools`) with 20 generic
  Odoo tools (search/read/search_read/search_count/create/write/unlink/execute,
  fields_get/list_models/module_info, export JSON/CSV, translate get/set, report,
  version, connections).
- Studio-style low-code tools (CE & EE, no Studio app): `odoo_add_field` (manual
  `x_` custom fields) and `odoo_add_automation` (safe_eval-validated automated
  actions, version-introspective over `base.automation`). Skill
  `odoo-studio-style` + doc `docs/odoo-studio-parity.md` explain the parity and
  the safe_eval caveat (esp. Odoo online/SaaS).
- Transport layer: XML-RPC, JSON-RPC, and an auto-fallback that handles the
  Odoo 17+ `/jsonrpc` API-key rejection transparently.
- Cross-version compatibility layer (Odoo 10-19): version/edition/deployment
  detection + declarative delta map + name/field/capability resolution.
- In-process TTL schema cache; optional Prometheus metrics and OTLP tracing.
- Claude plugin packaging: `plugin.json`, self-hosted `marketplace.json`, agents
  (`odoo`, `odoo-migrator`), skills (setup-mcp, setup-cli, connect, crossversion),
  commands (doctor, export), SessionStart hook.
- CLI fallback and Odoo domain context reused from the MIT `odoo-agent` project.
- CI (ruff + pytest on py3.11/3.12, CLI build), opt-in live Odoo version matrix,
  PyPI publish workflow, Docker image.

[1.2.0]: https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/releases/tag/v1.2.0
[1.1.0]: https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/releases/tag/v1.1.0
[1.0.0]: https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/releases/tag/v1.0.0
[0.1.0]: https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/releases/tag/v0.1.0
