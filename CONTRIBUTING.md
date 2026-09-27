# Contributing

Thanks for helping improve MCP-Odoo-Tools.

## Ground rules

- **License:** contributions are accepted under the **MIT** license.
- **Clean-room:** do not copy code from AGPL-licensed Odoo MCP projects. Rely on
  Odoo's public XML-RPC/JSON-RPC interfaces and public model/field names only.
- **Scope:** this repo is the generic public core. Localization/governance/
  tenant-specific engines (CFDI, approval gates, backups, etc.) belong elsewhere.

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
  route model/field names through `compat` before the ORM call.

## CLI (TypeScript)

```bash
cd cli && npm install && npm run build
```

## Pull requests

- Keep changes focused; include tests for logic.
- Update `docs/compat-matrix.md` when the delta map changes.
- Note any new Odoo version/edition you verified against.
