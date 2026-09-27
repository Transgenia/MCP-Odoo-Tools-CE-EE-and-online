# Packaging tiers

This repo ships the **Standard** package only: free, MIT-licensed, public.
Enterprise and Teams editions will live in **separate packages/repos** later —
nothing in this repo is gated, stubbed, or phone-home licensed.

## Standard (this repo, since v1.0.0)

| Artifact | Produced by | Contents |
|----------|-------------|----------|
| PyPI `odoo-mcp-tools` sdist + wheel | `release.yml` job `pypi` (trusted publishing: PyPI publisher = this repo, workflow `release.yml`, environment `pypi`) | `server/` (MCP server, 22 tools, no runtime dependencies) |
| `odoo-tools-standard-<ver>.zip` | `release.yml` on tag `v*` | plugin: `.claude-plugin/`, `agents/`, `skills/`, `commands/`, `context/`, `hooks/`, `cli/`, `docs/`, `server/` (the source the plugin runs with `python3`), plus `README.md`, `SECURITY.md`, `PRIVACY.md`, `CHANGELOG.md`, `LICENSE`, `NOTICE` |
| `ghcr.io/transgenia/odoo-mcp-tools:<ver>` (+ `<major.minor>`, `latest`) | `release.yml` on tag `v*` | the MCP server as a container (amd64 + arm64), used by `/odoo-tools:deploy-local` container mode |
| `ghcr.io/transgenia/odoo:{16.0..19.0}`, `ghcr.io/transgenia/postgres:16` | `mirror-images.yml` (weekly, called by `release.yml`, manual) | unchanged copies of the official images, used by the sandbox |
| GitHub Release `v<ver>` | `release.yml` | sdist/wheel + plugin zip, notes = that version's CHANGELOG section |

Release procedure: bump `plugin.json`, `marketplace.json`, `server/pyproject.toml`
and the telemetry fallback, add the `## [<ver>]` CHANGELOG section, merge, then
push the tag `v<ver>`. `release.yml` refuses a tag that does not match.

Install: `/plugin marketplace add Transgenia/MCP-Odoo-Tools-CE-EE-and-online`
then `/plugin install odoo-tools` (see `docs/install.md`).

## Enterprise / Teams (later, separate)

Planned as independent offerings (own repos, own licenses): SSO/RBAC,
audit logging, approval workflows for writes, managed hosting, SLA support.
No enterprise-only code paths exist in this repo — when those editions land,
this Standard package stays exactly as-is: free and public.
