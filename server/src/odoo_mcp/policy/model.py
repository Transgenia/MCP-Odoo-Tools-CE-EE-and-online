# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The permission policy: profiles, file rules and the one ``decide()``.

The policy is a ceiling on top of the Odoo user's own access rights: it never
grants what Odoo refuses (ACL, record rules and field groups always apply), and
it is never weaker than ODOO_READONLY. A :class:`Policy` is immutable and needs
no session and no Odoo version, so it decides before anything touches Odoo.
``loader.load_policy`` builds one from the settings, and never raises: a policy
that cannot be loaded is *locked*.

In the local (stdio) mode the policy limits what Claude can do through these
tools (mistakes, instructions hidden in data); it does not limit the holder of
the API key, nor an agent with unrestricted shell access on the same machine.
"""

from __future__ import annotations

import datetime
import functools
import hashlib
import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

from ..compat.deltas import MODEL_RENAMES
from ..errors import PolicyDenied
from .classify import is_internal_note, valid_method, valid_model
from .tiers import (
    DELEGATES,
    INSPECT,
    NEVER,
    NOT_WITHHELD,
    NOTE_SUBTYPE,
    OPERATIONS,
    OUTBOUND_METHODS,
    POLICY_ALIASES,
    PSEUDO,
    TIER_NAMES,
    TIERS,
    TIERS_VERSION,
    WITHHELD_FIELD_NAMES,
    WITHHELD_FIELD_PATTERN,
    WITHHELD_MODEL_FIELDS,
    WRITE_OPERATIONS,
    Never,
)

__all__ = [
    "DEFAULT_PROFILE",
    "OPERATIONS",
    "PROFILES",
    "PSEUDO",
    "TIER_WITHHELD",
    "WRITE_OPERATIONS",
    "Decision",
    "Policy",
    "Profile",
    "Rule",
    "Touch",
    "model_aliases",
    "model_tiers",
    "parse_explain",
    "policy_digest",
    "rule_openings",
]


@dataclass(frozen=True)
class Profile:
    name: str
    default: frozenset[str]  # operations on models outside every tier
    tiers: Mapping[str, frozenset[str]] | None  # operations allowed inside each tier; None = off
    # "full": no withheld fields, and no pointer, identity, delegation-link,
    # outbound-method or context rule. NEVER, the name checks and the Layer B
    # envelope stay on in every profile.
    rules_off: bool = False


_READ = frozenset({"read"})
_SEALED = {"secrets": frozenset(), "security": _READ, "outbound": _READ, "customization": _READ}

PROFILES: dict[str, Profile] = {
    "readonly": Profile("readonly", _READ, MappingProxyType(dict(_SEALED))),
    "standard": Profile("standard", frozenset({"read", "create", "write", "call"}),
                        MappingProxyType(dict(_SEALED))),
    # builder equals full for confidentiality: automations run Python on the
    # server, with sudo() available (warning W6).
    "builder": Profile("builder", frozenset({"read", "create", "write", "call", "schema"}),
                       MappingProxyType({**_SEALED, "customization": frozenset(OPERATIONS)})),
    # 1.4 behaviour minus NEVER.
    "full": Profile("full", frozenset(OPERATIONS), None, rules_off=True),
}
DEFAULT_PROFILE = "standard"

# The operations each tier withholds in some profile other than "full". An exact
# entry that sets one of them to an allowance opens it, and needs a reason (E15).
TIER_WITHHELD: dict[str, frozenset[str]] = {
    tier: frozenset().union(*(frozenset(OPERATIONS) - profile.tiers[tier]
                              for profile in PROFILES.values() if profile.tiers is not None))
    for tier in TIER_NAMES
}


@dataclass(frozen=True)
class Touch:
    """One operation on one model, as a tool declares it or a call makes it."""

    op: str  # one of OPERATIONS, or "inspect"
    model: str | None
    method: str | None = None

    def __str__(self) -> str:  # the audit form, op:model[:method]
        text = f"{self.op}:{self.model}"
        return f"{text}:{self.method}" if self.method else text


@dataclass(frozen=True)
class Decision:
    allowed: bool
    # invalid-name, never:<id>, readonly, locked, file:<key>, tier:<name>,
    # outbound-method or profile:<name>
    rule: str
    touch: Touch
    tier: str | None = None  # the tier of a tier:<name> decision
    via: str | None = None  # the alias or delegation parent the decision came from
    relation: str | None = None  # "alias" or "delegation" when via is set
    methods: tuple[str, ...] | None = None  # the method list that refused a call


@dataclass(frozen=True)
class Rule:
    """One entry of the policy file's ``models``, normalised by the loader."""

    key: str  # an exact model name, "prefix.*" or "*"
    ops: tuple[tuple[str, Any], ...]  # (op, True or False); "call" may hold a frozenset
    reason: str = ""
    expires: datetime.date | None = None  # end of that day, UTC

    @property
    def exact(self) -> bool:
        return self.key != "*" and not self.key.endswith(".*")

    @property
    def specificity(self) -> int:
        """Longer prefixes first, ``*`` last."""
        return -1 if self.key == "*" else len(self.key)

    def matches(self, model: str) -> bool:
        if self.key == "*":
            return True
        if self.key.endswith(".*"):
            return model.startswith(self.key[:-1])
        return model == self.key

    def get(self, op: str) -> Any:
        for name, value in self.ops:
            if name == op:
                return value
        return None

    def expired(self, today: datetime.date) -> bool:
        return self.expires is not None and today > self.expires

    def value(self, op: str, today: datetime.date) -> Any:
        """What the entry sets for ``op`` today; ``None`` when it sets nothing.

        Expiry fails closed. After the date a ``true`` is ignored, and a method
        list, which allowed its methods and refused every other one, keeps only
        its refusal: it refuses them all. A ``false`` still applies.
        """
        value = self.get(op)
        if value is None or not self.expired(today):
            return value
        if value is True:
            return None
        return False


@functools.lru_cache(maxsize=4096)
def model_aliases(name: str) -> frozenset[str]:
    """``name`` and every name the policy treats as the same model.

    Symmetric, merges included: a rule on either name of a renamed or merged pair
    (``compat/deltas.py`` MODEL_RENAMES, plus ``base.automation`` and v10's
    ``base.action.rule``) applies to both, on every version. The policy needs no
    version, so it cannot know which name exists on the target.
    """
    out, todo = {name}, [name]
    while todo:
        current = todo.pop()
        linked = set(POLICY_ALIASES.get(current, ()))
        for rename in MODEL_RENAMES:
            if current in (rename.old, rename.new):
                linked |= {rename.old, rename.new}
        for other in linked - out:
            out.add(other)
            todo.append(other)
    return frozenset(out)


@functools.lru_cache(maxsize=4096)
def model_tiers(name: str) -> tuple[str, ...]:
    """The tiers ``name`` itself matches, in severity order (no alias, no delegation)."""
    return tuple(tier.name for tier in TIERS if tier.matches(name))


@functools.lru_cache(maxsize=4096)
def rule_openings(rule: Rule) -> tuple[tuple[str, ...], str | None, tuple[str, ...]]:
    """What an exact entry opens: the tier operations it allows, the first tier
    (in severity order) they belong to, and the outbound methods it lists."""
    if not rule.exact:
        return (), None, ()
    names = model_aliases(rule.key)
    tiers = [tier for tier in TIER_NAMES if any(tier in model_tiers(name) for name in names)]
    ops = []
    for op in OPERATIONS:
        value = rule.get(op)
        allows = value is True or (isinstance(value, frozenset) and bool(value))
        if allows and any(op in TIER_WITHHELD[tier] for tier in tiers):
            ops.append(op)
    tier = next((t for t in tiers if any(op in TIER_WITHHELD[t] for op in ops)), None)
    call = rule.get("call")
    methods = tuple(sorted(call & OUTBOUND_METHODS)) if isinstance(call, frozenset) else ()
    return tuple(ops), tier, methods


def utc_today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


# The arguments of an internal note, to ask whether one would be allowed.
_NOTE_PROBE: Mapping[str, Any] = MappingProxyType(
    {"ids": [1], "args": [], "kwargs": MappingProxyType({"subtype_xmlid": NOTE_SUBTYPE})})


@dataclass(frozen=True)
class Policy:
    """An immutable permission policy: a profile, file rules, the read-only flag."""

    profile_name: str = DEFAULT_PROFILE
    readonly: bool = False
    rules: tuple[Rule, ...] = ()
    withhold: frozenset[str] = frozenset()  # "model.field" or "*.field"
    allow: tuple[tuple[str, str], ...] = ()  # ("model.field", reason), released fields
    disabled: frozenset[str] = frozenset()  # tool names
    source: str | None = None  # the policy file path, None without a file
    warnings: tuple[tuple[str, str], ...] = ()  # (code, text), as loaded
    error: str | None = None  # set when the policy is locked: the E-code text
    error_code: str | None = None
    clock: Callable[[], datetime.date] = field(default=utc_today, compare=False, repr=False)
    # derived in __post_init__
    profile: Profile | None = field(init=False, default=None, compare=False, repr=False)
    _exact: Mapping[str, Rule] = field(init=False, default_factory=dict, compare=False,
                                       repr=False)
    _patterns: tuple[Rule, ...] = field(init=False, default=(), compare=False, repr=False)
    _released: frozenset[str] = field(init=False, default=frozenset(), compare=False,
                                      repr=False)

    def __post_init__(self) -> None:
        profile = PROFILES.get(self.profile_name)
        if profile is None and self.error is None:
            raise ValueError(f"unknown profile {self.profile_name!r} (the loader locks instead)")
        object.__setattr__(self, "profile", profile)
        exact = {rule.key: rule for rule in self.rules if rule.exact}
        patterns = sorted((rule for rule in self.rules if not rule.exact),
                          key=lambda rule: rule.specificity, reverse=True)
        object.__setattr__(self, "_exact", MappingProxyType(exact))
        object.__setattr__(self, "_patterns", tuple(patterns))
        object.__setattr__(self, "_released", frozenset(name for name, _ in self.allow))

    @functools.cached_property
    def digest(self) -> str | None:
        """The policy digest (``policy_digest``); ``None`` while locked."""
        return None if self.error else policy_digest(self)

    @property
    def locked(self) -> bool:
        return self.error is not None

    @classmethod
    def from_settings(cls, settings: Any, tool_names: Iterable[str]) -> Policy:
        """The policy of ``settings`` (profile, file, read-only flag). Never raises."""
        from .loader import load_policy  # the loader builds Policy objects

        return load_policy(settings, tool_names)

    # -- Layer A (policy/check.py) ---------------------------------------------
    def check_tool(self, tool: Any) -> None:
        """Refuse a tool ``tools/list`` hides (locked, unmapped, disabled, read-only,
        a fixed touch refused, an operation allowed nowhere), whatever its arguments."""
        from .check import check_tool

        check_tool(self, tool)

    def check(self, tool: Any, arguments: Mapping[str, Any]) -> Any:
        """Layer A: decide a call from the tool's declared accesses and its arguments
        alone, before any session exists. Returns the call's ``CallScope``; raises
        :class:`~odoo_mcp.errors.PolicyDenied`."""
        from .check import check

        return check(self, tool, arguments)

    # -- decide -----------------------------------------------------------------
    def decide(self, op: str, model: Any, method: str | None = None,
               args: Mapping[str, Any] | None = None) -> Decision:
        """Whether ``op`` on ``model`` (``method`` for a call) is allowed.

        The first step that decides, decides: invalid-name, never:<id>, readonly,
        locked, the exact rule (file:<model>), the tiers (tier:<name>), the
        outbound methods, the most specific pattern (file:<pattern>), the
        profile (profile:<name>). It runs for every name of the model's alias
        closure, and for the delegation parent of every operation but ``read``;
        any refusal wins. ``args`` are the call's arguments in ``odoo_execute``'s
        shape ("args", "kwargs", and "ids" for the ids form); only the
        internal-note allowance of ``message_post`` looks at them.
        """
        if op not in OPERATIONS and op != INSPECT:
            raise ValueError(f"unknown operation {op!r}")
        if not valid_model(model) or (method is not None and not valid_method(method)):
            return Decision(False, "invalid-name", Touch(op, None, None))
        touch = Touch(op, model, method)
        never = _never(op, model, method)
        if never is not None:
            return Decision(False, f"never:{never.id}", touch)
        if self.readonly and op not in ("read", INSPECT):
            return Decision(False, "readonly", touch)
        if self.locked:
            return Decision(False, "locked", touch)
        if op == INSPECT:
            return self._inspect(touch)
        return self._decide(touch, args)

    def _decide(self, touch: Touch, args: Mapping[str, Any] | None) -> Decision:
        model = touch.model
        assert model is not None
        names = (model, *sorted(model_aliases(model) - {model}))
        own: Decision | None = None
        for name in names:
            decision = self._decide_name(touch, name, names, args)
            if not decision.allowed:
                if name != model and decision.via is None:
                    decision = replace(decision, via=name, relation="alias")
                return decision
            if own is None:
                own = decision
        assert own is not None
        if touch.op != "read":
            # Writing a delegating child writes its parent's fields.
            for name in names:
                parent = DELEGATES.get(name)
                if parent is None:
                    continue
                decided = self.decide(touch.op, parent[0], touch.method, args)
                if not decided.allowed:
                    return Decision(False, decided.rule, touch, tier=decided.tier,
                                    via=parent[0], relation="delegation",
                                    methods=decided.methods)
        return own

    def _decide_name(self, touch: Touch, name: str, names: tuple[str, ...],
                     args: Mapping[str, Any] | None) -> Decision:
        profile = self.profile
        assert profile is not None
        op, method = touch.op, touch.method
        exact = self._exact_value(op, method, names)
        if exact is not None:
            state, key, methods = exact
            via, relation = (key, "alias") if key != touch.model else (None, None)
            if state == "deny":
                return Decision(False, f"file:{key}", touch, via=via, relation=relation,
                                methods=methods)
            if state == "open" and self._outbound_refused(method, args):
                return Decision(False, "outbound-method", touch)
            return Decision(True, f"file:{key}", touch, via=via, relation=relation)
        tiers = model_tiers(name)
        if profile.tiers is not None:
            for tier in tiers:
                if op not in profile.tiers[tier]:
                    return Decision(False, f"tier:{tier}", touch, tier=tier)
        if op == "call" and self._outbound_refused(method, args):
            return Decision(False, "outbound-method", touch)
        rule = self._pattern(op, name)
        if rule is not None:
            value = rule.get(op)
            if isinstance(value, frozenset):
                if method in value:
                    return Decision(True, f"file:{rule.key}", touch)
                return Decision(False, f"file:{rule.key}", touch, methods=tuple(sorted(value)))
            return Decision(bool(value), f"file:{rule.key}", touch)
        # A tier model got here because each of its tiers allows the operation.
        granted = (bool(tiers) and profile.tiers is not None) or op in profile.default
        return Decision(granted, f"profile:{profile.name}", touch)

    def _exact_value(self, op: str, method: str | None,
                     names: tuple[str, ...]) -> tuple[str, str, tuple[str, ...] | None] | None:
        """The exact entries of the alias closure that set ``op``, combined:
        ``("deny"|"allow"|"open", key, refusing method list)`` or ``None``.

        A refusal on any name wins. For ``call`` the method must be in every
        list given; a list opens the tiers and the outbound methods it names,
        while ``true`` ("open") opens the tiers but not the outbound methods.
        """
        today = self.clock()
        found = []
        for name in names:
            rule = self._exact.get(name)
            if rule is not None:
                value = rule.value(op, today)
                if value is not None:
                    found.append((name, value))
        if not found:
            return None
        for key, value in found:
            if value is False:
                return "deny", key, None
        if op == "call":
            lists = [(key, value) for key, value in found if isinstance(value, frozenset)]
            for key, value in lists:
                if method not in value:
                    return "deny", key, tuple(sorted(value))
            if lists:
                return "allow", lists[0][0], None
            return "open", found[0][0], None
        return "allow", found[0][0], None

    def _pattern(self, op: str, name: str) -> Rule | None:
        """The most specific pattern entry that sets ``op`` for ``name``."""
        for rule in self._patterns:  # sorted: the longest prefix first, "*" last
            if rule.get(op) is not None and rule.matches(name):
                return rule
        return None

    def _outbound_refused(self, method: str | None, args: Mapping[str, Any] | None) -> bool:
        profile = self.profile
        if profile is None or profile.rules_off or method not in OUTBOUND_METHODS:
            return False
        # an internal note notifies nobody by e-mail
        return not (isinstance(args, Mapping) and is_internal_note(
            method, args.get("args"), args.get("kwargs"), ids_given="ids" in args))

    def _inspect(self, touch: Touch) -> Decision:
        """``inspect`` is allowed wherever any operation is allowed on the model."""
        model = touch.model
        assert model is not None
        for op in OPERATIONS:
            allowing = self._allowed_for(op, model)
            if allowing is not None:
                return Decision(True, allowing.rule, touch, via=allowing.via,
                                relation=allowing.relation)
        basis = self.decide("read", model)
        return Decision(False, basis.rule, touch, tier=basis.tier, via=basis.via,
                        relation=basis.relation)

    def _allowed_for(self, op: str, model: str) -> Decision | None:
        """An allowing decision for some use of ``op`` on ``model``, or ``None``."""
        if op != "call":
            decision = self.decide(op, model)
            return decision if decision.allowed else None
        for method, args in self._call_probes(model):
            decision = self.decide("call", model, method, args)
            if decision.allowed:
                return decision
        return None

    def _call_probes(self, model: str) -> Iterator[tuple[str | None, Mapping[str, Any] | None]]:
        yield None, None  # a business method no rule lists
        yield "message_post", _NOTE_PROBE  # an internal note
        names = model_aliases(model)
        methods = set(OUTBOUND_METHODS)
        for rule in self.rules:
            value = rule.get("call")
            if isinstance(value, frozenset) and any(rule.matches(name) for name in names):
                methods |= value
        for method in sorted(methods):
            yield method, None

    def ops_for(self, model: str) -> frozenset[str]:
        """The operations allowed on ``model`` (``call``: for some method)."""
        return frozenset(op for op in OPERATIONS if self._allowed_for(op, model) is not None)

    # -- tools/list -------------------------------------------------------------
    def allowed_somewhere(self, op: str) -> bool:
        """Whether ``op`` may be allowed on some model. It over-approximates: a
        tool hidden for lack of it is refused for every model."""
        if self.locked or (self.readonly and op not in ("read", INSPECT)):
            return False
        if op == INSPECT:
            return True
        profile = self.profile
        assert profile is not None
        if op in profile.default:
            return True
        if profile.tiers is not None and any(op in ops for ops in profile.tiers.values()):
            return True
        today = self.clock()
        for rule in self.rules:
            value = rule.value(op, today)
            if value is True or (isinstance(value, frozenset) and bool(value)):
                return True
        return False

    def tool_visible(self, tool: Any) -> bool:
        """Whether ``tools/list`` lists ``tool`` (its name, ``read_only`` and ``access``).

        A listed tool may still be refused for a given model; a hidden one is
        refused for every model and method.
        """
        if self.locked:
            return tool.name == "odoo_version"
        access = getattr(tool, "access", None)
        if access is None:  # no permission mapping: fail closed
            return False
        if tool.name in self.disabled:
            return False
        if self.readonly and not tool.read_only:  # the set check_readonly refuses
            return False
        if getattr(access, "degrade", False) or getattr(access, "stub", False):
            return True
        for op, model in getattr(access, "fixed", ()):
            if not self.decide(op, model).allowed:
                return False
        ops = list(getattr(access, "arg_ops", ()))
        if getattr(access, "dynamic", None) is not None:
            ops.append("call")
        return all(op == INSPECT or self.allowed_somewhere(op) for op in ops)

    # -- fields -----------------------------------------------------------------
    def field_withheld(self, model: str, name: str) -> bool:
        """Whether ``model.name`` is withheld: refused wherever a call names it,
        and removed from what a read returns.

        ``fields.withhold`` beats ``fields.allow``, which beats the built-in list
        (credential-like names, the code of automations). Profile ``full`` keeps
        only ``fields.withhold``; ``builder`` releases the automation code.
        """
        name = name.lower()
        names = model_aliases(model) if valid_model(model) else frozenset({model})
        if f"*.{name}" in self.withhold or any(f"{m}.{name}" in self.withhold for m in names):
            return True
        profile = self.profile
        if profile is not None and profile.rules_off:
            return False
        if any(f"{m}.{name}" in self._released for m in names):
            return False
        if any((m, name) in WITHHELD_MODEL_FIELDS for m in names):
            return profile is None or profile.name != "builder"
        return _credential_like(name)

    def field_withheld_everywhere(self, name: str) -> bool:
        """Whether a field named ``name`` is withheld whatever its model is.

        For a later segment of a path (``partner_id.signup_token``), whose model
        is known only from field metadata: a credential-like name that no
        ``fields.allow`` entry releases on any model, or a ``*.field`` entry of
        ``fields.withhold``. What depends on the model is decided once the model
        is known.
        """
        name = name.lower()
        if f"*.{name}" in self.withhold:
            return True
        profile = self.profile
        if profile is not None and profile.rules_off:
            return False
        if any(released.rsplit(".", 1)[-1] == name for released in self._released):
            return False
        return _credential_like(name)

    def field_withheld_by_file(self, model: str, name: str) -> bool:
        """Whether ``fields.withhold`` names ``model.name`` (or ``*.name``)."""
        name = name.lower()
        names = model_aliases(model) if valid_model(model) else frozenset({model})
        return f"*.{name}" in self.withhold or any(f"{m}.{name}" in self.withhold for m in names)

    # -- reporting --------------------------------------------------------------
    def opened_sensitive(self) -> list[dict[str, Any]]:
        """The unexpired exact entries that open a tier operation or an outbound method."""
        today = self.clock()
        out = []
        for rule in self.rules:
            if not rule.exact or rule.expired(today):
                continue
            ops, tier, methods = rule_openings(rule)
            if not ops and not methods:
                continue
            opened = list(ops) + (["call"] if methods and "call" not in ops else [])
            entry: dict[str, Any] = {"model": rule.key, "ops": opened, "tier": tier or "outbound"}
            if methods:
                entry["methods"] = list(methods)
            entry["reason"] = rule.reason
            entry["expires"] = rule.expires.isoformat() if rule.expires else None
            out.append(entry)
        return out

    def describe(self, tools: Iterable[Any] = ()) -> dict[str, Any]:
        """The ``policy`` block of ``odoo_version``; ``tools`` are the registered tools."""
        return {
            "profile": self.profile_name,
            "file": self.source,
            "digest": self.digest,
            "readonly": self.readonly,
            "hidden_tools": [tool.name for tool in tools if not self.tool_visible(tool)],
            "opened_sensitive": self.opened_sensitive(),
            "released_fields": [{"field": name, "reason": reason} for name, reason in self.allow],
            "warnings": [{"code": code, "text": text} for code, text in self.warnings],
            "error": self.error,
            "error_code": self.error_code,
        }

    def explain(self, model: str, op: str, method: str | None = None) -> str:
        """One line for ``--check-policy --explain``, e.g.
        ``res.users write: REFUSED (tier:security)``."""
        decision = self.decide(op, model, method)
        head = f"{model} {op} {method}" if method else f"{model} {op}"
        detail = decision.rule
        if decision.relation == "alias":
            detail += f", alias of {model}"
        elif decision.relation == "delegation":
            detail += f", through {decision.via}, which {model} delegates to"
        return f"{head}: {'ALLOWED' if decision.allowed else 'REFUSED'} ({detail})"

    def lock_error(self) -> PolicyDenied:
        """The refusal every tool except ``odoo_version`` returns while locked."""
        if not self.locked:
            raise ValueError("the policy is not locked")
        if self.error_code == "E1":
            remediation = ("set the option 'Permission profile' to readonly, standard, builder "
                           "or full, then reconnect the server (/mcp in Claude Code).")
        else:
            remediation = ("fix the file or clear the option 'Permission policy file', then "
                           "reconnect the server (/mcp in Claude Code).")
        return PolicyDenied(
            f"odoo-tools is locked: its permission policy could not be loaded ({self.error}). "
            "Every Odoo tool except odoo_version is disabled. Nothing was sent to Odoo.",
            remediation=remediation, rule="locked", layer="tool",
        )


def _credential_like(name: str) -> bool:
    """The built-in list: credential-like names (``name`` is lowercased)."""
    if name in NOT_WITHHELD:
        return False
    return name in WITHHELD_FIELD_NAMES or WITHHELD_FIELD_PATTERN.search(name) is not None


def _never(op: str, model: str, method: str | None) -> Never | None:
    names = model_aliases(model)
    for entry in NEVER:
        if entry.model in names and op in entry.ops and (
                entry.methods is None or method in entry.methods):
            return entry
    return None


def policy_digest(policy: Policy) -> str:
    """The first 12 hex characters of a SHA-256 over what decides: the profile,
    the normalised rules (method lists as sets, expiry dates), the field rules,
    the disabled tools, the read-only flag and ``TIERS_VERSION``. Comments,
    reasons and key order do not change it; any operation value does."""
    rules: dict[str, dict[str, Any]] = {}
    for rule in policy.rules:
        entry = {op: sorted(value) if isinstance(value, frozenset) else value
                 for op, value in rule.ops}
        if rule.expires is not None:
            entry["expires"] = rule.expires.isoformat()
        rules[rule.key] = entry
    document = {
        "profile": policy.profile_name,
        "rules": rules,
        "fields": {"withhold": sorted(policy.withhold),
                   "allow": sorted(name for name, _reason in policy.allow)},
        "disabled": sorted(policy.disabled),
        "readonly": bool(policy.readonly),
        "tiers": TIERS_VERSION,
    }
    text = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def parse_explain(spec: str) -> tuple[str, str, str | None]:
    """``MODEL:OP[:METHOD]`` -> ``(model, op, method)``; ValueError when malformed."""
    parts = spec.split(":")
    if len(parts) not in (2, 3) or not all(parts):
        raise ValueError(f"expected MODEL:OP[:METHOD], got {spec!r}")
    if parts[1] not in OPERATIONS and parts[1] != INSPECT:
        raise ValueError(f"unknown operation {parts[1]!r} (use {', '.join(OPERATIONS)} "
                         f"or {INSPECT})")
    return parts[0], parts[1], parts[2] if len(parts) == 3 else None
