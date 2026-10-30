# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Layer B: the guarded session, the only session a tool handler gets.

``McpServer.call_tool`` wraps the session of every call in a
:class:`GuardedSession` built from the call's ``CallScope`` (what Layer A
granted). Each Odoo call a tool makes then passes these steps before the
transport is touched:

  1. the name checks, for every transport;
  2. the method class (``classify.py``), and the arguments named as Odoo binds
     them (``ARG_SHAPES``);
  3. the envelope: the call is one of the tool's ``registry.Internal`` calls
     and its predicate holds on the actual arguments, or the touches the tool
     declared cover it. Anything else is a bug in odoo-tools and raises
     ``PolicyEnvelopeError``, in every profile;
  4. the decision again, on the actual model (``Policy.decide``), so Layer B
     stands alone even if Layer A was wrong. An internal call is decided by
     ``Policy.decide_internal`` instead: its predicate pins it, and every
     explicit refusal still applies;
  5. the values a write sends: x2many commands expanded to the models they
     create, write, link or delete (design 6.6), withheld keys at any depth,
     the delegation link (4.4), the identity rule (4.6) and the ir.attachment
     rules (4.5);
  6. the paths a call names (domain leaves with any/not any, field lists,
     specifications, export and import columns, groupby, aggregates, order):
     every model a path reaches must allow ``read`` and no segment may be
     withheld; an ir.attachment search must name its parent, and the guard
     adds ``["res_field", "=", False]`` to it;
  7. the context keys, and on Odoo 10 to 12, which also take the context from a
     positional argument, the objects the call passes positionally (design E1): a
     key of such an object passed to a method outside the argument table is a value
     when it is a field of the model, and otherwise a context key the allowlist must
     allow.

Then the call is sent. What it created, found and read is recorded in the
scope for the internal predicates, and withheld fields are removed from what a
read returns (the tool result names them in ``policy_withheld_fields``).

The guard's own Odoo calls are listed in ``SYSTEM_CALLS``: field metadata and
two pre-reads. They return nothing to the agent. The session's sign-in,
``facts()`` and ``module_installed()`` are the session's own (no model of the
agent's choosing) and pass through unchanged.

These views stop a contributor's accidental bypass, not malicious code: Python
cannot sandbox a plugin (SECURITY.md). An AST test enforces the same rule at
review time (``tests/test_policy_mapping.py``).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ..compat.resolve import resolve_model
from ..config import _without_userinfo
from ..errors import AuthError, ConfigError, OdooMcpError, TransportError
from . import texts
from .check import (
    SEARCH_METHODS,
    CallScope,
    check_attachment_pin,
    check_context,
    check_positional_contexts,
    field_or_context_keys,
)
from .classify import (
    ARG_SHAPES,
    CLASS_OPS,
    CREATE_METHODS,
    POSITIONAL_CONTEXT_UNTIL,
    CallArgs,
    ShapeError,
    column_paths,
    domain_paths,
    extract,
    method_class,
    positional_contexts,
    valid_method,
    valid_model,
)
from .model import Policy, model_aliases
from .tiers import ATTACHMENT_STRUCTURAL_FIELDS, DELEGATES, INSPECT, REFERENCE_LINKS

__all__ = [
    "SYSTEM_CALLS",
    "CallView",
    "CredsView",
    "GuardedSession",
    "ManagerView",
    "TransportView",
    "fields_within",
    "found_id",
    "id_list",
    "ids_within",
    "plain",
    "same_model",
    "user_has_group",
]

log = logging.getLogger("odoo_mcp.policy")

# The guard's own calls on the session it wraps: (model, method, what for). They
# are not checked, are not in the scope's "effective" list, and return nothing to
# the agent. A test checks that the guard makes no other unchecked call.
SYSTEM_CALLS: tuple[tuple[str, str, str], ...] = (
    ("*", "fields_get", ("the type, relation and relation_field of the fields a call names, "
                         "to know the models it reaches (cached per session)")),
    ("ir.attachment", "read", ("res_model and res_field of the attachments a call names by "
                               "id (design 4.5)")),
    ("res.partner", "read", "user_ids of the contacts whose e-mail a write changes (design 4.6)"),
)
METADATA_ATTRIBUTES = ("type", "relation", "relation_field")
SYSTEM_METHODS = ("uid", "facts", "version_info", "module_installed", "invalidate_fields")

X2MANY = frozenset({"one2many", "many2many"})
RELATIONAL = frozenset({"many2one"}) | X2MANY
MAX_COMMAND_DEPTH = 4  # nested x2many commands, as classify.MAX_DEPTH for paths
# Read oracles over a field's comodel: their field_name argument names the model
# whose records they enumerate, so reading it must be allowed (design 4.5/6.6).
SEARCH_PANEL_METHODS = frozenset({"search_panel_select_range", "search_panel_select_multi_range"})
ATTACHMENT = "ir.attachment"
PARTNER = "res.partner"
USERS = "res.users"
AUTOMATION = "$automation"  # registry.Internal: base.automation (base.action.rule on 10)
# Fields of ir.attachment that hold the file itself.
CONTENT_FIELDS = frozenset({"datas", "raw", "db_datas"})
# The ir.attachment structural fields the create/write rule (4.5) refuses outright: the
# structural set minus res_model, which is instead required to name a writable parent.
# policy/check.py refuses the same fields as a plain default_<field> (minus res_id, which
# is not structural), so the two paths cannot drift.
ATTACHMENT_REFUSED_FIELDS = ATTACHMENT_STRUCTURAL_FIELDS - frozenset({"res_model"})
# Write-nothing simulation verbs: onchange(values, field_names, field_onchange) saves
# nothing, so the x2many commands in its values are the record's existing lines, not a
# write. The call-class backstop must not expand them as writes or unlinks of the
# comodel (its result is still redacted, so nothing leaks), or previewing a quotation
# that already has lines would be refused under standard (design 4.7 keeps it working).
SIMULATION_METHODS = frozenset({"onchange"})
# The method classes that create records (create, create_write) or may (a business
# method, class call), so Odoo applies the context default_<field> keys to what they create
# (_add_missing_default_values). The structural value rules over the plain defaults run
# only for these classes, decided against the model the call names: on a read a
# default_<field> fills nothing, so applying them there is a false refusal (design 4.11). A
# default whose value is a list or an object never gets this far: check_context refuses it
# on both layers, because Odoo also applies it to the lines and the other models' records a
# call creates, which no check against one model can follow.
DEFAULT_APPLYING_CLASSES = frozenset({"create", "create_write", "call"})
_FIELD = re.compile(r"[A-Za-z0-9_]+")
# A whole string that is a groupby/aggregate term: 'field', 'field:function' or
# 'name:function(source)', dotted paths allowed (classify._TERM, anchored at both
# ends). The field a term reads is its source when present, else its head: so the
# backstop strips a ':count'/':month' suffix before deciding a withheld-field oracle,
# the way the enumerated grouping readers do through the TERMS role (design 4.11).
_TERM_FULL = re.compile(
    r"(?P<head>[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)"
    r"(?::[A-Za-z0-9_]+(?:\((?P<source>[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)\))?)?")
_DOMAIN_OPERATORS = frozenset({"&", "|", "!"})
# The leaf operators of an Odoo domain term. A three-element list is a domain term
# only when its middle element is one of these, so an attachment tuple [name, content,
# info] -- whose middle element is file content, not an operator -- is not mistaken for
# a domain and routed through domain-path analysis (which would read the file name as a
# field path). A real domain whose operator this set omits is still walked term by
# term, where the leaf field is checked, so an incomplete set never leaks.
_TERM_OPERATORS = frozenset({
    "=", "!=", "<>", "<=", "<", ">", ">=", "=?", "=like", "=ilike", "like", "not like",
    "ilike", "not ilike", "in", "not in", "child_of", "parent_of", "any", "not any",
    "any!", "not any!"})
MAX_ARG_DEPTH = 4  # how deep the call-class argument scan walks (as classify.MAX_DEPTH)
# The value types redaction passes through as they are (JSON scalars).
_SCALARS = frozenset({str, int, float, bool, type(None)})


# --- helpers for the internal predicates (tools/*.py) --------------------------------

def _is_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def id_list(value: Any) -> list[int] | None:
    """Record ids as a list (one id or a list of them); None when they are not ids."""
    if _is_id(value):
        return [value]
    if isinstance(value, (list, tuple)) and all(_is_id(item) for item in value):
        return list(value)
    return None


def ids_within(ids: Any, allowed: Iterable[int] | None) -> bool:
    """``ids`` are record ids, at least one, all in ``allowed``."""
    found = id_list(ids)
    return bool(found) and set(found) <= set(allowed or ())


def found_id(value: Any, allowed: Iterable[int] | None) -> bool:
    """``value`` is one record id, in ``allowed``."""
    return _is_id(value) and value in set(allowed or ())


def fields_within(fields: Any, allowed: Iterable[str]) -> bool:
    """An explicit field list, every name in ``allowed`` (no list reads every field)."""
    names = set(allowed)
    return isinstance(fields, (list, tuple)) and all(
        isinstance(name, str) and name in names for name in fields)


def plain(value: Any) -> Any:
    """``value`` with tuples as lists, to compare a domain whatever its container."""
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def same_model(name: Any, scope: CallScope) -> bool:
    """``name`` is the model the agent chose, or a name the policy treats as it (the
    tools resolve it for the target version, e.g. account.invoice on Odoo 17)."""
    return (valid_model(name) and valid_model(scope.model)
            and name in model_aliases(scope.model))


def user_has_group(group: str) -> Callable[[CallView, CallScope], bool]:
    """``res.users.has_group(group)`` about the signed-in user only: a model method up
    to Odoo 17 (no ids), a record method with ``ids=[uid]`` from 18."""

    def check(call: CallView, scope: CallScope) -> bool:
        if call.args != [group] or call.kwargs:
            return False
        return call.ids is None or id_list(call.ids) == [call.uid]

    return check


# --- the views a tool gets ------------------------------------------------------------

class CallView:
    """One actual Odoo call, as an ``Internal`` predicate sees it.

    ``args``, ``kwargs`` and ``ids`` are as the tool passed them (copies);
    ``named`` holds the arguments named as Odoo binds them (``ARG_SHAPES``),
    empty for a method outside that table; ``record_ids`` are the records of a
    record method (``ids=``, or the first positional argument of the legacy
    form). ``uid`` signs in on first use.
    """

    __slots__ = ("_uid", "_values", "args", "ids", "kwargs", "method", "model", "named",
                 "record_ids")

    def __init__(self, model: str, method: str, args: Any, kwargs: Any, ids: Any,
                 parts: CallArgs | None, uid: Callable[[], Any]) -> None:
        self.model = model
        self.method = method
        self.args = list(args) if isinstance(args, (list, tuple)) else []
        self.kwargs = dict(kwargs) if isinstance(kwargs, Mapping) else {}
        self.ids = ids
        self.named = dict(parts.named) if parts is not None else {}
        self.record_ids = ids if ids is not None else (parts.ids if parts is not None else None)
        self._values = [dict(values) for values in parts.values] if parts is not None else []
        self._uid = uid

    @property
    def uid(self) -> Any:
        """The signed-in user's id."""
        return self._uid()

    def values(self) -> list[dict[str, Any]]:
        """The values a create or a write sends, one dict per record ([] for none)."""
        return [dict(values) for values in self._values]


class CredsView:
    """The session's credentials without the secret: url (without user:pass@), db,
    login and the kind of secret (api_key or password)."""

    __slots__ = ("db", "login", "secret_kind", "url")

    def __init__(self, creds: Any) -> None:
        self.url = _without_userinfo(str(getattr(creds, "url", "") or ""))
        self.db = getattr(creds, "db", None)
        self.login = getattr(creds, "login", None)
        self.secret_kind = getattr(creds, "secret_kind", None)


class TransportView:
    """What a tool may read about the session's transport, never a call: the active
    transport, the series, whether JSON-2 is available, the deprecation notice and
    the kind of secret."""

    __slots__ = ("_transport",)

    def __init__(self, transport: Any) -> None:
        self._transport = transport

    @property
    def active(self) -> Any:
        return self._transport.active

    @property
    def series(self) -> Any:
        return self._transport.series

    @property
    def json2_available(self) -> Any:
        return self._transport.json2_available

    @property
    def transport_notice(self) -> Any:
        return self._transport.transport_notice

    @property
    def secret_kind(self) -> Any:
        return self._transport.secret_kind

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f"the transport view exposes no '{name}'")


class ManagerView:
    """The connection manager as a tool sees it: its connections and the call
    counters, never a session (no ``default()`` or ``get()``)."""

    __slots__ = ("_manager",)

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    def connections(self) -> Any:
        return self._manager.connections()

    def tool_calls_snapshot(self) -> Any:
        return self._manager.tool_calls_snapshot()

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f"the connection manager view exposes no '{name}'")


# --- the guarded session ----------------------------------------------------------------

class _Unverified(Exception):
    """The field metadata a check needs could not be read (design 6.6)."""


@dataclass
class _Plan:
    """A call the guard let through: what to send and what to do with the answer."""

    model: str
    method: str
    cls: str
    args: Any
    kwargs: Any
    record_ids: Any = None
    redact: bool = False


def _values_command(item: Any) -> bool:
    """An x2many command that carries the values of a line: (0, _, vals), (1, id, vals)."""
    return (isinstance(item, (list, tuple)) and len(item) == 3 and _is_id(item[0])
            and item[0] in (0, 1) and isinstance(item[2], Mapping))


def _commands(value: Any) -> list[tuple[Any, ...]] | None:
    """The x2many commands of ``value`` as Odoo reads them; None when it cannot be
    read with certainty. ``False``/``None`` clear the field (command 5), a bare id
    list sets it (command 6), and a lone tuple is one command."""
    if value is False or value is None:
        return [(5,)]
    if isinstance(value, tuple):
        value = [value]
    if not isinstance(value, list):
        return None
    if value and not isinstance(value[0], (list, tuple)):
        return [(6, 0, list(value))] if all(_is_id(item) for item in value) else None
    out = []
    for command in value:
        if not isinstance(command, (list, tuple)) or not command or not _is_id(command[0]):
            return None
        number = command[0]
        if number == 0:
            readable = len(command) == 3 and isinstance(command[2], Mapping)
        elif number == 1:
            readable = len(command) == 3 and _is_id(command[1]) and isinstance(command[2], Mapping)
        elif number in (2, 3, 4):
            readable = len(command) in (2, 3) and _is_id(command[1])
        elif number == 5:
            readable = len(command) <= 3
        elif number == 6:
            readable = len(command) == 3 and id_list(command[2]) is not None
        else:
            readable = False
        if not readable:
            return None
        out.append(tuple(command))
    return out


def _domain_shaped(value: Any) -> bool:
    """Whether ``value`` has the shape of a search domain: a non-empty list whose items
    are each a domain operator or a ``[field, operator, value]`` term. It decides whether
    a call-class argument goes through the domain-path analysis, so an ordinary list of
    ids is not mistaken for a domain."""
    if not isinstance(value, (list, tuple)) or not value:
        return False
    for term in value:
        if isinstance(term, str):
            if term not in _DOMAIN_OPERATORS:
                return False
        elif isinstance(term, (list, tuple)) and len(term) == 3:
            left, operator = term[0], term[1]
            # Odoo's TRUE_LEAF (1, '=', 1) and FALSE_LEAF (0, '=', 1): a valid leaf
            # whose left is an int, so a domain carrying one is still a domain and
            # goes through path analysis rather than being walked term by term.
            if isinstance(left, int) and not isinstance(left, bool) and left in (0, 1):
                continue
            # A real domain leaf has a field path on the left and a recognised operator
            # in the middle; a (name, content, info) attachment tuple has file content
            # in the middle, which is no operator, so it is not a domain.
            if not (isinstance(left, str) and isinstance(operator, str)
                    and operator.strip().lower() in _TERM_OPERATORS):
                return False
        else:
            return False
    return True


class GuardedSession:
    """The session a tool handler gets: every Odoo call is checked before it is sent.

    It exposes exactly what the tools use and nothing that reaches Odoo
    unchecked: ``execute``, ``fields_get``, ``name_get`` and ``api_doc`` are
    checked; ``uid``, ``facts()``, ``version_info()``, ``module_installed()`` and
    ``invalidate_fields()`` are the session's own; ``creds`` and ``transport``
    are views without the secret and without any way to call Odoo.
    """

    __slots__ = ("_columns_checked", "_internals", "_meta", "_policy", "_raw", "_scope")

    def __init__(self, raw: Any, scope: CallScope) -> None:
        if not isinstance(scope.policy, Policy):
            raise TypeError("a guarded session needs the CallScope of Layer A (with its policy)")
        self._raw = raw
        self._scope = scope
        self._policy: Policy = scope.policy
        self._internals = tuple(getattr(scope.access, "internal", ()) or ())
        self._meta: dict[str, Mapping[str, Any]] = {}
        # odoo_import_preview: its load() runs inside Odoo, so its columns are
        # checked once, before its first internal call.
        self._columns_checked = not getattr(scope.access, "columns_arg", None)

    # -- the session's own: no model of the agent's choosing ------------------------
    @property
    def uid(self) -> Any:
        """The signed-in user's id; the session signs in on first use."""
        return self._raw.uid

    def facts(self) -> Any:
        return self._raw.facts()

    def version_info(self) -> Any:
        return self._raw.version_info()

    def module_installed(self, name: str) -> bool:
        return self._raw.module_installed(name)

    def invalidate_fields(self, model: str) -> None:
        """Drop the cached field definitions of ``model`` (local only)."""
        self._meta.pop(model, None)
        self._raw.invalidate_fields(model)

    # -- read-only views ------------------------------------------------------------
    @property
    def creds(self) -> CredsView:
        return CredsView(self._raw.creds)

    @property
    def transport(self) -> TransportView:
        return TransportView(self._raw.transport)

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f"GuardedSession exposes no '{name}'")

    # -- checked calls ----------------------------------------------------------------
    def execute(self, model: str, method: str, args: Any = None, kwargs: Any = None, *,
                ids: Any = None, transports: Any = None) -> Any:
        """``model.method(*args, **kwargs)``, checked (module docstring) and then sent
        as the session sends it; withheld fields are removed from a read's result."""
        plan = self._check(model, method, args, kwargs, ids)
        extra: dict[str, Any] = {}
        if ids is not None:
            extra["ids"] = ids
        if transports is not None:
            extra["transports"] = transports
        return self._after(plan, self._raw.execute(model, method, plan.args, plan.kwargs,
                                                   **extra))

    def fields_get(self, model: str, attributes: Any = None) -> Any:
        """Field definitions (``inspect``): definitions, not values, so not redacted."""
        kwargs = {"attributes": attributes} if attributes is not None else {}
        plan = self._check(model, "fields_get", [], kwargs, None)
        return self._after(plan, self._raw.fields_get(model, attributes))

    def name_get(self, model: str, ids: Any) -> Any:
        """``[[id, display name], ...]``: checked as a read of ``display_name``."""
        plan = self._check(model, "read", [ids], {"fields": ["display_name"]}, None)
        return self._after(plan, self._raw.name_get(model, ids))

    def api_doc(self, model: str) -> Any:
        """Odoo's ``/doc-bearer`` catalog of ``model`` (``inspect``)."""
        plan = self._check(model, "api_doc", [], {}, None, cls=INSPECT)
        return self._after(plan, self._raw.api_doc(model))

    # -- the steps ------------------------------------------------------------------------
    def _check(self, model: Any, method: Any, args: Any, kwargs: Any, ids: Any, *,
               cls: str | None = None) -> _Plan:
        try:
            return self._check_call(model, method, args, kwargs, ids, cls)
        except _Unverified:
            cls = cls or method_class(method)
            raise texts.unverified(self._policy, CLASS_OPS[cls][0], model) from None
        except OdooMcpError:  # a refusal, or Odoo's own answer to a pre-read
            raise
        except Exception as exc:  # a bug in the guard: refused, never sent
            log.error("the permission policy could not check a call of %s (%s)",
                      self._scope.tool, type(exc).__name__)
            raise texts.guard_failure(self._scope.tool, type(exc).__name__) from None

    def _check_call(self, model: Any, method: Any, args: Any, kwargs: Any, ids: Any,
                    cls: str | None) -> _Plan:
        policy, scope = self._policy, self._scope
        # 1. the names, for every transport
        if not valid_model(model):
            raise texts.invalid_name(policy, "call", None, layer="B")
        if not valid_method(method):
            raise texts.invalid_name(policy, "call", model, layer="B")
        # 2. the class, and the arguments named as Odoo binds them
        cls = cls or method_class(method)
        shape_error: ShapeError | None = None
        parts: CallArgs | None = None
        try:
            parts = (extract(method, args, kwargs) if ids is None
                     else extract(method, args, kwargs, ids=ids))
        except ShapeError as exc:
            shape_error = exc
        view = CallView(model, method, args, kwargs, ids, parts, lambda: self._raw.uid)
        # 3. the envelope: an internal call whose predicate holds, or a declared touch
        internals = self._internals_for(model, method)
        if internals:
            if not any(self._holds(internal, view) for internal in internals):
                raise texts.envelope(scope.tool, model, method)
            return self._internal(view, cls, parts, shape_error)
        if not self._covered(model, cls, method):
            raise texts.envelope(scope.tool, model, method)
        return self._generic(view, cls, parts, shape_error)

    def _internals_for(self, model: str, method: str) -> list[Any]:
        out = []
        for internal in self._internals:
            target = "base.automation" if internal.model == AUTOMATION else internal.model
            if method in internal.methods and model in model_aliases(target):
                out.append(internal)
        return out

    def _holds(self, internal: Any, view: CallView) -> bool:
        if internal.check is None:
            return True
        try:
            return bool(internal.check(view, self._scope))
        except OdooMcpError:  # signing in for the uid failed: report that
            raise
        except Exception:  # a predicate that cannot read the call does not hold
            return False

    def _covered(self, model: str, cls: str, method: str) -> bool:
        """Whether the touches the tool declared cover a call of this class."""
        names = model_aliases(model)
        own = [touch for touch in self._scope.touches if touch.model in names]
        if cls == INSPECT:  # field metadata is implied by any operation on the model
            return bool(own)
        if cls == "call":
            return any(touch.op == "call" and touch.method == method for touch in own)
        return all(any(touch.op == op for touch in own) for op in CLASS_OPS[cls])

    def _rules_on(self) -> bool:
        profile = self._policy.profile
        return profile is not None and not profile.rules_off

    def _shape(self, op: str, model: str, detail: str, method: str) -> Exception:
        if getattr(self._scope.access, "dynamic", None) is not None:  # odoo_execute
            return texts.shape(self._policy, op, model, detail=detail, method=method, layer="B")
        return texts.shape(self._policy, op, model, detail=detail, tool=self._scope.tool,
                           layer="B")

    def _internal(self, view: CallView, cls: str, parts: CallArgs | None,
                  shape_error: ShapeError | None) -> _Plan:
        """An internal call: its predicate held. Explicit refusals stop it too."""
        policy, scope = self._policy, self._scope
        model, method = view.model, view.method
        ops = CLASS_OPS[cls]
        for op in ops:
            scope.record(op, model, method)
            decision = policy.decide_internal(op, model, method if op == "call" else None)
            if not decision.allowed:
                raise texts.refused(policy, decision, layer="B")
        for touch in scope.touches:  # what the tool declared is still allowed now
            decision = policy.decide(touch.op, touch.model, touch.method)
            if not decision.allowed:
                raise texts.refused(policy, decision, layer="B")
        rules_on = self._rules_on()
        if rules_on:  # 7a. a positional context (Odoo 10 to 12), before the shape as in _generic
            self._check_positional_contexts(model, method, view, cls)
        if shape_error is not None or parts is None:
            detail = shape_error.detail if shape_error is not None else "unreadable"
            raise self._shape(ops[0], model, detail, method)
        if not self._columns_checked:
            self._columns_checked = True
            self._check_tool_columns()
        if rules_on:
            self._check_contexts(model, method, parts, cls)
        if model in model_aliases(ATTACHMENT) and cls == "read":
            self._check_attachment_content(view, parts)
        return _Plan(model, method, cls, view.args, view.kwargs, record_ids=view.record_ids,
                     redact=cls == "read")

    def _generic(self, view: CallView, cls: str, parts: CallArgs | None,
                 shape_error: ShapeError | None) -> _Plan:
        """A call the declared touches cover: decided again, values and paths checked."""
        policy, scope = self._policy, self._scope
        model, method = view.model, view.method
        names = model_aliases(model)
        ops = list(CLASS_OPS[cls])
        if cls != "call" and any(touch.op == "call" and touch.method == method
                                 and touch.model in names for touch in scope.touches):
            ops.append("call")  # odoo_execute: the method itself, as Layer A decided it
        note: dict[str, Any] = {"args": view.args, "kwargs": view.kwargs}
        if view.ids is not None:
            note["ids"] = view.ids
        # 4. decided again, on the actual model
        for op in ops:
            scope.record(op, model, method)
            decision = policy.decide(op, model, method if op == "call" else None,
                                     note if op == "call" else None)
            if not decision.allowed:
                raise texts.refused(policy, decision, layer="B")
        rules_on = self._rules_on()
        # 7a. on Odoo 10 to 12, an object passed positionally may be the context (design E1):
        # checked before the shape, so it is refused as a context there, as at Layer A
        if rules_on:
            self._check_positional_contexts(model, method, view, cls)
        if shape_error is not None or parts is None:
            detail = shape_error.detail if shape_error is not None else "unreadable"
            raise self._shape(ops[0], model, detail, method)
        # 7. the context keys
        if rules_on:
            self._check_contexts(model, method, parts, cls)
        # 6. what the call reads, filters, groups or sorts on
        for path in parts.paths:
            self._check_path(model, method, path)
        if method in SEARCH_PANEL_METHODS:
            self._check_comodel_read(model, method, parts.named.get("field_name"))
        # 5. what it writes
        if parts.values:
            creating = cls == "create" or (method == "web_save" and view.record_ids is None)
            for values in parts.values:
                self._check_values(model, method, values, creating=creating,
                                   ids=view.record_ids, depth=0)
        if parts.columns:
            self._check_columns(model, method, parts.columns, ops[0])
        # A method that stays class "call" has no shape, so nothing above checked its
        # arguments: scan them for a withheld-field oracle before the call is sent.
        if rules_on and cls == "call":
            self._check_call_arguments(model, method, view.args, view.kwargs)
        args, kwargs = view.args, view.kwargs
        if rules_on and ATTACHMENT in names and cls != INSPECT:
            args, kwargs = self._attachment_call(view, cls, parts, args, kwargs, ops[0])
        # Redaction is a backstop on every result but the inspect class, not only the
        # read classes: a value-returning method left in the "call" class (onchange,
        # and any method Odoo adds later) must not be a door around the withheld-field
        # rule. It only removes withheld keys, so a result without any is unchanged.
        # inspect is excluded because fields_get and get_views return field
        # DEFINITIONS keyed by name, not values: those are not redacted (design 6.3).
        return _Plan(model, method, cls, args, kwargs, record_ids=view.record_ids,
                     redact=cls != INSPECT)

    # -- 7. context ---------------------------------------------------------------------
    def _check_contexts(self, model: str, method: str, parts: CallArgs, cls: str) -> None:
        op = CLASS_OPS[cls][0]
        for context in parts.contexts:
            if context is None:
                continue
            if not isinstance(context, Mapping):
                raise self._shape(op, model, "the context is not an object", method)
            # The same check as Layer A, on the actual call: a key outside the allowlist, a
            # withheld default and a default holding a list or an object are refused here
            # too, so Layer B stands alone (defense in depth).
            check_context(self._policy, model, context, op=op, layer="B")
            self._check_context_defaults(model, context, cls)

    def _check_positional_contexts(self, model: str, method: str, view: CallView,
                                   cls: str) -> None:
        """Odoo 10 to 12 also take a call's context from a positional argument, the one after
        the method's own parameters (design E1). On those series the objects of the actual
        call that may be its context (a Mapping, or a list of pairs, as the dict Odoo builds
        from it) meet the same rules as at Layer A
        (``check_positional_contexts``), as a backstop, and the metadata-free structural rules
        over their ``default_<field>`` keys that a named context meets here. The other keys of
        an object passed to a method outside the argument table are then decided with the
        model's fields (``_check_positional_keys``), last, so a call those rules refuse costs
        no field lookup. From 13 Odoo reads only ``kwargs["context"]``, so the positional
        objects are values, checked as before. The caller has checked ``rules_on``."""
        found = positional_contexts(method, view.args, ids_given=view.ids is not None)
        if not (found.certain or found.possible) or not self._reads_positional_context():
            return
        op = CLASS_OPS[cls][0]
        check_positional_contexts(self._policy, model, found, op=op, layer="B")
        for context in (*found.certain, *found.possible):
            self._check_context_defaults(model, context, cls)
        self._check_positional_keys(model, found.possible, op)

    def _check_positional_keys(self, model: str, possible: Iterable[Mapping[Any, Any]],
                               op: str) -> None:
        """On Odoo 10 to 12, an object passed positionally to a method outside the argument
        table may be the call's context or the method's values (design E1). Its
        ``default_<field>`` keys met the context rules already, and an allowed context key
        passes either way; every other text key (``field_or_context_keys``) is decided by the
        model's fields. A field of the model is one of the method's values, left to the checks
        the method's arguments get, as before (for a business method, the call-class backstop:
        a withheld field, the models its x2many commands reach). Any other key can only be a
        context key, and one outside the allowlist (``tracking_disable``, say) is refused with
        rule ``context``, naming the key, never its value.

        The fields are the metadata the other checks read (``_fields``: cached by the session
        and for this call, and read again by the backstop at no cost), and only when such a
        key is present. When they cannot be read the call is refused with rule ``unverified``,
        as every check that needs field metadata is: an unknown key is never let through."""
        keys = [key for value in possible for key in field_or_context_keys(value)]
        if not keys:
            return
        try:
            fields = self._fields(model)
        except _Unverified:
            raise texts.unverified(self._policy, op, model, positional=True) from None
        for key in keys:
            if key not in fields:
                raise texts.context_not_field(self._policy, op, model, key)

    def _reads_positional_context(self) -> bool:
        """Whether the connected Odoo takes a context from a positional argument: 10 to 12
        (``classify.POSITIONAL_CONTEXT_UNTIL``). A series the session cannot tell counts as
        one, so the check runs (fail closed)."""
        version = getattr(self._raw.facts(), "version", None)
        if not isinstance(version, int) or isinstance(version, bool):
            return True
        return version <= POSITIONAL_CONTEXT_UNTIL

    def _check_context_defaults(self, model: str, context: Mapping[str, Any],
                                cls: str) -> None:
        """A plain ``default_<field>`` context key fills a field of the record this call
        creates, so Odoo applies it exactly as the same key in ``values`` would
        (``_add_missing_default_values``, design 6.5/6.6): the metadata-free structural value
        rules -- the delegation link (4.4) and the ir.attachment create rules (4.5:
        public/res_field/res_model) -- run over the defaults, against the model the call
        names, for a class that creates records (``DEFAULT_APPLYING_CLASSES``); on a read a
        default fills nothing, so applying them there would be a false refusal.

        ``check_context`` (run first, on both layers) has already refused a default whose
        value is a list or an object, and a scalar default naming a sensitive delegation link,
        ``public`` or ``res_field`` on a creating call (``STRUCTURAL_DEFAULT_FIELDS``),
        whatever model the call names. What this adds is the check that only metadata here can
        make: a ``default_res_model`` on a direct create of the attachment, or of a child that
        delegates to it, must name a parent the agent may ``write`` (``default_res_model`` and
        ``default_res_id`` stay allowed as keys, so a nested attachment bound through them is
        an accepted limit). The caller has checked ``rules_on``."""
        if cls not in DEFAULT_APPLYING_CLASSES:
            return
        defaults = {key[len("default_"):]: value for key, value in context.items()
                    if isinstance(key, str) and key.startswith("default_")}
        if defaults:
            self._check_structural_values(model, "create", defaults)

    # -- field metadata -----------------------------------------------------------------
    def _fields(self, model: str) -> Mapping[str, Any]:
        """The type, relation and relation_field of ``model``'s fields (a system call,
        cached by the session for its TTL and here for the call)."""
        meta = self._meta.get(model)
        if meta is None:
            try:
                meta = self._raw.fields_get(model, list(METADATA_ATTRIBUTES))
            except (AuthError, ConfigError, TransportError):  # the connection: say so
                raise
            except Exception:
                raise _Unverified() from None
            if not isinstance(meta, Mapping):
                raise _Unverified()
            self._meta[model] = meta
        return meta

    def _relation(self, model: str, name: str) -> tuple[str, str] | None:
        """``(type, comodel)`` of a relational field of ``model``; None for any other
        field, or one fields_get does not know (Odoo refuses it)."""
        info = self._fields(model).get(name)
        if not isinstance(info, Mapping) or info.get("type") not in RELATIONAL:
            return None
        comodel = info.get("relation")
        if not valid_model(comodel):
            raise _Unverified()
        return str(info["type"]), comodel

    # -- 6. paths -----------------------------------------------------------------------
    def _check_path(self, model: str, method: str, path: tuple[str, ...]) -> None:
        """Every segment is a field of the model the previous one reached: withheld
        names are refused, and each model reached must allow ``read``."""
        policy, shown, current = self._policy, ".".join(path), model
        for index, name in enumerate(path):
            if policy.field_withheld(current, name):
                raise texts.field(policy, "read", model, shown,
                                  by_file=policy.field_withheld_by_file(current, name),
                                  layer="B")
            if index == len(path) - 1:
                return
            relation = self._relation(current, name)
            if relation is None:  # a plain field: Odoo reads a property or refuses
                return
            current = relation[1]
            self._effect("read", model, method, current, shown)

    def _effect(self, op: str, model: str, method: str, comodel: str, shown: str) -> None:
        self._scope.record(op, comodel)
        decision = self._policy.decide(op, comodel)
        if not decision.allowed:
            raise texts.path(self._policy, method=method, model=model, op=op, comodel=comodel,
                             field_path=shown, rule=texts.rule_text(decision))

    def _check_comodel_read(self, model: str, method: str, field_name: Any) -> None:
        """A search_panel read enumerates the records of ``field_name``'s comodel, so
        reading that comodel must be allowed, exactly as a domain hop into it would be
        (design 4.5): a relational field to a secrets-tier model is refused."""
        if not isinstance(field_name, str) or not _FIELD.fullmatch(field_name):
            return
        relation = self._relation(model, field_name)
        if relation is not None:
            self._effect("read", model, method, relation[1], field_name)

    # -- 6b. call-class backstop: the withheld-field oracle on an unlisted reader -------
    def _check_call_arguments(self, model: str, method: str, args: Any, kwargs: Any) -> None:
        """A method that stays class ``call`` (a business verb, or a method no inventory
        lists) has no argument shape, so nothing checks what it names. A reader Odoo
        adds later, or a module-specific one, could still carry a withheld-field oracle
        or a dotted path that hops a read into a sealed model, and a module-specific
        writer could set a withheld field named as a values key. This walks the
        arguments (never the context, which ``check_context`` governs) and refuses such
        a value before the call is sent, using field metadata so that only a string that
        is REALLY a field of the model, a values key that is really a field, or a domain
        is checked: an ordinary business verb -- ids, a plain context, a message body, a
        subject, an attachment file name, a status word -- passes untouched, because the
        design keeps the business verbs (``action_confirm``, ``action_post``,
        ``button_*``) and internal notes working under ``standard``."""
        for value in args if isinstance(args, (list, tuple)) else ():
            self._scan_call_value(model, method, value, 0)
        if isinstance(kwargs, Mapping):
            for key, value in kwargs.items():
                if key != "context":
                    self._scan_call_value(model, method, value, 0)

    def _scan_call_value(self, model: str, method: str, value: Any, depth: int) -> None:
        """A string is checked as a field reference (only a real field of the model is
        refused); a Mapping may be a values dict, whose keys are checked as write field
        names and whose x2many commands are expanded; a domain-shaped list goes through
        the read-path analysis instead of being walked term by term, so the value a term
        compares against is not mistaken for a field reference."""
        if depth > MAX_ARG_DEPTH:
            return
        if isinstance(value, str):
            self._check_field_name(model, method, value)
        elif isinstance(value, Mapping):
            self._scan_call_mapping(model, method, value, depth)
        elif isinstance(value, (list, tuple)):
            if _domain_shaped(value):
                self._check_domain_argument(model, method, value)
            else:
                for item in value:
                    self._scan_call_value(model, method, item, depth + 1)

    def _scan_call_mapping(self, model: str, method: str, mapping: Mapping[str, Any],
                           depth: int) -> None:
        """A Mapping argument of a call-class method may be the values of a module-specific
        writer (``action_apply(vals)``, ``set_values(vals)``): a key that is a withheld
        field of the model is refused -- setting ``signup_token`` is an account-takeover
        primitive, which ``odoo_write`` already refuses -- and a key that is an x2many
        field carrying commands is expanded to the models those commands create, write,
        link or delete (design 6.6), exactly as a real write is. A key that is not a
        field of the model (a nested options dict, a read specification) is not a write,
        so its value is scanned on; without field metadata nothing is treated as a field.

        A simulation verb (``onchange``) saves nothing, so its values dict is not a write:
        its keys are not refused and its x2many commands are not expanded as writes or
        unlinks of the comodel (the record's existing lines ride those commands). Its
        values are scanned on for an oracle, and its result is redacted like a read's."""
        if method in SIMULATION_METHODS:
            for value in mapping.values():
                self._scan_call_value(model, method, value, depth + 1)
            return
        try:
            meta = self._fields(model)
        except _Unverified:
            meta = None
        for key, value in mapping.items():
            if meta is not None and isinstance(key, str) and key in meta:
                if self._policy.field_withheld(model, key):
                    raise texts.field(self._policy, "write", model, key,
                                      by_file=self._policy.field_withheld_by_file(model, key),
                                      layer="B")
                info = meta[key]
                if (isinstance(info, Mapping) and info.get("type") in X2MANY
                        and isinstance(value, (list, tuple))):
                    comodel = info.get("relation")
                    if not valid_model(comodel):
                        raise _Unverified()
                    # Hand the list to the same _check_commands a values key takes: a
                    # recognised write command is decided against the comodel, and a list
                    # that is not a clean command list fails closed with rule shape, so a
                    # mixed command/id list cannot slip past as a plain nested value.
                    self._check_commands(model, method, key, str(info["type"]), comodel,
                                         value, creating=False, depth=0)
                    continue
            self._scan_call_value(model, method, value, depth + 1)

    def _check_field_name(self, model: str, method: str, text: str) -> None:
        """A string argument of a call-class method that names a real field path of the
        model -- its first segment a field of the model -- is checked as a read of that
        path, so a withheld segment and a dotted leaf that hops into a sealed comodel are
        both refused (design 4.11 / 6.6), through the same ``_check_path`` a read's domain
        uses. The string is read as a groupby/aggregate term first, so a field carried
        with a ':function'/':granularity' suffix ('signup_token:count') or inside an
        aggregate ('name:sum(signup_token)') is checked on the field it reads, exactly as
        the enumerated grouping readers do (a bare path is a term with no suffix). A
        string that is NOT a field of the model (a message body, a subject, an attachment
        file name, a status word, an operator, an xmlid) is not a field reference and is
        left alone, so an internal note and a business verb with a plain word argument
        still run. Without field metadata nothing is treated as a field."""
        if not isinstance(text, str):
            return
        match = _TERM_FULL.fullmatch(text)
        if match is None:
            return
        source, head = match.group("source"), match.group("head")
        ref = source if source is not None else (head if head != "__count" else None)
        if ref is None:
            return
        try:
            meta = self._fields(model)
        except _Unverified:
            return
        path = tuple(ref.split("."))
        if path[0] in meta:
            self._check_path(model, method, path)

    def _check_domain_argument(self, model: str, method: str, value: Any) -> None:
        """A domain-shaped argument: run the same read-path analysis a read's domain gets,
        so a withheld leaf and a dotted leaf that reaches a tier model are both refused.
        When the value only looks like a domain (``domain_paths`` cannot read it), fall
        back to checking the field each top-level term names."""
        try:
            paths = domain_paths(value, method=method)
        except ShapeError:
            for term in value:
                if (isinstance(term, (list, tuple)) and len(term) == 3
                        and isinstance(term[0], str)):
                    self._check_field_name(model, method, term[0])
            return
        for path in paths:
            self._check_path(model, method, path)

    def _link_op(self, model: str, field: str, comodel: str) -> str:
        """The effect a many2many link ``model.field`` -> ``comodel`` has on the comodel.

        A link changes the relation, not the linked records, so it is a ``read`` of the
        comodel when the comodel may be written anyway (or only the profile default
        refuses it). When a tier or a file rule withholds writing the comodel, the link
        is treated as a ``write`` on it -- a privilege link such as a user's groups or a
        company's users -- UNLESS ``(model, field)`` is a known reference link
        (``project.task.user_ids``, a helpdesk team's members), which only assigns the
        target and changes no field of it: that is a read. The owner, not the comodel,
        tells an assignment from a privilege, since both point at the same security-tier
        model (design 6.6)."""
        decision = self._policy.decide("write", comodel)
        if decision.allowed or decision.rule.startswith("profile:"):
            return "read"
        if any((name, field) in REFERENCE_LINKS for name in model_aliases(model)):
            return "read"
        return "write"

    # -- 5. values ------------------------------------------------------------------------
    def _check_values(self, model: str, method: str, values: Any, *, creating: bool,
                      ids: Any, depth: int) -> None:
        policy = self._policy
        op = "create" if creating else "write"
        if not isinstance(values, Mapping) or not all(
                isinstance(key, str) and _FIELD.fullmatch(key) for key in values):
            raise self._shape(op, model, "a values key is not a field name", method)
        for key in values:
            if policy.field_withheld(model, key):
                raise texts.field(policy, op, model, key,
                                  by_file=policy.field_withheld_by_file(model, key), layer="B")
        rules_on = self._rules_on()
        if rules_on:
            self._check_structural_values(model, op, values)
        for key, value in values.items():
            if not (isinstance(value, (list, tuple))
                    or (not creating and (value is None or value is False))):
                continue
            info = self._fields(model).get(key)
            if not isinstance(info, Mapping):
                if isinstance(value, (list, tuple)):  # commands for a field Odoo may not have
                    raise self._shape(op, model, f"field '{key}' is unknown to fields_get and "
                                      "carries a list", method)
                continue
            if info.get("type") not in X2MANY:
                continue
            comodel = info.get("relation")
            if not valid_model(comodel):
                raise _Unverified()
            self._check_commands(model, method, key, str(info["type"]), comodel, value,
                                 creating=creating, depth=depth)
        # last: the one check here that reads Odoo (a pre-read of user_ids)
        if rules_on and not creating and "email" in values and PARTNER in model_aliases(model):
            self._check_identity(ids, model, method, op)

    def _check_commands(self, model: str, method: str, field: str, ftype: str, comodel: str,
                        value: Any, *, creating: bool, depth: int) -> None:
        """Design 6.6: what each x2many command does to the comodel."""
        op = "create" if creating else "write"
        if depth >= MAX_COMMAND_DEPTH:
            raise self._shape(op, model, "x2many commands nest too deeply", method)
        commands = _commands(value)
        if commands is None:
            raise self._shape(op, model, f"the value of field '{field}' is not a list of "
                              "x2many commands", method)
        rules_on = self._rules_on()
        for command in commands:
            number = command[0]
            if number == 0:
                effects, existing = ["create"], None
            elif number == 1:
                effects, existing = ["write"], [command[1]]
            elif number == 2:
                effects, existing = ["unlink"], [command[1]]
            elif ftype == "many2many":  # 3, 4, 5, 6: links
                effects = [self._link_op(model, field, comodel)]
                existing = ([command[1]] if number in (3, 4)
                            else list(command[2]) if number == 6 else None)
            elif number == 4:  # one2many: re-parents the line
                effects, existing = ["write"], [command[1]]
            else:  # one2many 3, 5, 6: a write deletes the lines it removes (cascade)
                effects = ["write" if creating else "unlink"]
                existing = [command[1]] if number == 3 else (
                    list(command[2]) if number == 6 else None)
            for effect in effects:
                self._scope.record(effect, comodel)
                decision = self._policy.decide(effect, comodel)
                if not decision.allowed:
                    raise texts.relational(self._policy, method=method, model=model,
                                           op=effect, comodel=comodel, field=field,
                                           command=number, rule=texts.rule_text(decision))
            if rules_on and existing and ATTACHMENT in model_aliases(comodel):
                self._check_attachment_ids(existing, "write", comodel, method)
            if number in (0, 1):
                self._check_values(comodel, method, command[2], creating=number == 0,
                                   ids=[command[1]] if number == 1 else None, depth=depth + 1)

    def _check_structural_values(self, model: str, op: str, values: Mapping[str, Any]) -> None:
        """The metadata-free structural value rules, applied to a ``values`` dict and to
        the plain ``default_<field>`` values a context supplies alike (design 4.4, 4.5): the
        link field of a delegating child cannot be set (``product.document.ir_attachment_id``
        re-points the child at an existing attachment and exposes its content), and an
        ir.attachment -- or a child that delegates to it -- is never created public, as a
        field attachment, or on a model the policy does not let the agent write. Odoo
        applies ``default_<field>`` on create exactly as a value, so the identical setting
        through the context must meet the same rules as through ``values`` (6.5 step 5/7);
        running both from here keeps the two paths from drifting apart. The caller has
        checked ``rules_on``."""
        self._check_delegation_link(model, op, values)
        if self._reaches_attachment(model):
            self._check_attachment_values(op, values)

    def _check_delegation_link(self, model: str, op: str, values: Mapping[str, Any]) -> None:
        """4.4: the link field of a delegating child cannot be set through the tools."""
        for name in model_aliases(model):
            parent = DELEGATES.get(name)
            if parent is not None and parent[1] in values:
                raise texts.delegation_link(self._policy, op, model, parent[1], parent[0],
                                            layer="B")

    def _reaches_attachment(self, model: str) -> bool:
        """Whether a write on ``model`` writes ir.attachment: the model itself, or a
        child that delegates (_inherits) to ir.attachment (product.document,
        documents.document), whose inherited public/res_field/datas are the parent's
        (design 4.5, 4.4). Keying the attachment-value rules off model_aliases alone
        missed the delegates, since a model's aliases do not include its parent."""
        names = model_aliases(model)
        if ATTACHMENT in names:
            return True
        return any((DELEGATES.get(name) or (None, None))[0] == ATTACHMENT for name in names)

    def _check_identity(self, ids: Any, model: str, method: str, op: str) -> None:
        """4.6: a contact that is a user's login identity keeps its e-mail unless the
        policy lets the agent change users."""
        if self._policy.decide("write", USERS).allowed:
            return
        partners = id_list(ids)
        if partners is None:
            raise self._shape(op, model, "the records of this write are not ids", method)
        if not partners:
            return
        rows = self._raw.execute(PARTNER, "read", [partners],
                                 {"fields": ["user_ids"], "context": {"active_test": False}})
        for row in rows or []:
            if isinstance(row, Mapping) and row.get("user_ids"):
                partner = row.get("id") if _is_id(row.get("id")) else partners[0]
                raise texts.identity(self._policy, partner, layer="B")

    # -- imports ------------------------------------------------------------------------
    def _check_columns(self, model: str, method: str,
                       columns: list[tuple[tuple[str, ...], bool]], op: str) -> None:
        """load() columns (6.6): each segment a field of the model the previous one
        reached; lines an import creates or updates need create and write there, a
        link needs read (or write, for a security model's many2many)."""
        policy = self._policy
        rules_on = self._rules_on()
        upserted: dict[tuple[str, ...], str] = {(): model}
        for names, reference in columns:
            shown = "/".join(names) or "id"
            current = model
            for index, name in enumerate(names):
                if policy.field_withheld(current, name):
                    raise texts.field(policy, op, model, shown,
                                      by_file=policy.field_withheld_by_file(current, name),
                                      layer="B")
                if rules_on:
                    self._check_delegation_link(current, op, {name: None})
                relation = self._relation(current, name)
                if relation is None:
                    break
                ftype, comodel = relation
                last = index == len(names) - 1
                if not last or ftype == "one2many":  # lines created or updated there
                    effects = ["create", "write"]
                    upserted[names[:index + 1]] = comodel
                elif ftype == "many2many":
                    effects = [self._link_op(current, name, comodel)]
                else:  # a many2one, by name, external id or database id
                    effects = ["read"]
                for effect in effects:
                    self._effect(effect, model, method, comodel, shown)
                current = comodel
        if rules_on and not policy.decide("write", USERS).allowed:
            references = {names for names, reference in columns if reference}
            plain_columns = {names for names, reference in columns if not reference}
            for prefix, target in upserted.items():
                if (PARTNER in model_aliases(target) and prefix in references
                        and prefix + ("email",) in plain_columns):
                    raise texts.identity_import(policy, target)

    def _check_tool_columns(self) -> None:
        """odoo_import_preview: the columns its dry run hands to Odoo's importer."""
        scope = self._scope
        columns_arg = getattr(scope.access, "columns_arg", None)
        if not columns_arg or not valid_model(scope.model):
            return
        try:
            columns = column_paths(scope.arguments.get(columns_arg), method=scope.tool)
        except ShapeError as exc:
            raise self._shape("create", scope.model, exc.detail, "load") from None
        model = resolve_model(scope.model, self._raw.facts())
        self._check_columns(model, "load", columns, "create")

    # -- 4.5: ir.attachment -------------------------------------------------------------
    def _attachment_call(self, view: CallView, cls: str, parts: CallArgs, args: Any,
                         kwargs: Any, op: str) -> tuple[Any, Any]:
        """A generic call on ir.attachment, outside profile full: a search names the
        parent model (``res_field = False`` is added), a call by ids is pre-read."""
        method = view.method
        if method in SEARCH_METHODS:
            domain = parts.named.get("domain")
            check_attachment_pin(self._policy, domain, method, layer="B")
            return self._pinned(method, args, kwargs, domain)
        if view.record_ids is not None:
            self._check_attachment_ids(view.record_ids, "read" if cls == "read" else "write",
                                       view.model, method)
        elif cls == "call" and view.args:
            raise self._shape(op, view.model, "pass the records of a method on ir.attachment "
                              "in 'ids'", method)
        return args, kwargs

    @staticmethod
    def _pinned(method: str, args: Any, kwargs: Any, domain: Any) -> tuple[Any, Any]:
        """The arguments with ``["res_field", "=", False]`` added to the domain, which
        is what Odoo itself does unless a domain names id or res_field."""
        pinned = [["res_field", "=", False], *list(domain)]
        args = list(args or [])
        kwargs = dict(kwargs or {})
        for key in ("domain", "args"):  # by name; "args" is the older keyword
            if key in kwargs:
                kwargs[key] = pinned
                return args, kwargs
        index = next(i for i, (name, _role) in enumerate(ARG_SHAPES[method].params)
                     if name == "domain")
        args[index] = pinned
        return args, kwargs

    def _check_attachment_ids(self, ids: Any, op: str, model: str, method: str) -> None:
        """4.5, by ids: every attachment stores no field of a record, and belongs to a
        model the policy lets the agent ``op`` (read; write for any change)."""
        attachments = id_list(ids)
        if attachments is None:
            raise self._shape(op, model, "the records of a call on ir.attachment are not ids",
                              method)
        if not attachments:
            return
        rows = self._raw.execute(ATTACHMENT, "read", [attachments],
                                 {"fields": ["res_model", "res_field"]})
        by_id = {row.get("id"): row for row in rows or [] if isinstance(row, Mapping)}
        for attachment_id in attachments:
            row = by_id.get(attachment_id)
            if row is None or row.get("res_field"):
                raise texts.attachment_field(self._policy, op, attachment_id, layer="B")
            parent = row.get("res_model")
            if parent and not (valid_model(parent) and self._policy.decide(op, parent).allowed):
                raise texts.attachment_field(self._policy, op, attachment_id, layer="B")

    def _check_attachment_values(self, op: str, values: Mapping[str, Any]) -> None:
        """4.5, create and write: never public, never a field of a record, and the
        parent model must allow write."""
        if any(values.get(name) for name in ATTACHMENT_REFUSED_FIELDS):
            raise texts.attachment_create(self._policy, op)
        parent = values.get("res_model")
        if parent:
            decision = self._policy.decide("write", parent)
            if not decision.allowed:
                if decision.rule == "invalid-name":
                    raise texts.invalid_name(self._policy, "write", parent, layer="B")
                raise texts.refused(self._policy, decision, layer="B")

    def _check_attachment_content(self, view: CallView, parts: CallArgs) -> None:
        """An internal read of an attachment's file (odoo_record_documents): its
        predicate showed it belongs to the record; the file must not be a withheld
        field of that record (a key or a certificate stored in a binary field)."""
        policy = self._policy
        if not self._rules_on() and not policy.withhold:
            return
        fields = parts.named.get("fields")
        if isinstance(fields, (list, tuple)) and not CONTENT_FIELDS & set(fields):
            return
        attachments = id_list(view.record_ids) or []
        if not attachments:
            return
        rows = self._raw.execute(ATTACHMENT, "read", [attachments],
                                 {"fields": ["res_model", "res_field"]})
        for row in rows or []:
            if not isinstance(row, Mapping):
                continue
            parent, stored = row.get("res_model"), row.get("res_field")
            if stored and (not valid_model(parent) or not isinstance(stored, str)
                           or policy.field_withheld(parent, stored)):
                raise texts.attachment_field(policy, "read", row.get("id")
                                             if _is_id(row.get("id")) else attachments[0],
                                             layer="B")

    # -- after the call ---------------------------------------------------------------------
    def _after(self, plan: _Plan, result: Any) -> Any:
        """Redact what a read returns, and record what the call created, found and
        read for the internal predicates of the calls that follow."""
        scope = self._scope
        if plan.redact and (self._rules_on() or self._policy.withhold):
            result = self._redact(plan.model, plan.method, result)
        method = plan.method
        if method in CREATE_METHODS:
            if method == "name_create":  # [id, display name]
                result_ids = result[0] if isinstance(result, (list, tuple)) and result else None
            else:
                result_ids = result
            created = id_list(result_ids)
            if created:
                scope.created.setdefault(plan.model, []).extend(created)
                scope.n += len(created)
        elif method == "search" and isinstance(result, list):
            scope.found.setdefault(plan.model, []).extend(i for i in result if _is_id(i))
        # Only internal predicates read the rows back (odoo_record_documents), so a
        # tool without internal calls keeps no copy of what it read.
        if method == "read" and self._internals and isinstance(result, list):
            rows = scope.records.setdefault(plan.model, {})
            for row in result:
                if isinstance(row, Mapping) and _is_id(row.get("id")):
                    rows.setdefault(row["id"], {}).update(row)
        if plan.cls == "read":
            records = result.get("records") if isinstance(result, Mapping) else result
            if isinstance(records, list):
                scope.n += len(records)
        elif plan.cls in ("write", "unlink", "create_write") or (
                plan.cls == "call" and plan.record_ids is not None):
            scope.n += len(id_list(plan.record_ids) or [])
        return result

    def _redact(self, model: str, method: str, result: Any) -> Any:
        # read_progress_bar returns {group value: {bucket value: count}}: its keys are
        # the distinct values of the group-by and bucket fields (a kanban stage name, a
        # selection value), not field names, and the grouping fields were already checked
        # (design 4.11), so the counts hold no withheld field value. Deciding its keys as
        # field names would drop a column whose value reads like a credential word ('Pass',
        # 'Token') and report a field that does not exist, so it is left unredacted.
        if method == "read_progress_bar":
            return result
        # The rows of one model share their keys: each key is decided once per call.
        seen: dict[str | None, tuple[set[Any], dict[Any, str]]] = {}
        if isinstance(result, Mapping):
            for key in ("records", "groups"):  # web_search_read, web_read_group
                if method.startswith("web_") and isinstance(result.get(key), list):
                    return {**result, key: self._rows(model, model, result[key], seen)}
            # onchange returns {"value": {field: value}, "warning": ..., "domain": ...}:
            # its "value" holds the call model's own fields (as copy_data's rows do), so
            # it is redacted against that model, not treated as an unknown nested dict.
            if method == "onchange" and isinstance(result.get("value"), Mapping):
                return {**result, "value": self._row(model, model, result["value"], seen)}
            return self._row(model, model, result, seen)
        if isinstance(result, list):
            return self._rows(model, model, result, seen)
        return result

    def _rows(self, model: str | None, label: str, rows: list[Any],
              seen: dict[str | None, tuple[set[Any], dict[Any, str]]]) -> list[Any]:
        return [self._row(model, label, row, seen) if isinstance(row, Mapping) else row
                for row in rows]

    def _row(self, model: str | None, label: str, row: Mapping[str, Any],
             seen: dict[str | None, tuple[set[Any], dict[Any, str]]]) -> dict[str, Any]:
        """A copy of ``row`` of ``model`` (None: a nested row of a model this call did
        not need to know) without its withheld fields; ``label`` names it in
        ``policy_withheld_fields``. ``seen`` holds, per model, the keys this call
        kept and the field name each withheld key names."""
        decided = seen.get(model)
        if decided is None:
            decided = seen[model] = (set(), {})
        kept, hidden = decided
        names = row.keys()
        if not names <= kept:  # keys not decided yet
            for key in names - kept - hidden.keys():
                withheld = self._withheld_key(model, key)
                if withheld:
                    hidden[key] = withheld
                else:
                    kept.add(key)
        out = dict(row)
        if hidden:
            for key in names & hidden.keys():
                self._scope.withheld.add(f"{label}.{hidden[key]}")
                del out[key]
        for key, value in out.items():  # values only change below, so iterating is safe
            if type(value) in _SCALARS:  # most values
                continue
            if type(value) is list and all(type(item) in _SCALARS for item in value):
                continue  # ids, or a many2one's [id, name]: nothing nested to redact
            name = key.split(":")[0] if isinstance(key, str) else key
            if key == "__records" and isinstance(value, list):  # unfolded groups
                out[key] = self._rows(model, label, value, seen)
            elif isinstance(value, Mapping) or (isinstance(value, list) and any(
                    isinstance(item, Mapping) for item in value)):
                nested = self._known_relation(model, name)
                inner = f"{label}.{name}"
                out[key] = (self._row(nested, inner, value, seen) if isinstance(value, Mapping)
                            else self._rows(nested, inner, value, seen))
            elif isinstance(value, list) and any(_values_command(item) for item in value):
                # x2many lines as (0, 0, values) or (1, id, values) commands: what
                # copy_data and default_get return for one2many fields
                nested, inner = self._known_relation(model, name), f"{label}.{name}"
                out[key] = [[item[0], item[1], self._row(nested, inner, item[2], seen)]
                            if _values_command(item) else item for item in value]
        return out

    def _withheld_key(self, model: str | None, key: Any) -> str:
        """The field name a result key withholds (``amount:sum`` names ``amount``), or
        "" when the key is kept."""
        name = key.split(":")[0] if isinstance(key, str) else key
        if not isinstance(name, str):
            return ""
        policy = self._policy
        withheld = (policy.field_withheld(model, name) if model
                    else policy.field_withheld_everywhere(name))
        return name if withheld else ""

    def _known_relation(self, model: str | None, name: Any) -> str | None:
        """The comodel of ``model.name``, so a nested read row is redacted against its
        own model (``hr.employee.private_email`` inside a ``hr.department`` copy_data).

        copy_data and default_get name no paths, so the guard holds no metadata for the
        model when redaction runs; the field metadata is loaded here on demand (cached
        per session) and any failure degrades to ``None`` (the result is already in
        hand, so redaction never fails the call), falling back to the names withheld
        everywhere."""
        if not model or not isinstance(name, str) or not valid_model(model):
            return None
        info = self._meta.get(model, {}).get(name)
        if info is None:
            try:
                info = self._fields(model).get(name)
            except Exception:  # redaction degrades to None, it never fails the call
                return None
        if isinstance(info, Mapping) and info.get("type") in RELATIONAL and valid_model(
                info.get("relation")):
            return str(info["relation"])
        return None

