# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Cross-version compatibility layer for Odoo 10-19 / CE / EE / online."""

from .detect import EnvFacts, probe
from .resolve import (
    FieldResolution,
    assert_capability,
    has_capability,
    requires_edition,
    resolve_field,
    resolve_fields,
    resolve_model,
)

__all__ = [
    "EnvFacts",
    "FieldResolution",
    "assert_capability",
    "has_capability",
    "probe",
    "requires_edition",
    "resolve_field",
    "resolve_fields",
    "resolve_model",
]
