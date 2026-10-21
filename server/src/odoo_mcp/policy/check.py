# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Layer A: a tool call decided from its declared accesses and its arguments alone.

``McpServer.call_tool`` runs it before any session exists, so a refusal here
never signs in, never opens a transport and is never counted as a call. It
checks:

  * the tool itself (``check_tool``): locked, unmapped, disabled, hidden by
    Read-only mode, a fixed touch refused, an operation allowed on no model;
    the same conditions as ``Policy.tool_visible``, so a tool ``tools/list``
    hides is refused when it is called by name;
  * every touch the tool declares (``registry.Access``), with the alias
    closure and the delegation parents ``decide()`` adds, NEVER and the name
    checks, and the internal-note allowance of ``message_post``;
  * what the arguments name, read without any Odoo metadata: withheld fields
    in field lists, values, domains (every segment), groupby, order and
    import columns; the parent model an ``ir.attachment`` search must name;
    the context keys of ``odoo_execute``. What needs field metadata (the
    models a path or an x2many command reaches) is left to the guarded
    session, which sees every actual Odoo call.

A tool declares its accesses with ``registry.Access`` (duck-typed here:
``arg_ops``, ``fixed``, ``optional``, ``dynamic``, ``degrade``,
``columns_arg``, ``stub``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from . import texts
from .classify import (
    COLUMNS,
    DOMAIN,
    FIELD,
    ORDER,
    TERMS,
    VALUES,
    CallArgs,
    ShapeError,
    domain_conjuncts,
    domain_paths,
    extract,
    method_ops,
    named_parts,
    valid_method,
)
from .model import Policy, Touch, model_aliases
from .tiers import INSPECT, SAFE_CONTEXT_KEYS

__all__ = [
    "EFFECTIVE_LIMIT",
    "FIELD_ARGUMENTS",
    "SEARCH_METHODS",
    "CallScope",
    "check",
    "check_attachment_pin",
    "check_context",
    "check_tool",
    "execute_touches",
    "scope_for",
    "touches_for",
]

# The arguments of the dedicated tools that name fields of args["model"], by
# name. "fields" is read as groupby/aggregate terms, which also covers a plain
# field list; an import's columns are named by Access.columns_arg instead, and
# odoo_execute's arguments are read by classify.extract.
FIELD_ARGUMENTS: dict[str, str] = {
    "domain": DOMAIN,
    "filter_domain": DOMAIN,
    "fields": TERMS,
    "groupby": TERMS,
    "order": ORDER,
    "orderby": ORDER,
    "values": VALUES,
    "field": FIELD,
}

# The search-class methods: a generic ir.attachment call of these must name the
# parent model in its domain (design 4.5).
SEARCH_METHODS = frozenset({"search", "search_read", "search_count", "read_group",
                            "formatted_read_group", "web_search_read", "web_read_group",
                            "name_search"})
ATTACHMENT = "ir.attachment"
_PLAIN_VALUE = (str, int, float, bool, type(None))
_FIELD_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}")
EFFECTIVE_LIMIT = 50  # the audit keeps at most 50 effective touches per call


@dataclass
class CallScope:
    """One ``tools/call`` as the policy sees it.

    Layer A fills the first part: the tool, the model the agent chose and the
    touches the tool declared for it (the audit's ``touches``), plus what the
    guarded session (Layer B, ``policy/guard.py``) needs: the policy, the tool's
    ``Access`` and the call's arguments, which only the internal predicates read
    and which are never logged or written anywhere.

    Layer B records the rest while the tool runs: ``effective``, the operations
    it decided on the actual Odoo calls (``op:model[:method]``, the relational
    ones included); ``withheld``, the ``model.field`` names it removed from the
    results; ``n``, the rows read and the records changed; and the ids this call
    created, the ids its searches found and the rows its reads returned, which
    the internal predicates check (an unlink of a wizard this call created, the
    content of an attachment this call showed to be the record's).
    """

    tool: str
    model: str | None = None
    touches: tuple[Touch, ...] = ()
    policy: Policy | None = field(default=None, repr=False, compare=False)
    access: Any = field(default=None, repr=False, compare=False)
    arguments: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)
    effective: list[str] = field(default_factory=list)
    withheld: set[str] = field(default_factory=set)
    n: int = 0
    created: dict[str, list[int]] = field(default_factory=dict, repr=False, compare=False)
    found: dict[str, list[int]] = field(default_factory=dict, repr=False, compare=False)
    records: dict[str, dict[int, dict[str, Any]]] = field(default_factory=dict, repr=False,
                                                          compare=False)

    def touch_strings(self) -> list[str]:
        """The touches in the audit form, ``op:model[:method]``."""
        return [str(touch) for touch in self.touches]

    def record(self, op: str, model: str, method: str | None = None) -> None:
        """Add ``op:model[:method]`` to ``effective`` once (``method`` for a call only)."""
        text = str(Touch(op, model, method if op == "call" else None))
        if text not in self.effective and len(self.effective) < EFFECTIVE_LIMIT:
            self.effective.append(text)

    def annotate(self, result: Any) -> Any:
        """``result`` plus ``policy_withheld_fields`` when the guard removed fields, so
        nothing disappears silently."""
        if self.withheld and isinstance(result, dict):
            return {**result, "policy_withheld_fields": sorted(self.withheld)}
        return result


def execute_touches(arguments: Mapping[str, Any]) -> list[Touch]:
    """``odoo_execute``'s touches: ``call`` for the method on the model, plus the
    operations of the method's class, so ``unlink`` also needs ``unlink`` and
    ``search_read`` also ``read``; NEVER is checked on both."""
    model, method = arguments.get("model"), arguments.get("method")
    touches = [Touch("call", model, method)]
    if valid_method(method):
        ops = method_ops(method)
        if ops != ("call",):
            touches.extend(Touch(op, model) for op in ops)
    return touches


def touches_for(tool: Any, arguments: Mapping[str, Any]) -> list[Touch]:
    """The touches ``tool`` declares for a call with ``arguments``, in order: its
    operations on args["model"], its fixed touches, the optional ones whose
    argument is given, then those ``dynamic`` derives (``odoo_execute``)."""
    access = getattr(tool, "access", None)
    if access is None or access.stub:
        return []
    model = arguments.get("model")
    touches = [Touch(op, model) for op in access.arg_ops]
    touches.extend(Touch(op, name) for op, name in access.fixed)
    for op, argument in access.optional:
        value = arguments.get(argument)
        if isinstance(value, str):
            value = value.strip()  # as the handler reads it
        if value:
            touches.append(Touch(op, value))
    if access.dynamic is not None:
        touches.extend(access.dynamic(dict(arguments)))
    return touches


def check_tool(policy: Policy, tool: Any) -> None:
    """Refuse ``tool`` when ``policy.tool_visible`` hides it, with the reason."""
    if policy.locked:
        if tool.name == "odoo_version":
            return
        raise policy.lock_error()
    access = getattr(tool, "access", None)
    if access is None:
        raise texts.unmapped(tool.name)
    if tool.name in policy.disabled:
        raise texts.disabled(tool.name, policy.source)
    if policy.readonly and not tool.read_only:
        raise texts.read_only_tool(tool.name)
    if access.degrade or access.stub:
        return
    for op, model in access.fixed:
        decision = policy.decide(op, model)
        if not decision.allowed:
            raise texts.refused(policy, decision, layer="tool")
    ops = list(access.arg_ops) + (["call"] if access.dynamic is not None else [])
    for op in ops:
        if op != INSPECT and not policy.allowed_somewhere(op):
            raise texts.hidden(tool.name, policy.profile_name, op)


def scope_for(policy: Policy, tool: Any, arguments: Mapping[str, Any]) -> CallScope:
    """The scope of a call as its tool declares it, before anything is decided."""
    access = getattr(tool, "access", None)
    if access is None or access.stub:
        return CallScope(tool.name, policy=policy, access=access, arguments=dict(arguments))
    takes_model = bool(access.arg_ops) or access.dynamic is not None
    model = arguments.get("model") if takes_model else None
    return CallScope(tool.name, model if isinstance(model, str) else None,
                     tuple(touches_for(tool, arguments)), policy=policy, access=access,
                     arguments=dict(arguments))


def check(policy: Policy, tool: Any, arguments: Mapping[str, Any]) -> CallScope:
    """Layer A for one call; ``check_tool`` has passed. Raises PolicyDenied."""
    if policy.locked:
        if tool.name != "odoo_version":
            raise policy.lock_error()
        return CallScope(tool.name, policy=policy, access=getattr(tool, "access", None))
    access = getattr(tool, "access", None)
    if access is None:
        raise texts.unmapped(tool.name)
    scope = scope_for(policy, tool, arguments)
    if access.stub:
        return scope
    touches = list(scope.touches)
    # A degrading tool runs; a section whose fixed touch is refused degrades.
    sections = set(access.fixed) if access.degrade else set()
    note_args = _execute_args(arguments) if access.dynamic is not None else None
    for touch in touches:
        if touch.method is None and (touch.op, touch.model) in sections:
            continue
        decision = policy.decide(touch.op, touch.model, touch.method,
                                 note_args if touch.op == "call" else None)
        if not decision.allowed:
            if decision.rule == "invalid-name":
                raise texts.invalid_name(policy, touch.op, touch.model)
            raise texts.refused(policy, decision)
    if scope.model is not None:
        _check_arguments(policy, tool, access, scope.model, arguments, touches)
    return scope


def _execute_args(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """odoo_execute's arguments in the shape ``decide()`` reads for an internal note."""
    out: dict[str, Any] = {"args": arguments.get("args") or [],
                           "kwargs": arguments.get("kwargs") or {}}
    if "ids" in arguments:
        out["ids"] = arguments["ids"]
    return out


def _check_arguments(policy: Policy, tool: Any, access: Any, model: str,
                     arguments: Mapping[str, Any], touches: list[Touch]) -> None:
    """Withheld fields, the ir.attachment pin and the context keys, from the arguments."""
    write_op = next((t.op for t in touches if t.model == model
                     and t.op not in ("read", INSPECT, "call")), "write")
    method = arguments.get("method") if access.dynamic is not None else None
    try:
        if method is not None:
            ids = {"ids": arguments["ids"]} if "ids" in arguments else {}
            parts = extract(method, arguments.get("args"), arguments.get("kwargs"), **ids)
        else:
            roles: dict[str, str | None] = dict(FIELD_ARGUMENTS)
            if access.columns_arg:
                roles[access.columns_arg] = COLUMNS
            parts = named_parts(tool.name, arguments, roles)
        contexts = [_context(context, method or tool.name) for context in parts.contexts]
    except ShapeError as exc:
        op = "call" if method is not None else (touches[0].op if touches else "read")
        raise texts.shape(policy, op, model, detail=exc.detail, method=method,
                          tool=tool.name) from None
    _check_fields(policy, model, parts, write_op)
    rules_on = policy.profile is not None and not policy.profile.rules_off
    if rules_on:
        for context in contexts:
            check_context(policy, model, context)
        if ATTACHMENT in model_aliases(model):
            searches = method in SEARCH_METHODS if method is not None else (
                "domain" in tool.input_schema.get("properties", {}) and "read" in access.arg_ops)
            if searches:
                check_attachment_pin(policy, parts.named.get("domain"), method or tool.name)


def _check_fields(policy: Policy, model: str, parts: CallArgs, write_op: str) -> None:
    for path in parts.paths:
        _check_path(policy, "read", model, path, ".")
    for values in parts.values:
        for key in values:
            if policy.field_withheld(model, key):
                raise texts.field(policy, write_op, model, key,
                                  by_file=policy.field_withheld_by_file(model, key))
    for names, _reference in parts.columns:
        _check_path(policy, write_op, model, names, "/")


def _check_path(policy: Policy, op: str, model: str, path: tuple[str, ...], sep: str) -> None:
    """The first segment is a field of ``model``; a later one belongs to a related
    model this layer cannot name, so only what is withheld everywhere is refused."""
    if not path:
        return
    shown = sep.join(path)
    if policy.field_withheld(model, path[0]):
        by_file = policy.field_withheld_by_file(model, path[0]) and len(path) == 1
        raise texts.field(policy, op, model, shown, by_file=by_file)
    for name in path[1:]:
        if policy.field_withheld_everywhere(name):
            raise texts.field(policy, op, model, shown, by_file=f"*.{name.lower()}" in
                              policy.withhold)


def _context(context: Any, label: str) -> Mapping[str, Any]:
    if context is None:
        return {}
    if not isinstance(context, Mapping):
        raise ShapeError(label, "the context is not an object")
    return context


def check_context(policy: Policy, model: str, context: Mapping[str, Any], *, op: str = "call",
                  layer: str = "A") -> None:
    """Every key is a safe one, or ``default_<field>`` with a plain value for a field
    that is not withheld. The keys that silence chatter tracking are refused."""
    for key, value in context.items():
        if not isinstance(key, str):
            raise texts.context(policy, op, model, key, layer=layer)
        if key in SAFE_CONTEXT_KEYS:
            continue
        name = key[len("default_"):]
        if (key.startswith("default_") and _FIELD_NAME.fullmatch(name)
                and isinstance(value, _PLAIN_VALUE) and not policy.field_withheld(model, name)):
            continue
        raise texts.context(policy, op, model, key, layer=layer)


def check_attachment_pin(policy: Policy, domain: Any, label: str, *, layer: str = "A") -> None:
    """A generic ir.attachment search must AND ``res_model = X`` (or ``in [X, ...]``)
    at its top level, with every ``X`` readable (False: an orphan attachment), and
    must not filter on ``res_field``."""
    try:
        if any(path and path[0] == "res_field" for path in domain_paths(domain, method=label)):
            raise texts.attachment_pin(policy, layer=layer)
    except ShapeError:  # the paths were read already; an unreadable domain is not pinned
        raise texts.attachment_pin(policy, layer=layer) from None
    parents = _pinned_parents(domain)
    if parents is None:
        raise texts.attachment_pin(policy, layer=layer)
    for parent in parents:
        if parent is False or parent is None:
            continue
        if not isinstance(parent, str):
            raise texts.attachment_pin(policy, layer=layer)
        decision = policy.decide("read", parent)
        if not decision.allowed:
            if decision.rule == "invalid-name":
                raise texts.invalid_name(policy, "read", parent, layer=layer)
            raise texts.refused(policy, decision, layer=layer)


def _pinned_parents(domain: Any) -> list[Any] | None:
    for term in domain_conjuncts(domain or []) or []:
        if len(term) != 1:
            continue
        leaf = term[0]
        if not (isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == "res_model"):
            continue
        if leaf[1] == "=":
            return [leaf[2]]
        if leaf[1] == "in" and isinstance(leaf[2], (list, tuple)):
            return list(leaf[2])
    return None

