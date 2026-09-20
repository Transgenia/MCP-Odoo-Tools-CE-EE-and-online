# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Tests for ODOO_READONLY kill-switch and odoo_read_group."""

from __future__ import annotations

import pytest

from odoo_mcp.config import Settings
from odoo_mcp.errors import CompatError
from odoo_mcp.registry import ToolContext, registry
from odoo_mcp.server import check_readonly
from odoo_mcp.tools.crud import odoo_read_group


def test_readonly_parses_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("ODOO_READONLY", "1")
    assert Settings.from_env().readonly is True
    monkeypatch.delenv("ODOO_READONLY", raising=False)
    assert Settings.from_env().readonly is False


def test_readonly_blocks_writes_but_not_reads() -> None:
    settings = Settings(readonly=True)
    write_tool = registry.get("odoo_create")
    read_tool = registry.get("odoo_search_read")
    with pytest.raises(CompatError, match="ODOO_READONLY"):
        check_readonly(settings, write_tool)
    check_readonly(settings, read_tool)  # no raise
    check_readonly(Settings(), write_tool)  # disabled by default: no raise


class _FakeSession:
    def __init__(self) -> None:
        from odoo_mcp.compat import EnvFacts

        self.calls: list[tuple] = []
        self._facts = EnvFacts(version=17, edition="community", deployment="onprem")

    def facts(self):
        return self._facts

    def execute(self, model, method, args=None, kwargs=None):
        self.calls.append((model, method, args, kwargs))
        assert method == "read_group"
        return [{"stage_id": [1, "New"], "expected_revenue:sum": 5000.0, "__count": 2}]


def test_read_group_resolves_model_and_returns_groups() -> None:
    fake = _FakeSession()
    res = odoo_read_group(
        ToolContext(session=fake, manager=None),
        {"model": "crm.lead", "fields": ["stage_id", "expected_revenue:sum"],
         "groupby": ["stage_id"]},
    )
    assert res["model"] == "crm.lead"
    assert res["groups"][0]["__count"] == 2
    _, _, args, _ = fake.calls[0]
    assert args[1] == ["stage_id", "expected_revenue:sum"]
    assert args[2] == ["stage_id"]
