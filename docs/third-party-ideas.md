# Third-party ideas evaluated (best-of audit, 2026-09-20)

Read-only review of five public Odoo MCP servers. **No third-party code was
copied** — adaptations below are clean-room reimplementations in our style,
honoring each repo's license. See the PR description's IP section.

| Repo | License | Stars (verified 2026-09-20) | Verdict |
|------|---------|-----------------------------|---------|
| `erpipe-org/mcp-odoo` (PyPI `odoo-mcp`) | MIT | 413 | Adopt concepts selectively; three-step writes deferred |
| `ivnvxd/mcp-server-odoo` (+ Apps Store `mcp_server` module) | MPL-2.0 | 388 | Adopt `read_group` idea; Apps module needs business decision |
| `mart337i/odoo-dev-mcp` | MIT | — (not recorded) | Different angle (scaffolding); deferred |
| `sameeroz/odoo-mcp-server` | MIT | — (not recorded) | i18n already covered; no action |
| `altinkaya-opensource/odoo-mcp` | AGPL-3.0 | — (not recorded) | Concept only (`READONLY_MODE` idea), never code |

## Adopted in this release (reimplemented)

1. **Read-only kill-switch** — idea observed in `altinkaya-opensource/odoo-mcp`
   (`READONLY_MODE`, AGPL-3.0: concept only, zero lines copied). Ours differs
   by design: central enforcement in `server.py::check_readonly` using the
   existing `ToolDef.read_only` flags, instead of per-tool guards. Env var is
   `ODOO_READONLY` (distinct name, same granularity: every `read_only=False`
   tool refused before any session/transport is touched).
2. **Server-side aggregation** — idea observed in `ivnvxd/mcp-server-odoo`
   (`aggregate_records`, MPL-2.0: reimplemented, not copied) and
   `altinkaya-opensource/odoo-mcp` (`read_group`, AGPL-3.0: concept only).
   Ours is `odoo_read_group`: classic `read_group` (works on Odoo 10-19,
   unlike version-gated `formatted_read_group`), routed through our compat
   layer (`resolve_model` + `requires_edition`).

## Evaluated, deferred (with reason)

- **Three-step safe writes** (`erpipe-org/mcp-odoo`, MIT): robust, but our
  agent already gates writes on user confirmation (`agents/odoo.md`), and
  session-token state adds complexity. Candidate for the Enterprise tier.
- **`fit_gap_report` / `upgrade_risk_report` / `scan_addons_source`**
  (`erpipe-org/mcp-odoo`, MIT): strong commercial fit for Transgenia's
  fit/gap + migration services. Sizable input-driven heuristics — propose as
  a follow-up services-oriented pack, not in Standard 1.0.
- **Entry-point plugins `ODOO_MCP_PLUGINS`** (`erpipe-org/mcp-odoo`, MIT):
  nice extensibility, but new API surface to maintain. Roadmap.
- **Companion Odoo module + Apps Store listing** (`ivnvxd`, external module):
  distribution advantage is real (reaches business owners, not just devs),
  but publishing a module is a **business decision for Saurat/Efraín**
  (maintenance, version matrix 10-19, store reviews). Not started.
- **Smart field selection** (`ivnvxd`, MPL-2.0): our tools require explicit
  fields (honest, no magic). Could reduce token usage later; deferred.
- **Module/view/security/migration/OWL scaffolding** (`mart337i/odoo-dev-mcp`,
  MIT): different job (build modules vs operate production). Standard 1.0
  stays operate-focused; scaffolding is a possible second skill later.
- **Explicit locale map en/ar/fr/es** (`sameeroz/odoo-mcp-server`, MIT):
  no gap — Odoo `context.lang` plus our `odoo_translate_get/set` already
  cover MX/LatAm needs; a two-letter convenience map adds nothing structural.

## License hygiene

- AGPL-3.0 (`altinkaya-opensource/odoo-mcp`): concept-level inspiration only.
- MPL-2.0 (`ivnvxd/mcp-server-odoo`): no file copied, so no file-level copyleft triggered.
- MIT repos: attribution given here; code is ours.
