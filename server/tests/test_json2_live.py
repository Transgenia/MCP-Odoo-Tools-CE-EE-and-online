# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Live JSON-2 checks against local sandboxes (opt-in: ``-m live`` plus paths).

Start the sandboxes with ``scripts/deploy_local.py sandbox up`` (19.0 and 18.0),
create an admin API key in each, and point the tests at them:

    ODOO_LIVE_SBX19_DIR=<19.0 sandbox dir>  ODOO_LIVE_SBX19_KEY_FILE=<file with the key>
    ODOO_LIVE_SBX18_DIR=<18.0 sandbox dir>  (ODOO_LIVE_SBX18_KEY_FILE optional)
    python -m pytest -m live tests/test_json2_live.py

The credentials are read from the sandbox's owner-only ``.env`` and the key
file, and never printed. The parity run calls the real tool handlers over
JSON-2 and over XML-RPC on the same database and compares the results.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest

from odoo_mcp import tools as _tools  # noqa: F401  (import registers all tools)
from odoo_mcp.config import Settings
from odoo_mcp.registry import ToolContext, registry
from odoo_mcp.tenancy import ConnectionManager

pytestmark = pytest.mark.live


def _env_file(directory: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (Path(directory).expanduser() / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def _sandbox(prefix: str, need_key: bool = True) -> tuple[dict[str, str], str]:
    directory = os.environ.get(f"ODOO_LIVE_{prefix}_DIR")
    key_file = os.environ.get(f"ODOO_LIVE_{prefix}_KEY_FILE")
    if not directory or (need_key and not key_file):
        pytest.skip(f"set ODOO_LIVE_{prefix}_DIR and ODOO_LIVE_{prefix}_KEY_FILE")
    key = Path(key_file).read_text().strip() if key_file else ""
    return _env_file(directory), key


def _ctx(env: dict[str, str], *, pref: str, api_key: str = "", password: str = "") -> ToolContext:
    settings = Settings(url=f"http://localhost:{env['ODOO_PORT']}", db=env["ODOO_DB"],
                        login=env["ODOO_ADMIN_LOGIN"], api_key=api_key, password=password,
                        transport_pref=pref, timeout=60)
    manager = ConnectionManager(settings)
    return ToolContext(session=manager.default(), manager=manager)


def _call(ctx: ToolContext, name: str, args: dict[str, Any]) -> Any:
    return registry.get(name).handler(ctx, args)


READS: list[tuple[str, dict[str, Any]]] = [
    ("odoo_search", {"model": "res.partner", "domain": [["is_company", "=", True]],
                     "order": "id", "limit": 5}),
    ("odoo_search_count", {"model": "res.partner", "domain": [["is_company", "=", True]]}),
    ("odoo_search_read", {"model": "res.partner", "domain": [["is_company", "=", True]],
                          "fields": ["name", "country_id", "email"], "order": "id", "limit": 5}),
    ("odoo_read", {"model": "res.partner", "ids": [1, 2, 3], "fields": ["name", "display_name"]}),
    ("odoo_read_group", {"model": "res.partner", "fields": ["color:sum"],
                         "groupby": ["country_id", "is_company"], "orderby": "country_id",
                         "domain": [["is_company", "=", True]], "limit": 3}),
    ("odoo_read_group", {"model": "res.partner", "fields": ["color"], "groupby": ["is_company"],
                         "lazy": False}),
    ("odoo_read_group", {"model": "res.partner", "fields": ["color:sum"],
                         "groupby": ["create_date"], "limit": 2}),
    ("odoo_export_records_csv", {"model": "res.partner", "fields": ["name", "country_id"],
                                 "order": "id", "limit": 5}),
    ("odoo_list_models", {"like": "res.partner", "limit": 20}),
    ("odoo_module_info", {"name": "base"}),
    ("odoo_translate_get", {"model": "res.partner", "id": 1, "field": "name", "lang": "en_US"}),
    ("odoo_execute", {"model": "res.partner", "method": "name_search",
                      "args": ["a"], "kwargs": {"limit": 5}}),
    ("odoo_execute", {"model": "res.users", "method": "has_group", "ids": [2],
                      "args": ["base.group_system"]}),
]


def test_json2_and_xmlrpc_give_the_same_tool_results() -> None:
    env, key = _sandbox("SBX19")
    json2 = _ctx(env, pref="json2", api_key=key)
    xmlrpc = _ctx(env, pref="xmlrpc", api_key=key)
    v2, vx = _call(json2, "odoo_version", {}), _call(xmlrpc, "odoo_version", {})
    assert (v2["transport"], vx["transport"]) == ("json2", "xmlrpc")
    assert v2["transport_notice"] is None and vx["transport_notice"]
    assert {k: v for k, v in v2.items() if not k.startswith("transport")} == {
        k: v for k, v in vx.items() if not k.startswith("transport")}
    fields2 = _call(json2, "odoo_fields_get", {"model": "res.partner", "attributes": ["type"]})
    fieldsx = _call(xmlrpc, "odoo_fields_get", {"model": "res.partner", "attributes": ["type"]})
    assert fields2 == fieldsx
    for name, args in READS:
        assert _call(json2, name, args) == _call(xmlrpc, name, args), (name, args)


def test_writes_over_json2_are_seen_over_xmlrpc() -> None:
    env, key = _sandbox("SBX19")
    json2 = _ctx(env, pref="json2", api_key=key)
    xmlrpc = _ctx(env, pref="xmlrpc", api_key=key)
    tag = f"odoo-tools live json2 {int(time.time())}"
    new_id = _call(json2, "odoo_create", {"model": "res.partner", "values": {"name": tag}})["id"]
    assert isinstance(new_id, int)
    try:
        _call(json2, "odoo_write", {"model": "res.partner", "ids": [new_id],
                                    "values": {"name": tag + " (renamed)"}})
        rows = _call(xmlrpc, "odoo_read", {"model": "res.partner", "ids": [new_id],
                                           "fields": ["name"]})["records"]
        assert rows[0]["name"] == tag + " (renamed)"
    finally:
        assert _call(json2, "odoo_unlink", {"model": "res.partner", "ids": [new_id]})["ok"]
    assert _call(xmlrpc, "odoo_search_count", {"model": "res.partner",
                                               "domain": [["name", "like", tag]]})["count"] == 0


def test_a_password_on_19_stays_legacy_and_gets_the_notice() -> None:
    env, _key = _sandbox("SBX19")
    ctx = _ctx(env, pref="auto", password=env["ODOO_ADMIN_PASSWORD"])
    version = _call(ctx, "odoo_version", {})
    assert version["transport"] == "jsonrpc(auto)"
    assert "Create an API key" in (version["transport_notice"] or "")


def test_18_stays_on_legacy_without_a_notice() -> None:
    env, key = _sandbox("SBX18", need_key=False)
    if key:
        ctx = _ctx(env, pref="auto", api_key=key)
    else:
        ctx = _ctx(env, pref="auto", password=env["ODOO_ADMIN_PASSWORD"])
    version = _call(ctx, "odoo_version", {})
    assert version["version"] == 18
    assert version["transport"] == "jsonrpc(auto)" and version["transport_notice"] is None


def test_a_real_bind_error_is_recognised_and_corrected() -> None:
    """Odoo's own 422 from signature.bind: the saas~18.4 override case, replayed on
    19.0 by teaching the transport a wrong name (write(values); 19.0 takes vals)."""
    from odoo_mcp.errors import OdooFault
    from odoo_mcp.transport.json2_signatures import Signature

    env, key = _sandbox("SBX19")
    ctx = _ctx(env, pref="json2", api_key=key)
    tag = f"odoo-tools live bind {int(time.time())}"
    new_id = _call(ctx, "odoo_create", {"model": "res.partner", "values": {"name": tag}})["id"]
    try:
        session = ctx.session
        _ = session.uid
        j2 = session.transport._json2()
        j2._learned[(env["ODOO_DB"], "res.partner", "write")] = Signature(False, ("values",))
        assert _call(ctx, "odoo_write", {"model": "res.partner", "ids": [new_id],
                                         "values": {"name": tag + " (bind)"}})["ok"]
        assert j2._learned[(env["ODOO_DB"], "res.partner", "write")].params == ("vals",)
        rows = _call(ctx, "odoo_read", {"model": "res.partner", "ids": [new_id],
                                        "fields": ["name"]})["records"]
        assert rows[0]["name"] == tag + " (bind)"
        with pytest.raises(OdooFault, match="check the names in kwargs"):
            _call(ctx, "odoo_execute", {"model": "res.partner", "method": "write",
                                        "ids": [new_id], "kwargs": {"values": {"name": "x"}}})
    finally:
        assert _call(ctx, "odoo_unlink", {"model": "res.partner", "ids": [new_id]})["ok"]
