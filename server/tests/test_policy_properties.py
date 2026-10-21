# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Properties of the permission policy, over generated policies (3000 cases each).

The generated files mix entries over the real tier models, real business names
and random ``x_`` names, with a random profile and, where the property allows,
the read-only flag. Every test seeds its own ``random.Random(1729)``, so the
cases are the same on every run and need no extra dependency.

The letters follow the design's list (a, c, d, f to k, m); b, e and l need the
tool mappings and the guard, which come with the server wiring.
"""

from __future__ import annotations

import copy
import datetime
import json
import random
from collections.abc import Callable
from typing import Any

from odoo_mcp.policy.loader import ERRORS, load_bytes, policy_from_document
from odoo_mcp.policy.model import PROFILES, Policy, Rule, model_aliases
from odoo_mcp.policy.tiers import (
    DELEGATES,
    NEVER,
    OPERATIONS,
    OUTBOUND_METHODS,
    WRITE_OPERATIONS,
)
from odoo_mcp.registry import registry
from odoo_mcp.tools import crud  # noqa: F401  (registers the tools)

SEED = 1729
CASES = 3000
TODAY = datetime.date(2026, 10, 21)
REASON = "Reviewed by the owner, ticket 4312"
TOOL_NAMES = sorted(tool.name for tool in registry.all())
PROFILE_NAMES = sorted(PROFILES)
E_CODES = set(ERRORS)

TIER_MODELS = [
    "ir.config_parameter", "res.config.settings", "ir.mail_server", "payment.provider",
    "payment.token", "mail.mail", "certificate.key", "res.users", "res.users.apikeys",
    "res.groups", "ir.model.access", "ir.rule", "ir.module.module", "res.partner.bank",
    "mail.message", "ir.sequence", "mail.template", "mail.followers", "mail.compose.message",
    "sms.sms", "mailing.mailing", "account.move.send", "ir.ui.view", "ir.actions.server",
    "ir.cron", "ir.property", "base.automation", "base.action.rule", "studio.approval.rule",
    "ir.model.fields", "base.module.uninstall", "res.users.apikeys.description",
]
BUSINESS = [
    "res.partner", "sale.order", "sale.order.line", "account.move", "account.invoice",
    "account.move.line", "account.invoice.line", "stock.quant.package", "stock.package",
    "crm.lead", "product.template", "hr.employee", "website.page", "website.controller.page",
    "product.document", "documents.document", "ir.attachment", "res.company", "project.task",
]
PATTERNS = ["*", "res.*", "ir.*", "account.*", "sale.*", "mail.*", "website.*", "hr.*",
            "stock.*", "res.users.*", "account.move.*", "base.*", "payment.*", "x_custom.*"]
METHODS = ["action_confirm", "action_post", "action_cancel", "button_draft", "message_post",
           "message_subscribe", "send_mail", "action_send_mail", "button_immediate_uninstall",
           "button_immediate_install", "x_method", "name_get"]
PAIRS = [("account.invoice", "account.move"), ("account.invoice.line", "account.move.line"),
         ("stock.quant.package", "stock.package"), ("base.automation", "base.action.rule")]
NOTE = {"ids": [1], "args": [], "kwargs": {"subtype_xmlid": "mail.mt_note"}}


# --- generators -------------------------------------------------------------------

def random_model(rng: random.Random) -> str:
    roll = rng.random()
    if roll < 0.4:
        return rng.choice(TIER_MODELS)
    if roll < 0.85:
        return rng.choice(BUSINESS)
    name = "x_" + "".join(rng.choice("abcdefgh") for _ in range(rng.randint(1, 6)))
    return name + rng.choice(["", ".line"])


def _value(rng: random.Random, op: str) -> Any:
    if op == "call":
        roll = rng.random()
        if roll < 0.3:
            return True
        if roll < 0.55:
            return False
        return rng.sample(METHODS, rng.randint(1, 3))
    return rng.random() < 0.5


def _without_never_grants(key: str, entry: dict[str, Any]) -> None:
    """What the loader would refuse (E18) becomes a refusal."""
    names = model_aliases(key)
    for never in NEVER:
        if never.model not in names:
            continue
        for op in never.ops:
            value = entry.get(op)
            if op == "call" and never.methods is not None:
                if isinstance(value, list):
                    kept = [m for m in value if m not in never.methods]
                    entry[op] = kept or False
            elif value is True or isinstance(value, list):
                entry[op] = False


def random_entry(rng: random.Random, key: str, exact: bool) -> dict[str, Any]:
    entry: dict[str, Any] = {op: _value(rng, op)
                             for op in rng.sample(OPERATIONS, rng.randint(1, 3))}
    if exact:
        entry["reason"] = REASON  # every opening needs one; a reason is valid on any exact entry
        if rng.random() < 0.3:
            entry["expires"] = (TODAY + datetime.timedelta(days=rng.randint(-60, 60))).isoformat()
        _without_never_grants(key, entry)
    return entry


def random_document(rng: random.Random, *, exact: bool = True, patterns: bool = True,
                    focus: list[str] | None = None) -> dict[str, Any]:
    models: dict[str, Any] = {}
    for _ in range(rng.randint(0, 7)):
        if patterns and (not exact or rng.random() < 0.35):
            key = rng.choice(PATTERNS)
            models[key] = random_entry(rng, key, False)
        elif exact:
            key = rng.choice(focus) if focus and rng.random() < 0.5 else random_model(rng)
            models[key] = random_entry(rng, key, True)
    document: dict[str, Any] = {"version": 1, "models": models}
    if rng.random() < 0.3:
        document["fields"] = {
            "withhold": rng.sample(["*.vat", "hr.employee.private_email", "res.partner.email",
                                    "sale.order.note"], rng.randint(0, 2)),
            "allow": [{"field": "sale.order.access_token", "reason": REASON}]
            if rng.random() < 0.5 else [],
        }
    if rng.random() < 0.2:
        document["tools"] = {"disabled": rng.sample(TOOL_NAMES, rng.randint(1, 3))}
    if rng.random() < 0.3:
        document["comment"] = "generated"
    return document


def build(document: dict[str, Any] | None, profile: str, readonly: bool = False,
          today: datetime.date = TODAY) -> Policy:
    # policy_from_document raises on an invalid file, so a generator bug fails loudly
    return policy_from_document(document, path="/p.json", profile=profile, readonly=readonly,
                                tool_names=TOOL_NAMES, today=today)


def random_query(rng: random.Random, document: dict[str, Any] | None = None,
                 ops: tuple[str, ...] = OPERATIONS) -> tuple[str, str, str | None, Any]:
    op = rng.choice(ops)
    keys = [k for k in (document or {}).get("models", {}) if k != "*" and not k.endswith(".*")]
    model = rng.choice(keys) if keys and rng.random() < 0.5 else random_model(rng)
    method = None
    if op == "call" and rng.random() < 0.85:
        method = rng.choice(METHODS)
    args = NOTE if method == "message_post" and rng.random() < 0.3 else None
    return op, model, method, args


def allowed(p: Policy, query: tuple[str, str, str | None, Any]) -> bool:
    op, model, method, args = query
    return p.decide(op, model, method, args).allowed


def _never_matches(op: str, model: str, method: str | None) -> bool:
    return any(entry.model in model_aliases(model) and op in entry.ops
               and (entry.methods is None or method in entry.methods) for entry in NEVER)


# --- the properties ------------------------------------------------------------------

def test_a_the_read_only_ceiling() -> None:
    """With read-only on, every operation but read and inspect is refused, whatever the file."""
    rng = random.Random(SEED)
    for _ in range(CASES):
        document = random_document(rng)
        p = build(document, rng.choice(PROFILE_NAMES), readonly=True)
        for _ in range(4):
            op, model, method, args = random_query(rng, document, tuple(sorted(WRITE_OPERATIONS)))
            d = p.decide(op, model, method, args)
            assert not d.allowed, (document, op, model, method)
            assert d.rule == "readonly" or d.rule.startswith("never:"), d


def test_c_patterns_never_open_a_tier_or_an_outbound_method() -> None:
    """A file of pattern rules only never changes what a tier or 4.7 refuses."""
    rng = random.Random(SEED)
    checked = 0
    for _ in range(CASES):
        profile, readonly = rng.choice(PROFILE_NAMES), rng.random() < 0.1
        document = random_document(rng, exact=False)
        base, p = build(None, profile, readonly), build(document, profile, readonly)
        for _ in range(6):
            query = random_query(rng)
            before = base.decide(query[0], query[1], query[2], query[3])
            if not before.allowed and (before.rule.startswith("tier:")
                                       or before.rule == "outbound-method"):
                checked += 1
                assert not allowed(p, query), (document, query, before.rule)
    assert checked > 1000


def test_d_exact_rules_decide() -> None:
    """An exact, unexpired rule that sets an operation gives that value (read-only off,
    NEVER aside). A model whose alias holds another exact rule for that operation, or
    that delegates its writes to a parent (which must allow them too), is left to g, h."""
    rng = random.Random(SEED)
    checked = 0
    for _ in range(CASES):
        profile = rng.choice(PROFILE_NAMES)
        document = random_document(rng)
        models = document["models"]
        exact = [k for k in models if k != "*" and not k.endswith(".*")]
        if not exact:
            continue
        key = rng.choice(exact)
        entry = models[key]
        ops = [op for op in OPERATIONS if op in entry]
        if not ops:
            continue
        op = rng.choice(ops)
        value = entry[op]
        if "expires" in entry and datetime.date.fromisoformat(entry["expires"]) < TODAY:
            continue
        closure = model_aliases(key)
        if any(op in models.get(other, {}) for other in closure - {key}):
            continue
        if op != "read" and any(name in DELEGATES for name in closure):
            continue
        method = None
        if op == "call":
            method = rng.choice(value) if isinstance(value, list) and rng.random() < 0.5 else (
                rng.choice(METHODS))
        if _never_matches(op, key, method):
            continue
        if value is False:
            expected = False
        elif op != "call":
            expected = True
        elif value is True:  # true opens the tiers, not the outbound methods
            expected = method not in OUTBOUND_METHODS or profile == "full"
        else:
            expected = method in value
        checked += 1
        d = build(document, profile).decide(op, key, method)
        assert d.allowed is expected, (document, profile, op, key, method, d)
    assert checked > 1000


def test_f_adding_a_false_never_turns_a_refusal_into_an_allowance() -> None:
    rng = random.Random(SEED)
    checked = 0
    for _ in range(CASES):
        profile, readonly = rng.choice(PROFILE_NAMES), rng.random() < 0.2
        document = random_document(rng)
        key = rng.choice(PATTERNS) if rng.random() < 0.4 else random_model(rng)
        op = rng.choice(OPERATIONS)
        entry = dict(document["models"].get(key, {}))
        if op in entry:
            continue
        entry[op] = False
        stricter = copy.deepcopy(document)
        stricter["models"][key] = entry
        p, q = build(document, profile, readonly), build(stricter, profile, readonly)
        for _ in range(6):
            query = random_query(rng, stricter)
            if not allowed(p, query):
                checked += 1
                assert not allowed(q, query), (document, key, op, query)
    assert checked > 3000


def test_g_both_names_of_an_alias_pair_get_the_same_decision() -> None:
    rng = random.Random(SEED)
    names = [name for pair in PAIRS for name in pair]
    for _ in range(CASES):
        profile, readonly = rng.choice(PROFILE_NAMES), rng.random() < 0.1
        p = build(random_document(rng, focus=names), profile, readonly)
        for a, b in PAIRS:
            op = rng.choice(OPERATIONS + ("inspect",))
            method = rng.choice(METHODS) if op == "call" else None
            args = NOTE if method == "message_post" and rng.random() < 0.5 else None
            assert p.decide(op, a, method, args).allowed is p.decide(op, b, method, args).allowed, (
                a, b, op, method)


def test_h_a_delegating_child_is_never_weaker_than_its_parent_for_writes() -> None:
    rng = random.Random(SEED)
    names = list(DELEGATES) + [parent for parent, _link in DELEGATES.values()]
    checked = 0
    for _ in range(CASES):
        profile, readonly = rng.choice(PROFILE_NAMES), rng.random() < 0.1
        p = build(random_document(rng, focus=names), profile, readonly)
        for child, (parent, _link) in DELEGATES.items():
            op = rng.choice(sorted(WRITE_OPERATIONS))
            method = rng.choice(METHODS) if op == "call" else None
            if p.decide(op, child, method).allowed:
                checked += 1
                assert p.decide(op, parent, method).allowed, (child, parent, op, method)
    assert checked > 1000


def test_i_never_is_never_allowed() -> None:
    """The loader refuses a file that grants a NEVER entry (E18), and decide() refuses
    NEVER under every valid policy, and under hand-built rules that grant it."""
    rng = random.Random(SEED)
    for _ in range(CASES):
        profile = rng.choice(PROFILE_NAMES)
        never = rng.choice(NEVER)
        op = rng.choice(sorted(never.ops))
        method = rng.choice(sorted(never.methods)) if never.methods else (
            rng.choice(METHODS) if op == "call" else None)
        document = random_document(rng)
        if op == "call":
            grant: Any = [method] if never.methods or rng.random() < 0.5 else True
        else:
            grant = True
        refused = copy.deepcopy(document)
        refused["models"][never.model] = {op: grant, "reason": REASON}
        loaded = load_bytes(json.dumps(refused).encode(), path="/p.json", profile=profile,
                            tool_names=TOOL_NAMES, today=TODAY)
        assert (loaded.locked, loaded.error_code) == (True, "E18"), refused
        p = build(document, profile, readonly=rng.random() < 0.2)
        assert p.decide(op, never.model, method).rule == f"never:{never.id}"
        value = frozenset({method}) if op == "call" and method else True
        forced = Policy(profile_name=profile, rules=(Rule(never.model, ((op, value),),
                                                          reason=REASON),))
        assert not forced.decide(op, never.model, method).allowed


def _reordered(rng: random.Random, document: dict[str, Any]) -> dict[str, Any]:
    """The same rules in another key order, with other comments."""
    def shuffled(mapping: dict[str, Any]) -> dict[str, Any]:
        items = list(mapping.items())
        rng.shuffle(items)
        return dict(items)

    out: dict[str, Any] = {}
    for key, value in shuffled(document).items():
        if key == "models":
            models = {}
            for model, entry in shuffled(value).items():
                entry = shuffled({k: (rng.sample(v, len(v)) if isinstance(v, list) else v)
                                  for k, v in entry.items() if k != "comment"})
                if rng.random() < 0.5:
                    entry["comment"] = f"note {rng.randint(0, 999)}"
                models[model] = entry
            out[key] = models
        elif key == "fields":
            out[key] = {k: rng.sample(v, len(v)) for k, v in shuffled(value).items()}
        elif key == "tools":
            out[key] = {"disabled": rng.sample(value["disabled"], len(value["disabled"]))}
        elif key != "comment":
            out[key] = value
    if rng.random() < 0.7:
        out["comment"] = f"changed {rng.randint(0, 999)}"
    return out


def _flipped(rng: random.Random, document: dict[str, Any]) -> dict[str, Any] | None:
    """The same document with one operation value changed, or None."""
    models = document["models"]
    keys = [key for key, entry in models.items() if any(op in entry for op in OPERATIONS)]
    if not keys:
        return None
    key = rng.choice(keys)
    entry = dict(models[key])
    op = rng.choice([op for op in OPERATIONS if op in entry])
    old = entry[op]
    if isinstance(old, bool):
        entry[op] = not old
    elif len(old) > 1:
        entry[op] = old[1:]
    else:
        entry[op] = old + [m for m in METHODS if m not in old][:1]
    if key != "*" and not key.endswith(".*"):
        _without_never_grants(key, entry)
    if entry[op] == old or (isinstance(old, list) and isinstance(entry[op], list)
                            and set(entry[op]) == set(old)):
        return None
    flipped = copy.deepcopy(document)
    flipped["models"][key] = entry
    return flipped


def test_j_the_digest_ignores_order_and_comments_and_follows_every_value() -> None:
    rng = random.Random(SEED)
    flips = 0
    for _ in range(CASES):
        profile, readonly = rng.choice(PROFILE_NAMES), rng.random() < 0.2
        document = random_document(rng)
        digest = build(document, profile, readonly).digest
        assert digest is not None and len(digest) == 12
        assert build(_reordered(rng, document), profile, readonly).digest == digest
        flipped = _flipped(rng, document)
        if flipped is not None:
            flips += 1
            assert build(flipped, profile, readonly).digest != digest, (document, flipped)
    assert flips > 2000


# The corruptions of a valid document, each with the code it must give.
Mutation = Callable[[random.Random, dict[str, Any]], tuple[Any, str]]


def _some_entry(rng: random.Random, document: dict[str, Any], exact: bool) -> str:
    keys = [k for k in document["models"] if (k != "*" and not k.endswith(".*")) is exact]
    if keys:
        return rng.choice(keys)
    key = random_model(rng) if exact else rng.choice(PATTERNS)
    while key in document["models"] or (exact and _never_matches("read", key, None)):
        key = random_model(rng) if exact else rng.choice(PATTERNS)
    document["models"][key] = random_entry(rng, key, exact)
    return key


def _set(path: tuple[str, ...], value: Any, code: str) -> Mutation:
    def mutate(rng: random.Random, document: dict[str, Any]) -> tuple[Any, str]:
        target = document
        for step in path[:-1]:
            target = target.setdefault(step, {})
        target[path[-1]] = value
        return document, code
    return mutate


def _entry(change: Callable[[random.Random, dict[str, Any]], None], code: str,
           exact: bool = True) -> Mutation:
    def mutate(rng: random.Random, document: dict[str, Any]) -> tuple[Any, str]:
        key = _some_entry(rng, document, exact)
        change(rng, document["models"][key])
        return document, code
    return mutate


def _model_key(key: str) -> Mutation:
    def mutate(_rng: random.Random, document: dict[str, Any]) -> tuple[Any, str]:
        document["models"][key] = {"read": True}
        return document, "E9"
    return mutate


def _text(change: Callable[[random.Random, str], bytes], code: str) -> Mutation:
    def mutate(rng: random.Random, document: dict[str, Any]) -> tuple[Any, str]:
        return change(rng, json.dumps(document)), code
    return mutate


MUTATIONS: list[Mutation] = [
    _set(("x_unknown",), 1, "E8"),
    _set(("version",), 2, "E7"),
    _set(("version",), "1", "E7"),
    _set(("version",), True, "E7"),
    _set(("version",), None, "E7"),
    _set(("models",), [], "E7"),
    _set(("comment",), 5, "E7"),
    _model_key("Res.Partner"),
    _model_key("a b"),
    _model_key("*.x"),
    _model_key("x.*.y"),
    _model_key("a" * 129),
    _entry(lambda rng, e: e.update(delete=True), "E10"),
    _entry(lambda rng, e: e.update(write=rng.choice([1, "true", None, []])), "E11"),
    _entry(lambda rng, e: e.update(call=rng.choice(["x", 1, None, {}])), "E12"),
    _entry(lambda rng, e: e.update(call=[]), "E12"),
    _entry(lambda rng, e: e.update(call=["_private"]), "E13"),
    _set(("tools", "disabled"), ["odoo_nope"], "E14"),
    _set(("models", "res.users"), {"write": True}, "E15"),
    _entry(lambda rng, e: e.update(expires=rng.choice(["2026-02-30", "soon", 20261231])), "E16"),
    _set(("fields", "withhold"), ["vat"], "E17"),
    _set(("models", "res.users.apikeys"), {"unlink": True, "reason": REASON}, "E18"),
    _entry(lambda rng, e: e.update(reason=REASON), "E19", exact=False),
    _set(("fields", "allow"), [{"field": "sale.order.access_token"}], "E20"),
    _text(lambda rng, text: text[:rng.randint(0, len(text) - 1)].encode(), "E5"),
    _text(lambda rng, text: text.replace('"version"', '"version": 1, "version"', 1).encode(),
          "E6"),
    _text(lambda rng, text: text[:-1].encode() + b', "comment": "\xff\xfe"}', "E3"),
    _text(lambda rng, text: text[:-1].encode() + b', "comment": ' + b"[" * 9 + b"]" * 9 + b"}",
          "E5"),
    _text(lambda rng, text: text[:-1].encode() + b', "comment": "' + b"x" * 262144 + b'"}',
          "E4"),
]


def _random_json(rng: random.Random, depth: int = 0) -> Any:
    roll = rng.random()
    if depth > 3 or roll < 0.3:
        return rng.choice([None, True, False, 0, 1, -1, 2.5, "", "x", "read", "*", "res.partner"])
    if roll < 0.6:
        return [_random_json(rng, depth + 1) for _ in range(rng.randint(0, 3))]
    keys = ["version", "models", "fields", "tools", "comment", "read", "call", "reason",
            "withhold", "allow", "disabled", "res.partner", "*", "hr.*", "x"]
    return {rng.choice(keys): _random_json(rng, depth + 1) for _ in range(rng.randint(0, 4))}


def test_k_malformed_documents_always_lock_with_an_error_code() -> None:
    """Never another exception, never a partly applied policy."""
    rng = random.Random(SEED)
    for case in range(CASES):
        profile = rng.choice(PROFILE_NAMES)
        if case % 10 == 9:  # random structures: they may be valid, but never raise
            data = json.dumps(_random_json(rng)).encode()
            expected = None
        elif case % 10 == 8:  # random bytes
            data = bytes(rng.randrange(256) for _ in range(rng.randint(0, 80)))
            expected = None
        else:
            mutate = rng.choice(MUTATIONS)
            document, expected = mutate(rng, random_document(rng))
            data = document if isinstance(document, bytes) else json.dumps(document).encode()
        p = load_bytes(data, path="/p.json", profile=profile, tool_names=TOOL_NAMES, today=TODAY)
        if expected is None and not p.locked:
            continue
        assert p.locked and p.error_code in E_CODES and p.error, (data[:200], p.error)
        if expected is not None:
            assert p.error_code == expected, (data[:300], p.error)
        assert p.rules == () and p.withhold == frozenset() and p.disabled == frozenset()
        assert p.digest is None and p.decide("read", "res.partner").rule == "locked"
        assert "unexpected" not in p.error  # every problem has its own code and text


def test_m_an_expired_entry_never_allows_more_than_the_file_without_its_allowances() -> None:
    rng = random.Random(SEED)
    checked = 0
    for _ in range(CASES):
        profile, readonly = rng.choice(PROFILE_NAMES), rng.random() < 0.1
        document = random_document(rng)
        key = random_model(rng)
        entry = random_entry(rng, key, True)
        entry[rng.choice(OPERATIONS)] = True
        _without_never_grants(key, entry)
        entry["expires"] = (TODAY - datetime.timedelta(days=rng.randint(1, 30))).isoformat()
        document["models"][key] = entry
        stripped = {k: v for k, v in entry.items()
                    if k != "expires" and not (v is True or isinstance(v, list))}
        without = copy.deepcopy(document)
        without["models"][key] = stripped
        expired, baseline = build(document, profile, readonly), build(without, profile, readonly)
        for _ in range(6):
            op, model, method, args = random_query(rng, document)
            if rng.random() < 0.5:
                model = rng.choice(sorted(model_aliases(key)))
            if expired.decide(op, model, method, args).allowed:
                checked += 1
                assert baseline.decide(op, model, method, args).allowed, (entry, op, model, method)
    assert checked > 3000
