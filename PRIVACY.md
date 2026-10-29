# Privacy policy: Odoo Tools plugin

_Last updated: 2026-10-29. Applies to the `odoo-tools` Claude plugin in this
repository (MCP server, CLI fallback, skills, commands, agents and hooks), and to
the Claude Desktop extension preview built from it._

Publisher: Transgenia (Centrum Transgenia SAS), dev@transgenia.org.
Corporate privacy notice: <https://transgenia.org/en/legal-privacy.html>.

## Summary

- The plugin runs **on your machine**. Transgenia operates no server for it and
  **receives, proxies and retains no data** from it: not your credentials, not
  your Odoo records, not your prompts.
- The plugin **reads** personal data that lives in your Odoo (contact names,
  emails, addresses, etc.) when you or your agent ask for it. It does not keep
  its own copy of that data.
- It keeps small diagnostics on your computer, metadata only, so that support can
  learn what happened when something fails. They never leave your computer unless
  you send them.

## What data is processed, and where it goes

| Data | Where it goes | Why |
|------|---------------|-----|
| Odoo URL, database, login, API key / password | Stored by Claude Code as plugin options; the API key and password are `sensitive` options kept in the OS secure credential store. Passed to the local MCP server process, which sends them only to the Odoo URL you configured. Claude Code also exports every saved option to the environment of the plugin's hook processes; since 1.5.1 the plugin's hook reads none of them. | To authenticate against **your** Odoo instance. |
| Odoo records you query (may include personal data) | Sent from your Odoo to the local MCP server, then returned to your MCP client, which sends tool results to your model provider (e.g. Anthropic, for Claude) as with any tool. | To answer your request. Governed by your Odoo's and your model provider's terms, not by Transgenia. |
| Diagnostics and the support report (metadata only) | Your computer only, until you choose to send the report (see Local storage). | So that support can learn what happened when something fails. |
| Nothing | Transgenia | Not applicable |

## Services the plugin contacts

1. **Your Odoo instance:** the URL you configure, over JSON-2 / JSON-RPC / XML-RPC, from
   the MCP server (primary) or the optional CLI fallback.
2. **The npm registry, only for the optional CLI fallback:** when you run
   `/odoo-tools:odoo-setup-cli`, it runs `npm install` to build the CLI. No Odoo
   data or credentials are sent. The MCP server downloads nothing: it has no
   third-party dependencies and runs from the source shipped in the plugin.
3. **Optional, off by default, operator-configured:** an OTLP collector you set
   in `ODOO_OTEL_ENDPOINT`, and a local Prometheus endpoint (`ODOO_METRICS`).
   Telemetry (`ODOO_TELEMETRY=opt-in`) never sends anything by itself: it only
   renders a PII-free payload for you to review and share manually. See
   [`SECURITY.md`](SECURITY.md#opt-in-telemetry-disabled-by-default).

## Local storage

- The MCP server does not write credentials or records to disk. Its schema cache
  is in memory.
- **Audit log (1.5.0):** the MCP server writes one line per tool call, refusals
  included, to daily files in the plugin's data folder
  (`~/.claude/plugins/data/…/audit`, owner-only). A line holds tool, model and
  operation names, counts, timings and the policy digest; the Odoo database and
  login appear only on the line written when the server starts. It holds no
  record data, argument values, filters, ids, URL or secret. Files are kept 90
  days and are deleted with the plugin's data folder; in containers and
  standalone runs, `ODOO_AUDIT_DIR=off` writes none.
- **Exception, the optional CLI fallback:** `/odoo-tools:odoo-setup-cli` creates an
  owner-only `.env` with placeholders under `~/.claude/tools/odoo-cli`; you type
  your credentials into it yourself (Claude never asks for the secret). Delete it
  when you stop using the CLI.
- **Diagnostics (1.5.1):** two small files in the `diagnostics` folder of the
  plugin's data folder (`~/.claude/plugins/data/…/diagnostics`, owner-only), so
  that support can learn what happened when the Odoo tools do not work:
  - `server.jsonl`, written by the MCP server: when it starts (plugin, Python and
    operating system versions; the transport preference, read-only mode and
    permission profile; whether a URL, database and login are set, never their
    values; whether an API key or a password is used, never its value), the
    result of its first connection (the Odoo version, edition and deployment, or
    a category of error such as `auth` or `network` with the HTTP status), a
    crash (the error type and the plugin's own code lines, never the message),
    and when it stops (uptime, number of tool calls, errors by category);
  - `hook.jsonl`, written by the session-start hook: when a session starts, its
    session id, which Claude app started it, the plugin, Python and operating
    system versions, and the MCP server's last status.

  They hold no URL, host, database, login, API key, password, policy file path,
  record data, filters, ids, tool arguments or error message text. Each file is
  rotated at 256 KiB, keeping one previous file, and they are deleted with the
  plugin's data folder; in containers and standalone runs, `ODOO_DIAG_DIR=off`
  writes none. The plugin never sends them anywhere: `/odoo-tools:odoo-doctor`
  prints a support report from them, and you decide whether to send it.
- **Claude Desktop extension preview (not published yet):** the same MCP server,
  packaged for Claude Desktop ([`docs/desktop-extension.md`](docs/desktop-extension.md)).
  Claude Desktop stores its settings, with the API key and the password as sensitive
  settings. The server writes its audit log and diagnostics to
  `~/.odoo-tools/desktop/audit` and `~/.odoo-tools/desktop/diagnostics`, with the
  same content and limits as above.
- The SessionStart hook keeps empty timestamp files in the plugin's data folder
  so that its notices are shown at most once a day. Since 1.5.1 it reads only the
  plugin's data folder and the name of the Claude app that started the session:
  no plugin option, credential or policy file, and nothing outside the plugin's
  own folders.

## Retention

Transgenia retains **no** data received from Claude or from this plugin, because
none is sent to Transgenia.

## Your choices

- Use a least-privilege Odoo user and enable **Read-only mode** in the plugin
  options for exploration. The **Permission profile** option (`standard` by
  default) and an optional policy file narrow further what the tools read: a
  policy file can withhold fields such as personal e-mails (`fields.withhold`,
  see [`docs/policy.md`](docs/policy.md)).
- Revoke the API key in Odoo (Preferences → Account Security) to cut access
  immediately. Uninstalling the plugin (`/plugin`) also deletes its data
  directory (`~/.claude/plugins/data/…`).
- Delete the `diagnostics` folder in that data directory whenever you like; the
  plugin starts new files on the next session.

## Contact

Privacy or security questions: **dev@transgenia.org**.
