# Packaging tiers

This repo ships the **Standard** package only: free, MIT-licensed, public.
Enterprise and Teams editions will live in **separate packages/repos** later —
nothing in this repo is gated, stubbed, or phone-home licensed.

## Standard (this repo, since v1.0.0)

| Artifact | Produced by | Contents |
|----------|-------------|----------|
| PyPI `odoo-mcp-tools` sdist + wheel | `release.yml` job `pypi` (trusted publishing: PyPI publisher = this repo, workflow `release.yml`, environment `pypi`) | `server/` (MCP server, 28 tools, no runtime dependencies) |
| `odoo-tools-standard-<ver>.zip` | `release.yml` on tag `v*` | plugin: `.claude-plugin/`, `agents/`, `skills/`, `commands/`, `context/`, `hooks/`, `cli/`, `docs/`, `server/` (the source the plugin runs with `python3`), plus `README.md`, `SECURITY.md`, `PRIVACY.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE`, `NOTICE` |
| `ghcr.io/transgenia/odoo-mcp-tools:<ver>` (+ `<major.minor>`, `latest`) | `release.yml` on tag `v*` | the MCP server as a container (amd64 + arm64), used by `/odoo-tools:deploy-local` container mode |
| `ghcr.io/transgenia/odoo:{16.0..19.0}`, `ghcr.io/transgenia/postgres:16` | `mirror-images.yml` (weekly, called by `release.yml`, manual) | unchanged copies of the official images, used by the sandbox |
| GitHub Release `v<ver>` | `release.yml` | sdist/wheel + plugin zip, notes = that version's CHANGELOG section |

Release procedure: bump `plugin.json`, `marketplace.json`, `server/pyproject.toml`
and the telemetry fallback and add the `## [<ver>]` CHANGELOG section. Then, in this
order, because Anthropic's directory picks up a merge to the tracked branch (by
default through the push webhook) and can publish it by itself, while the container
image the docs pin (`ghcr.io/transgenia/odoo-mcp-tools:<ver>`) exists only once the
tag's `container` job finishes:

1. Before merging: in the developer portal, plugin **Settings** tab, turn off
   **Publish new versions automatically** if it is on.
2. Merge, then right away run **Actions → Release → Run workflow** on `main` with
   tag `v<ver>` (the workflow creates the tag itself). `release.yml` refuses a tag
   that does not match the versions.
   - To review the release first, check **draft**. That run creates the tag, runs
     the tests and leaves a **draft** GitHub Release with the zip, sdist and wheel.
     It builds no image and uploads nothing to PyPI. Select **Publish release** on
     the draft when it is right: publishing runs the image, mirror and PyPI jobs.
     To discard it, delete the draft and the tag before running again.
   - Without **draft**, or when you push the tag `v<ver>` yourself, everything is
     published in one run.
   - Before anything is published, the `preflight` job reads the tag's release
     state: it stops a full run while that release is still a draft, and a draft
     run when the tag already has a release. GitHub lists draft releases only to a
     token with push access, so that job alone gets `contents: write` and runs no
     code but the query.
   - Publishing a draft runs the `pypi` job on the tag's ref, so the `pypi`
     environment must allow deployments from tags `v*` (it did for v1.5.0 on
     2026-10-23).
3. When `docker manifest inspect ghcr.io/transgenia/odoo-mcp-tools:<ver>` succeeds,
   select **Publish update** in the portal and turn the toggle back on.
4. Check that the version goes live. The directory can hold a version for an
   Anthropic reviewer (**Versions** tab, **Policy hold**); the **Overview** tab
   says why the newest version is not live, and directory users keep the live
   version until a reviewer releases the new one. v1.4.0 stayed live from
   2026-10-05 while 1.4.1 and 1.5.0 were held with "Update adds credential
   forward".

Install: `/plugin install odoo-tools --marketplace Transgenia/MCP-Odoo-Tools-CE-EE-and-online`
(Claude Code 2.1.275 or later; older versions add the marketplace first, see `docs/install.md`).

## Enterprise / Teams (later, separate)

Planned as independent offerings (own repos, own licenses): SSO/RBAC,
central audit logging, approval workflows for writes, managed hosting, SLA
support. The Standard package already has a local permission policy and a local
audit trail (`docs/policy.md`).
No enterprise-only code paths exist in this repo — when those editions land,
this Standard package stays exactly as-is: free and public.
