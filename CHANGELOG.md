# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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
  on changes to the sandbox or the server, weekly, and on demand.
- The image mirror also copies `odoo:10.0`-`15.0` and `postgres:10`, `12`, `13`.

### Fixed
- The sandbox talks to Odoo over XML-RPC (`/xmlrpc/2/common`, `/xmlrpc/2/db`)
  instead of `/jsonrpc`, which does not exist before Odoo 12.0.

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
