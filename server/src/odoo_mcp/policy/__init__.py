# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The odoo-tools permission policy: a declarative ceiling on Odoo's own rights.

Four profiles (``readonly``, ``standard`` by default, ``builder``, ``full``),
four sensitive tiers closed by default (``secrets``, ``security``,
``outbound``, ``customization``), a short NEVER list no profile opens, and an
optional JSON file of per-model rules, all decided by one ``Policy.decide()``.

Modules:
  * ``tiers``: the data (tiers, NEVER, delegation, outbound methods, fields);
  * ``classify``: method classes, argument shapes and field paths of a call;
  * ``model``: profiles, rules and the decision;
  * ``loader``: the settings and the file, validated (E1-E20, W1-W7);
  * ``check``: Layer A, a tool call decided from its declared accesses and its
    arguments before any session exists;
  * ``texts``: what the policy tells the agent (refusals, the instructions line,
    the description suffix).

Pure: no Odoo call, no session, and no I/O except reading the policy file once.
"""

from .loader import load_policy
from .model import (
    DEFAULT_PROFILE,
    OPERATIONS,
    PROFILES,
    WRITE_OPERATIONS,
    Decision,
    Policy,
    Profile,
    Rule,
    Touch,
    model_aliases,
)

__all__ = [
    "DEFAULT_PROFILE",
    "OPERATIONS",
    "PROFILES",
    "WRITE_OPERATIONS",
    "Decision",
    "Policy",
    "Profile",
    "Rule",
    "Touch",
    "load_policy",
    "model_aliases",
]
