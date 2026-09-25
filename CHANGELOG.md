# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

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

[1.0.0]: https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/releases/tag/v1.0.0
[0.1.0]: https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/releases/tag/v0.1.0
