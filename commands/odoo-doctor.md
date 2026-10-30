---
description: Diagnose odoo-tools - whether the Odoo tools run on this surface, the connection to Odoo (version, edition, deployment, transport, a sanity read), and a support report with no keys, URLs or data.
---

# /odoo-doctor

Diagnose odoo-tools, in this order. Stop at the first step that explains the problem.

## 0. Are the Odoo tools loaded here? (always first)

Look at your tool list before you run anything. If `odoo_version` is in it, go to
step 1.

If it is not, this plugin's MCP server is not running in this session. Until it
runs, nothing else can be the cause, so:

- Do not run shell commands and do not check Python. In Cowork, the commands you
  run go to a virtual machine, not to the user's computer: a Python version read
  there says nothing about the computer, so never report one. (The plugin's own
  hooks are different: Cowork runs them on the computer itself.)
- Do not give advice about the Odoo side yet (subscription plan, API key, transport,
  database). It only matters once the tools load and Odoo refuses the connection.

Then:

1. Read any line in your context that starts with `odoo-tools session diagnostics:`.
   The plugin's session-start hook writes it from the user's computer, outside any
   virtual machine. Note its
   `entrypoint`, `server_last`, `age_h` and `diag_dir`.
2. Find the surface. If the user already said it (Cowork, Claude chat, claude.ai,
   the Code tab, a terminal, VS Code, JetBrains), use that. Otherwise ask one
   question: **1)** Claude Code (terminal, VS Code or JetBrains, or the **Code** tab
   of Claude Desktop) · **2)** Cowork · **3)** Claude chat (claude.ai web, desktop or
   mobile).
3. **Cowork or Claude chat:** say it plainly. This plugin's Odoo tools do not run
   there, by design of those apps: Anthropic's plugin support matrix says Cowork
   does not prompt for plugin options and ignores a local MCP server whose options
   have no default, and chat ignores a plugin's local MCP server. Nothing is wrong
   with the user's account, Odoo or Python, and the skills and commands they see
   did install correctly. Offer, in this order:
   1. The **Code** tab of Claude Desktop, or Claude Code. The plugin installed on
      their Claude account appears there as a synced plugin when they sign in with
      the same account; then run `/odoo-tools:odoo-setup-mcp`.
   2. Assisted setup by Transgenia: **dev@transgenia.org** · WhatsApp
      **+52 55 8034 0405** (https://wa.me/525580340405).
4. **Claude Code:** the server did not start. The usual causes are empty Odoo URL,
   database or login options, or a second copy of the plugin. Run the copies check
   and, for the copy it keeps, the options check (they read what Claude Code prints,
   contact nothing and never show the key):

   ```bash
   claude plugin list --json | python3 "${CLAUDE_PLUGIN_ROOT}/server/run_stdio.py" --check-copies
   claude plugin configure <id> --json | python3 "${CLAUDE_PLUGIN_ROOT}/server/run_stdio.py" --check-options
   ```

   If `claude` is not found, use `"$HOME/.local/bin/claude"`. Show both outputs as
   they are and follow `/odoo-tools:odoo-setup-mcp`, Phase 0b. The commands the
   copies check prints are for a terminal (PowerShell or Terminal), not for
   `/plugin`.
5. Finish with the support report (step 4).

## 1. The instance

1. Call the MCP tool `odoo_version`. First its `plugin` block: the odoo-tools
   `version` that answered and its `copy` (`plugin@marketplace`). If the answer has
   no `policy` key, a copy older than 1.5.0 answered, without the permission
   policy. Say so, run the copies check of step 0 (this is Claude Code), and stop
   here.

   Otherwise report: `version`, `edition`
   (community/enterprise), `deployment` (onprem/saas), `transport` (`json2`,
   `jsonrpc`, `xmlrpc` or `jsonrpc(auto)`) and, when it is not null,
   `transport_notice`: Odoo 19 deprecates `/xmlrpc` and `/jsonrpc` and Odoo 22
   (Odoo Online saas~21.1) removes them, so show the notice with its fix
   (usually: create an API key and set it in the plugin options).
   Also report its `policy` block: the `profile` (`standard` unless the user
   chose another), whether a policy `file` is set, the `digest`, the
   `hidden_tools`, any `opened_sensitive` entries with their reason and expiry,
   and every `warnings` entry. Show W10 (the Odoo user is an administrator)
   prominently and recommend a dedicated, least-privilege user. When `error` is
   set the policy is locked: show the error, say that every other Odoo tool is
   disabled until the user fixes the file or the **Permission profile** /
   **Permission policy file** options and reconnects (`/mcp`), and stop here.
2. Run the copies check of step 0 once and add its result to the table. Two
   copies can be active while the connection works, and then the options dialog
   and the tools may belong to different copies.

## 2. Sessions

Call `odoo_connections` and list active sessions.

## 3. Data access

Do a bounded sanity read to confirm data access:
`odoo_search_read { "model": "res.partner", "fields": ["name"], "limit": 1 }`.
Then call the read-only `odoo_online_profile` and add to the table its `series`
(e.g. `saas~19.2` on Odoo Online), `deployment_confidence` and any `hints` (for
example an API key that expires soon). When `deployment` is `saas`, also list its
`online_hints`. Only now, if Odoo refused the connection, do the Odoo-side checks
apply: on Odoo Online, external API access needs a Custom plan; an expired or
revoked API key; the database name.

## 4. Failures and the support report

If any step fails, state the exact failure and point the user to
`/odoo-tools:odoo-setup-mcp` (or `/odoo-tools:odoo-setup-cli` for the fallback).

Always end with a support report the user can send to Transgenia:

- **Claude Code** (you can run commands on the user's computer): run

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/server/run_stdio.py" --diagnose --diag-dir "${CLAUDE_PLUGIN_DATA}/diagnostics" --audit-dir "${CLAUDE_PLUGIN_DATA}/audit"
  ```

  and show its output as it is, in a code block. It reads only the plugin's local
  diagnostics and audit files and contacts nothing. If `python3` is missing, say
  so and give the report below instead.
- **Cowork or Claude chat:** write a short report from step 0: the surface, the
  `entrypoint`, `server_last` and `age_h` values of the session diagnostics line,
  and that the diagnostics files are in `diag_dir` on the user's computer (they can
  attach them to an e-mail). Claude chat runs no plugin hooks, so there is no such
  line there: report the surface only.

Say that the report holds no keys, URLs, logins or record data, and that they can
send it to **dev@transgenia.org** or by WhatsApp **+52 55 8034 0405**
(https://wa.me/525580340405) for assisted support. Never ask for the API key or
password, in the chat or anywhere else.

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
