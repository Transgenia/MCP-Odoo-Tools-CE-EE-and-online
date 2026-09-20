# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""In-process TTL cache for schema metadata (fields_get / name_get / model lists).

Uses ``cachetools.TTLCache`` when available, otherwise a small stdlib fallback
so the server has zero hard dependency on the optional ``cache`` extra.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable
from typing import Any

try:  # optional dependency
    from cachetools import TTLCache  # type: ignore

    _HAS_CACHETOOLS = True
except Exception:  # pragma: no cover - exercised when extra is absent
    _HAS_CACHETOOLS = False


class _SimpleTTLCache:
    """Minimal thread-safe TTL cache used when cachetools is not installed."""

    def __init__(self, maxsize: int, ttl: float) -> None:
        self._maxsize = maxsize
        self._ttl = ttl
        self._data: dict[Hashable, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Hashable, default: Any = None) -> Any:
        now = time.monotonic()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return default
            expires, value = item
            if expires < now:
                self._data.pop(key, None)
                return default
            return value

    def set(self, key: Hashable, value: Any) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._data) >= self._maxsize:
                # drop the oldest-expiring entry
                oldest = min(self._data.items(), key=lambda kv: kv[1][0], default=None)
                if oldest is not None:
                    self._data.pop(oldest[0], None)
            self._data[key] = (now + self._ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def delete(self, key: Hashable) -> None:
        with self._lock:
            self._data.pop(key, None)

    def keys(self) -> list[Hashable]:
        with self._lock:
            return list(self._data.keys())


class SchemaCache:
    """TTL cache keyed by ``(tenant, model, version, kind)``.

    ``kind`` distinguishes ``fields`` from ``name`` and ``models`` lookups so a
    single cache instance serves all schema reads. Records ``hit``/``miss``
    counters that :mod:`odoo_mcp.observability` can export.
    """

    def __init__(self, ttl: int = 300, maxsize: int = 2048) -> None:
        self.ttl = ttl
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()
        # Per-(tenant, model) generation bumped by invalidate_fields. Callers
        # include it in their cache key so an in-flight fill computed BEFORE
        # an invalidation (but stored AFTER) lands under a stale generation
        # and is never served.
        self._generations: dict[tuple[str, str], int] = {}
        if _HAS_CACHETOOLS:
            self._impl: Any = TTLCache(maxsize=maxsize, ttl=ttl)
            self._is_cachetools = True
        else:
            self._impl = _SimpleTTLCache(maxsize=maxsize, ttl=ttl)
            self._is_cachetools = False

    def get_or_compute(self, key: Hashable, compute: Callable[[], Any]) -> Any:
        cached = self._get(key)
        if cached is not None:
            with self._lock:
                self.hits += 1
            return cached
        with self._lock:
            self.misses += 1
        value = compute()
        self._set(key, value)
        return value

    def _get(self, key: Hashable) -> Any:
        if self._is_cachetools:
            try:
                return self._impl[key]
            except KeyError:
                return None
        return self._impl.get(key)

    def _set(self, key: Hashable, value: Any) -> None:
        if self._is_cachetools:
            self._impl[key] = value
        else:
            self._impl.set(key, value)

    def clear(self) -> None:
        if self._is_cachetools:
            self._impl.clear()
        else:
            self._impl.clear()
        with self._lock:
            self.hits = 0
            self.misses = 0

    def delete(self, key: Hashable) -> None:
        try:
            if self._is_cachetools:
                self._impl.pop(key, None)
            else:
                self._impl.delete(key)
        except Exception:  # noqa: S110 — best-effort cache eviction
            pass

    def invalidate(self, predicate: Callable[[Hashable], bool]) -> int:
        """Delete every key matching ``predicate``. Returns count removed."""
        if self._is_cachetools:
            try:
                keys = list(self._impl.keys())
            except Exception:
                return 0
            removed = 0
            for k in keys:
                try:
                    if predicate(k):
                        self._impl.pop(k, None)
                        removed += 1
                except Exception:  # noqa: S112 — keep evicting other keys
                    continue
            return removed
        try:
            keys = self._impl.keys()
        except Exception:
            return 0
        removed = 0
        for k in keys:
            try:
                if predicate(k):
                    self._impl.delete(k)
                    removed += 1
            except Exception:  # noqa: S112 — keep evicting other keys
                continue
        return removed

    def invalidate_fields(self, fingerprint: str, model: str) -> int:
        """Drop cached ``fields_get`` entries for ``model``/tenant.

        Called after ``odoo_add_field`` so an immediate verification
        ``odoo_fields_get`` does not serve the pre-create schema (TTL 300s).
        Also bumps the per-model generation so concurrent fills that started
        before this call cannot repopulate stale data afterwards.
        """
        with self._lock:
            gen_key = (fingerprint, model)
            self._generations[gen_key] = self._generations.get(gen_key, 0) + 1

        def _match(key: Hashable) -> bool:
            return (
                isinstance(key, tuple)
                and len(key) >= 3
                and key[0] == fingerprint
                and key[1] == "fields"
                and key[2] == model
            )

        return self.invalidate(_match)

    def generation(self, fingerprint: str, model: str) -> int:
        """Current generation for ``(fingerprint, model)`` (0 = never invalidated)."""
        with self._lock:
            return self._generations.get((fingerprint, model), 0)
