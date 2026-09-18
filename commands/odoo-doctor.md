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
