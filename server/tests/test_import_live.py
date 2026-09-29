# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Live import checks against local sandboxes (opt-in: ``-m live`` plus paths).

Same setup as ``test_json2_live.py``: ``ODOO_LIVE_SBX19_DIR`` / ``ODOO_LIVE_SBX19_KEY_FILE``
and ``ODOO_LIVE_SBX18_DIR`` (key file optional; the admin password from ``.env`` is used
without one). Every record the tests create is named ``odoo-tools-live-import`` and removed.

They pin two facts of Odoo 16-19 the import tools rely on:

* ``base_import.import.file`` takes the raw CSV bytes, not base64: the preview sends the
  CSV text and Odoo reads quoted commas, embedded newlines and non-ASCII unchanged.
* ``load()`` is all-or-nothing: one failing row, at conversion or at database level,
  rolls every row of the call back.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from odoo_mcp import tools as _tools  # noqa: F401  (import registers all tools)
from odoo_mcp.config import Settings
from odoo_mcp.errors import CompatError
from odoo_mcp.registry import ToolContext, registry
from odoo_mcp.tenancy import ConnectionManager

pytestmark = pytest.mark.live

TAG = "odoo-tools-live-import"
FIELDS = ["name", "street", "city", "country_id"]


def _ctx(prefix: str) -> ToolContext:
    directory = os.environ.get(f"ODOO_LIVE_{prefix}_DIR")
    if not directory:
        pytest.skip(f"set ODOO_LIVE_{prefix}_DIR (and ODOO_LIVE_{prefix}_KEY_FILE)")
    env: dict[str, str] = {}
    for line in (Path(directory).expanduser() / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    key_file = os.environ.get(f"ODOO_LIVE_{prefix}_KEY_FILE")
    api_key = Path(key_file).read_text().strip() if key_file else ""
    settings = Settings(url=f"http://localhost:{env['ODOO_PORT']}", db=env["ODOO_DB"],
                        login=env["ODOO_ADMIN_LOGIN"], api_key=api_key,
                        password="" if api_key else env["ODOO_ADMIN_PASSWORD"],
                        transport_pref="auto", timeout=60)
    manager = ConnectionManager(settings)
    return ToolContext(session=manager.default(), manager=manager)


def _call(ctx: ToolContext, name: str, args: dict[str, Any]) -> Any:
    return registry.get(name).handler(ctx, args)


def _ours(ctx: ToolContext, model: str = "res.partner") -> list[int]:
    return ctx.session.execute(model, "search", [[["name", "like", TAG]]],
                               {"context": {"active_test": False}})


@pytest.fixture(params=["SBX18", "SBX19"])
def ctx(request: pytest.FixtureRequest) -> Any:
    context = _ctx(request.param)
    yield context
    for model in ("res.partner", "res.country"):
        ids = _ours(context, model)
        if ids:
            context.session.execute(model, "unlink", [ids])


def _rows(label: str) -> list[list[str]]:
    return [
        [f"{TAG} {label} José Peña, S.A.", "Calle 1, Int. 2\nCol. Centro", "Ñandú, Norte",
         "Mexico"],
        [f"{TAG} {label} \"Ana\" López ü ß € 日本", "Line \"quoted\"\nsecond, line",
         "São Paulo", "Brazil"],
    ]


def test_quoted_commas_newlines_and_non_ascii_survive_both_import_paths(ctx: Any) -> None:
    rows = _rows("csv")
    preview = _call(ctx, "odoo_import_preview", {"model": "res.partner", "fields": FIELDS,
                                                 "rows": rows})
    assert (preview["would_import"], preview["errors"], preview["warnings"]) == (2, 0, 0)
    assert _ours(ctx) == []  # the dry run saved nothing
    out = _call(ctx, "odoo_import", {"model": "res.partner", "fields": FIELDS, "rows": rows})
    assert out["ok"] is True and out["count"] == 2
    saved = ctx.session.execute("res.partner", "read", [out["ids"]],
                                {"fields": ["name", "street", "city", "country_id"]})
    assert [[r["name"], r["street"], r["city"], r["country_id"][1]] for r in saved] == rows


def test_a_mixed_batch_saves_nothing(ctx: Any) -> None:
    good = [[f"{TAG} good 1", "", "", "Mexico"], [f"{TAG} good 2", "", "", "Spain"]]
    for rows in (good + [[f"{TAG} bad", "", "", "Atlantis"]],
                 [[f"{TAG} bad", "", "", "Atlantis"]] + good):
        out = _call(ctx, "odoo_import", {"model": "res.partner", "fields": FIELDS,
                                         "rows": rows})
        assert (out["ok"], out["ids"], out["errors"]) == (False, [], 1)
        assert _ours(ctx) == []
    # a database-level failure (duplicate country code) goes through load()'s row-by-row
    # retry, which saves the good row in a savepoint before the whole call is rolled back
    used = {c["code"] for c in ctx.session.execute("res.country", "search_read", [[]],
                                                   {"fields": ["code"]})}
    free = next(a + b for a in "QXZ" for b in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                if a + b not in used)
    out = _call(ctx, "odoo_import", {"model": "res.country", "fields": ["name", "code"],
                                     "rows": [[f"{TAG} land", free], [f"{TAG} dup", "MX"]]})
    assert (out["ok"], out["ids"], out["errors"]) == (False, [], 1)
    assert _ours(ctx, "res.country") == []


def test_trailing_text_in_an_aggregate_spec_is_refused_on_formatted_read_group() -> None:
    ctx = _ctx("SBX19")
    args = {"model": "res.partner", "groupby": ["type"]}
    for spec in ("color:sum trailing", "total:sum(color)junk", "color:sum,id:count"):
        with pytest.raises(CompatError, match="invalid field specification"):
            _call(ctx, "odoo_read_group", {**args, "fields": [spec]})
    for spec in ("color", "color:max", "total:sum(color)"):
        assert "groups" in _call(ctx, "odoo_read_group", {**args, "fields": [spec]})
