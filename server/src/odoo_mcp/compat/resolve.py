# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Resolve model/field names and capabilities for a given Odoo environment.

Every tool routes its model/field names through here BEFORE hitting the ORM so
one tool call works unchanged across Odoo 10-19 / CE / EE.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import CompatError
from .deltas import (
    CAPABILITIES,
    ENTERPRISE_ONLY_MODELS,
    FIELD_REMOVED,
    FIELD_RENAMES,
    METHOD_DELTAS,
    MODEL_RENAMES,
    Capability,
    MethodDelta,
)
from .detect import EnvFacts


@dataclass
class FieldResolution:
    """Result of resolving a field list for a model+version."""

    mapping: dict[str, str]  # requested -> actual (usable) name
    dropped: dict[str, str]  # requested -> reason (not available on this version)

    @property
    def usable(self) -> list[str]:
        return list(self.mapping.values())


def resolve_model(name: str, facts: EnvFacts) -> str:
    """Return the model name valid on ``facts.version``.

    Accepts either the historical or modern name and returns whichever exists on
    the target version.
    """
    for r in MODEL_RENAMES:
        # old -> new once the old model is gone (valid for both renames and merges)
        if name == r.old and facts.version >= r.changed_in:
            return r.new
        # new -> old on older versions ONLY for a clean rename. For a merge the
        # ``new`` model already exists (as a different model) before changed_in, so
        # rewriting it would redirect to the wrong records.
        if name == r.new and facts.version < r.changed_in and not r.merge:
            return r.old
    return name


def resolve_field(model: str, field: str, facts: EnvFacts) -> str | None:
    """Return the usable field name, or None if it does not exist on this version."""
    canonical_model = resolve_model(model, facts)
    for r in FIELD_RENAMES:
        if resolve_model(r.model, facts) != canonical_model:
            continue
        if field == r.new and facts.version < r.changed_in:
            return r.old
        if field == r.old and facts.version >= r.changed_in:
            return r.new
    for rem in FIELD_REMOVED:
        if resolve_model(rem.model, facts) != canonical_model:
            continue
        if field == rem.field and facts.series >= rem.removed_in_series:
            return None  # gone on this version
    return field


def resolve_fields(model: str, fields: list[str], facts: EnvFacts) -> FieldResolution:
    mapping: dict[str, str] = {}
    dropped: dict[str, str] = {}
    for f in fields:
        actual = resolve_field(model, f, facts)
        if actual is None:
            dropped[f] = f"field '{f}' is not available on Odoo {facts.raw_version or facts.version}"
        else:
            mapping[f] = actual
    return FieldResolution(mapping=mapping, dropped=dropped)


def _method_delta(method: str) -> MethodDelta | None:
    return next((d for d in METHOD_DELTAS if d.method == method), None)


def method_available(method: str, facts: EnvFacts) -> bool:
    """Whether the ORM method exists on ``facts.series`` (unknown methods: yes)."""
    delta = _method_delta(method)
    if delta is None:
        return True
    if delta.since is not None and facts.series < delta.since:
        return False
    return not (delta.removed_in is not None and facts.series >= delta.removed_in)


def resolve_method(method: str, facts: EnvFacts) -> str:
    """The method the plugin should call for ``method`` on this series.

    ``read_group`` becomes ``formatted_read_group`` from saas~18.4 on. A method
    that is gone becomes its replacement when that one exists; otherwise the
    name is returned unchanged and Odoo reports the error.
    """
    delta = _method_delta(method)
    if delta is None or not delta.use_instead:
        return method
    preferred = delta.prefer_from is not None and facts.series >= delta.prefer_from
    if (preferred or not method_available(method, facts)) and method_available(
            delta.use_instead, facts):
        return delta.use_instead
    return method


def _find_capability(feature: str) -> Capability | None:
    for c in CAPABILITIES:
        if c.feature == feature:
            return c
    return None


def has_capability(feature: str, facts: EnvFacts) -> bool:
    cap = _find_capability(feature)
    if cap is None:
        return True  # unknown feature: assume available, don't block
    too_old = cap.since is not None and facts.version < cap.since
    too_new = cap.until is not None and facts.version > cap.until
    return not (too_old or too_new)


def assert_capability(feature: str, facts: EnvFacts) -> None:
    if not has_capability(feature, facts):
        cap = _find_capability(feature)
        note = cap.note if cap else ""
        raise CompatError(
            f"feature '{feature}' is not available on Odoo {facts.version}",
            remediation=note or "use a supported version or an alternate approach",
        )


def requires_edition(model: str, facts: EnvFacts) -> None:
    """Raise if a model needs Enterprise and edition was detected as community."""
    canonical = resolve_model(model, facts)
    if canonical in ENTERPRISE_ONLY_MODELS and facts.edition == "community":
        raise CompatError(
            f"model '{canonical}' requires Odoo Enterprise",
            remediation="this instance was detected as Community; the model is unavailable",
        )
