# Packaging tiers

This repo ships the **Standard** package only: free, MIT-licensed, public.
Enterprise and Teams editions will live in **separate packages/repos** later —
nothing in this repo is gated, stubbed, or phone-home licensed.

## Standard (this repo, since v1.0.0)

| Artifact | Produced by | Contents |
|----------|-------------|----------|
| PyPI `odoo-mcp-tools` sdist + wheel | `publish.yml` on GitHub Release | `server/` (MCP server, 22 tools, no runtime dependencies) |
| `odoo-tools-standard-<ver>.zip` | `release.yml` on tag `v*` | plugin: `.claude-plugin/`, `agents/`, `skills/`, `commands/`, `context/`, `hooks/`, `cli/`, `docs/`, `server/` (the source the plugin runs with `python3`), plus `README.md`, `SECURITY.md`, `PRIVACY.md`, `CHANGELOG.md`, `LICENSE`, `NOTICE` |
| GitHub Release `v<ver>` | `release.yml` | both artifacts + CHANGELOG notes |

Install: `/plugin marketplace add Transgenia/MCP-Odoo-Tools-CE-EE-and-online`
then `/plugin install odoo-tools` (see `docs/install.md`).

## Enterprise / Teams (later, separate)

Planned as independent offerings (own repos, own licenses): SSO/RBAC,
audit logging, approval workflows for writes, managed hosting, SLA support.
No enterprise-only code paths exist in this repo — when those editions land,
this Standard package stays exactly as-is: free and public.
