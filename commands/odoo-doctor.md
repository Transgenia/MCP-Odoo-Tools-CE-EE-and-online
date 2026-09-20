---
description: Probe the connected Odoo instance and report version, edition, deployment, transport and a sanity read.
---

# /odoo-doctor

Diagnose the current Odoo connection.

1. Call the MCP tool `odoo_version` and report: `version`, `edition`
   (community/enterprise), `deployment` (onprem/saas) and `transport`.
2. Call `odoo_connections` and list active sessions.
3. Do a bounded sanity read to confirm data access:
   `odoo_search_read { "model": "res.partner", "fields": ["name"], "limit": 1 }`.
4. If any step fails, state the exact failure and point the user to
   `/odoo-tools:odoo-setup-mcp` (or `/odoo-tools:odoo-setup-cli` for the fallback).

Report the results as a short table. Do not perform any write.

## 5. Opt-in telemetry preview (explicit, manual, no PII)

Call the read-only MCP tool `odoo_telemetry_preview` and render exactly what it
returns. If it reports `opted_in: false`, state `telemetry: disabled (default)`
and stop. Never send anything anywhere yourself; let the human decide whether
to copy the payload block.

When opt-in is active, preface the block with this statement, in full, for
purposes of continuous improvement of the plugin:

> **Explicit opt-in telemetry for continuous improvement of the plugin.**
> This payload exists solely to guide maintenance of the version/transport
> compatibility matrix (`server/src/odoo_mcp/compat/deltas.py`), prioritization
> of transport fallback robustness (XML-RPC vs JSON-RPC surface, Odoo 17+
> `/jsonrpc` API-key refusal handling), schema-cache TTL calibration
> (`SchemaCache`, default 300s), documentation accuracy for CE/EE/online
> behavior across Odoo 10-19, and regression-test coverage for the generic tool
> surface (`odoo_search/read/search_read/create/write/unlink/execute/fields_get/
> export/report/studio`). It contains strictly: `plugin_version` (this repo's
> `server` package version), `odoo_version_major` (integer 10-19 from
> `common.version()`), normalized `odoo_edition` and `odoo_deployment` labels,
> the configured `transport` preference label, and aggregate counters
> `tool_calls_total` / `tool_calls_by_tool` keyed exclusively by known generic
> tool names. It contains no URL, no database name, no login or credential, no
> email/phone/company/record content, no domain/id/value tuples, no installed
> module inventory, no revenue or billing figures, no file path, and no hostname;
> the builder (`server/src/odoo_mcp/telemetry.py::build_optin_payload`) enforces
> this allowlist and `assert_no_pii` rejects any deviation. Emission is purely
> synchronous and operator-visible: no cron or 04:00 schedule, no at-boot or
> post-Sunday persistence, no background thread, no retry queue, no endpoint
> called by this codebase. Disabling is `unset ODOO_TELEMETRY` plus a server
> restart. By copying this block anywhere, the operator performs a discrete,
> revocable, human-initiated disclosure for the purposes above and nothing else.

Then show the payload (7 keys max) verbatim, followed by:
`To disable: unset ODOO_TELEMETRY and restart. Nothing was transmitted by this command.`
