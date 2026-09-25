# Privacy policy — Odoo Tools plugin

_Last updated: 2026-09-25. Applies to the `odoo-tools` Claude plugin in this
repository (MCP server, CLI fallback, skills, commands, agents and hooks)._

Publisher: Transgenia (Centrum Transgenia S.A.S. de C.V.), dev@transgenia.org.
Corporate privacy notice: <https://transgenia.org/en/legal-privacy.html>.

## Summary

- The plugin runs **on your machine**. Transgenia operates no server for it and
  **receives, proxies and retains no data** from it — not your credentials, not
  your Odoo records, not your prompts.
- The plugin **reads** personal data that lives in your Odoo (contact names,
  emails, addresses, etc.) when you or your agent ask for it. It does not keep
  its own copy of that data.

## What data is processed, and where it goes

| Data | Where it goes | Why |
|------|---------------|-----|
| Odoo URL, database, login, API key / password | Stored by Claude Code as plugin options; the API key and password are `sensitive` options kept in the OS secure credential store. Passed only to the local MCP server process. | To authenticate against **your** Odoo instance. |
| Odoo records you query (may include personal data) | Sent from your Odoo to the local MCP server, then returned to your MCP client, which sends tool results to your model provider (e.g. Anthropic, for Claude) as with any tool. | To answer your request. Governed by your Odoo's and your model provider's terms, not by Transgenia. |
| Nothing | Transgenia | — |

## Services the plugin contacts

1. **Your Odoo instance** — the URL you configure, over JSON-RPC / XML-RPC, from
   the MCP server (primary) or the optional CLI fallback.
2. **Package registries, at install/first launch only** — `uv` downloads the
   server's Python dependencies pinned in `server/uv.lock` from PyPI; the
   optional CLI fallback runs `npm install` against the npm registry. No Odoo
   data or credentials are sent.
3. **Optional, off by default, operator-configured:** an OTLP collector you set
   in `ODOO_OTEL_ENDPOINT`, and a local Prometheus endpoint (`ODOO_METRICS`).
   Telemetry (`ODOO_TELEMETRY=opt-in`) never sends anything by itself: it only
   renders a PII-free payload for you to review and share manually. See
   [`SECURITY.md`](SECURITY.md#opt-in-telemetry-disabled-by-default).

## Local storage

- The MCP server does not write credentials or records to disk. Its schema cache
  is in memory.
- **Exception — optional CLI fallback:** `/odoo-tools:odoo-setup-cli` writes a
  `.env` with your credentials under `~/.claude/tools/odoo-cli`. Delete it when
  you stop using the CLI.

## Retention

Transgenia retains **no** data received from Claude or from this plugin, because
none is sent to Transgenia.

## Your choices

- Use a least-privilege Odoo user and enable **Read-only mode** in the plugin
  options for exploration.
- Revoke the API key in Odoo (Preferences → Account Security) to cut access
  immediately. Uninstalling the plugin (`/plugin`) also deletes its data
  directory (`~/.claude/plugins/data/…`).

## Contact

Privacy or security questions: **dev@transgenia.org**.
