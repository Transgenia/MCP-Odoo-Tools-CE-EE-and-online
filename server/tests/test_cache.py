# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""SchemaCache hit/miss behavior."""

from __future__ import annotations

from odoo_mcp.cache import SchemaCache


def test_hit_and_miss_counters() -> None:
    cache = SchemaCache(ttl=300)
    calls = {"n": 0}

    def compute() -> str:
        calls["n"] += 1
        return "value"

    key = ("tenant", "fields", "res.partner", 17)
    assert cache.get_or_compute(key, compute) == "value"
    assert cache.get_or_compute(key, compute) == "value"
    assert calls["n"] == 1  # second call served from cache
    assert cache.hits == 1
    assert cache.misses == 1


def test_clear_resets() -> None:
    cache = SchemaCache(ttl=300)
    cache.get_or_compute(("k",), lambda: 1)
    cache.clear()
    assert cache.hits == 0 and cache.misses == 0
