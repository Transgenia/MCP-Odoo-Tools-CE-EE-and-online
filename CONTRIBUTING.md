# Contributing

Thanks for helping improve MCP-Odoo-Tools.

## Ground rules

- **License:** contributions are accepted under the **MIT** license.
- **Clean-room:** do not copy code from AGPL-licensed Odoo MCP projects, nor from
  proprietary ones: Odoo Apps modules under the Odoo Proprietary License (OPL-1),
  or any code whose license does not allow redistribution under MIT. Such
  projects may inform ideas, read from their public documentation; never their
  code, tests, prompts or tool descriptions. Interoperate with them only over the
  network. Rely on Odoo's public XML-RPC/JSON-RPC/JSON-2 interfaces and public
  model/field names only.
- **Product rules:** read [`docs/product-rules.md`](docs/product-rules.md) before a
  change that affects where the plugin installs, what it says on a surface where
  its tools cannot run, credentials or diagnostics. The plugin installs on every
  surface Anthropic allows and is never blocked on one.
- **Scope:** this repo is the generic public core. A generic, declarative
  permission policy is part of the public core; approval workflows, localization
  engines (CFDI and the like), backups and other tenant-specific engines are not,
  and belong elsewhere.

## Server (Python)

```bash
cd server
python3 -m venv .venv && . .venv/bin/activate   # or use uv
pip install -e ".[dev,cache]"
ruff check src tests
pytest -q -m "not live"
```

- **No runtime dependencies.** The plugin runs the shipped source with the
  user's `python3` and installs nothing, so `src/` may import only the standard
  library. Optional packages (cache/metrics/otel, `certifi`) must stay behind a
  guarded import that degrades gracefully. Adding a required dependency would
  bring back a package install and the directory review hold it causes.
- **Python 3.9 compatible.** CI runs 3.9, 3.11, 3.12 and 3.13; ruff targets
  `py39`. `run_stdio.py` must also parse on older interpreters so it can print
  its version error.

- Add or change a cross-version behavior? Edit
  `src/odoo_mcp/compat/deltas.py` (data) and add a row to
  `tests/test_compat_resolve.py`. Boundaries you can't verify live should be
  commented "best-effort".
- New tool? Register it in `src/odoo_mcp/tools/` via the `registry` decorator and
  route model/field names through `compat` before the ORM call. A new tool must
  pass `access=` (what it touches, for the permission policy), declare its
  internal calls with predicates (`registry.Internal(model, methods, check=...,
  reason=...)`), and add a `GOLDEN` row to `tests/test_policy_mapping.py`; the
  mapping and coverage tests explain failures. Then refresh the tables of
  `docs/policy.md` with `python3 scripts/policy_docs.py --write` (see
  [Tool mapping](docs/policy.md#tool-mapping)).

## CLI (TypeScript)

```bash
cd cli && npm install && npm run build
```

## Pull requests

- Keep changes focused; include tests for logic.
- Say in the pull request what changes in the manual at docs.transgenia.org, or why
  nothing does ([product rule 8](docs/product-rules.md#8-every-change-is-checked-against-the-manual)).
  Transgenia's maintainers update the manual in Spanish, English and Chinese in the
  same release.
- Update `docs/compat-matrix.md` when the delta map changes.
- Note any new Odoo version/edition you verified against.
