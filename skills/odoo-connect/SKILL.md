---
name: odoo-connect
description: Discover a target Odoo instance — version, edition (CE/EE) and deployment (onprem/SaaS) — before running operations, and choose the right surface (MCP vs CLI).
---

# Odoo — connection & environment discovery

Run this first against a new instance so later operations account for its
version and edition.

## 1. Identify the environment (MCP)

Call `odoo_version`. It returns:
- `version` (major int, 10-19)
- `edition` (`community` | `enterprise` | `unknown`)
- `deployment` (`onprem` | `saas`)
- `transport` (`jsonrpc(auto)` or `xmlrpc` after fallback)

Record these. The compat layer uses them to resolve model/field names, so you
almost never need version-specific branching in your queries.

## 2. Sanity read

Confirm data access with a bounded read:
```
odoo_search_read { "model": "res.partner", "fields": ["name"], "limit": 1 }
```

## 3. Explore before assuming

Each instance differs (custom `x_studio_*` fields, installed modules). Use
`odoo_fields_get { "model": "<model>" }` to discover the real schema before
building filters. `odoo_list_models { "like": "<fragment>" }` finds models.

## 4. Edition-gated models

Enterprise-only models (e.g. `documents.document`, `sign.request`,
`helpdesk.ticket`) raise a clear `CompatError` on Community instances. If you
hit one, the instance is CE — pick a Community-available alternative.

## Surface choice

- **MCP server (primary):** full tool set + compat layer + export. Default.
- **CLI fallback:** when the MCP server can't run, or for shell/batch scripts.
