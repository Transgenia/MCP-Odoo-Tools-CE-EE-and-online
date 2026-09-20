# Packaging tiers

This repo ships the **Standard** package only: free, MIT-licensed, public.
Enterprise and Teams editions will live in **separate packages/repos** later —
nothing in this repo is gated, stubbed, or phone-home licensed.

## Standard (this repo, v1.0.0)

| Artifact | Produced by | Contents |
|----------|-------------|----------|
| PyPI `odoo-mcp-tools` sdist + wheel | `publish.yml` on GitHub Release | `server/` (MCP server, 21 tools) |
| `odoo-tools-standard-<ver>.zip` | `release.yml` on tag `v*` | plugin: `.claude-plugin/`, `agents/`, `skills/`, `commands/`, `context/`, `hooks/`, `cli/`, `docs/` |
| GitHub Release `v<ver>` | `release.yml` | both artifacts + CHANGELOG notes |

Install: `/plugin marketplace add Transgenia/MCP-Odoo-Tools-CE-EE-and-online`
then `/plugin install odoo-tools` (see `docs/install.md`).

## Enterprise / Teams (later, separate)

Planned as independent offerings (own repos, own licenses): SSO/RBAC,
audit logging, approval workflows for writes, managed hosting, SLA support.
No enterprise-only code paths exist in this repo — when those editions land,
this Standard package stays exactly as-is: free and public.
