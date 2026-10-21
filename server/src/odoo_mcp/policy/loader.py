# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Load the permission policy: the profile, the optional JSON file, its checks.

``load_policy`` never raises. A profile, path or file it cannot accept gives a
locked policy (``Policy.locked``) whose error carries one of the codes E1 to
E20: ``tools/list`` then lists only ``odoo_version``, which shows the error,
and every other tool refuses without contacting Odoo. The server fails closed
but still explains itself, where a crash would show an empty tool list and no
reason.

The file (version 1) layers per-model rules on the profile chosen in the
option and carries no profile of its own. It is read once, at start, from an
explicit absolute path only: no default location is searched, because an agent
could create a file there and have it picked up silently. The schema is
strict: an unknown key is an error, so a typo cannot silently drop a refusal.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import stat
import unicodedata
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from ..errors import PolicyConfigError
from .classify import valid_method
from .model import (
    DEFAULT_PROFILE,
    PROFILES,
    Policy,
    Rule,
    model_aliases,
    model_tiers,
    rule_openings,
    utc_today,
)
from .tiers import (
    DELEGATES,
    NEVER,
    OPERATIONS,
    OUTBOUND_METHODS,
    TIER_NAMES,
    TIERS,
    Tier,
)

log = logging.getLogger("odoo_mcp.policy")

FILE_VERSION = 1  # version 2 is reserved for a remote mode (principals)
MAX_FILE_BYTES = 262144
MAX_MODELS = 1000
MAX_CALL_METHODS = 200
MAX_KEY_LENGTH = 128
MAX_NESTING = 8  # the deepest valid file nests 4 levels (top, fields, allow, item)
REASON_MIN, REASON_MAX = 10, 200

TOP_KEYS = ("version", "models", "fields", "tools", "comment")
ENTRY_KEYS = ("read", "create", "write", "unlink", "call", "schema", "reason", "expires",
              "comment")
BOOLEAN_OPS = ("read", "create", "write", "unlink", "schema")
FIELDS_KEYS = ("withhold", "allow")
ALLOW_KEYS = ("field", "reason")
TOOLS_KEYS = ("disabled",)

_MODEL_KEY = re.compile(r"\*|[a-z0-9_]+(?:\.[a-z0-9_]+)*(?:\.\*)?")
_MODEL_FIELD = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*\.[a-z0-9_]+")
_ANY_MODEL_FIELD = re.compile(r"\*\.[a-z0-9_]+")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

ERRORS: dict[str, str] = {
    "E1": "unknown permission profile '{value}' (use readonly, standard, builder, full)",
    "E2": "the policy file path must be absolute (got '{value}')",
    "E3": "policy file {path}: cannot be read ({strerror})",
    "E4": "policy file {path}: is larger than 262144 bytes",
    "E5": "policy file {path}: is not valid JSON (line {line}, column {column}: {msg})",
    "E6": "policy file {path}: duplicate key '{key}' (a repeated entry could hide a rule)",
    "E7": 'policy file {path}: the top level must be an object with "version": 1',
    "E8": "policy file {path}: unknown key '{key}' at the top level (use version, models, "
          "fields, tools, comment)",
    "E9": "policy file {path}: models['{key}']: not a model name, 'prefix.*' or '*'",
    "E10": "policy file {path}: models['{key}']: unknown key '{op}' (use read, create, "
           "write, unlink, call, schema, reason, expires, comment)",
    "E11": "policy file {path}: models['{key}'].{op}: must be true or false",
    "E12": "policy file {path}: models['{key}'].call: must be true, false or a list of "
           "method names",
    "E13": "policy file {path}: models['{key}'].call: '{method}' is not a public method name",
    "E14": "policy file {path}: tools.disabled: unknown tool '{name}'",
    "E15": "policy file {path}: models['{key}'] opens {ops} on {article} {tier}-tier model "
           'and needs "reason" (at least 10 characters): it is shown in odoo_version and '
           "written to the audit log",
    "E16": "policy file {path}: models['{key}'].expires: '{value}' is not a date (YYYY-MM-DD)",
    "E17": "policy file {path}: fields.{list}[{index}]: '{value}' is not model.field "
           "(withhold also accepts *.field)",
    "E18": "policy file {path}: models['{key}'].{op}: cannot be granted: {reason}",
    "E19": "policy file {path}: models['{key}']: \"reason\" and \"expires\" only apply to an "
           "entry that names one model exactly",
    "E20": 'policy file {path}: fields.allow[{index}] needs "reason" (at least 10 characters)',
}

# Wordings for the structural problems the main table does not word (a value of
# the wrong type, a list out of bounds). Each keeps the code of its section, so
# the codes stay E1 to E20.
VARIANTS: dict[str, tuple[str, str]] = {
    "top-type": ("E7", "policy file {path}: '{key}' at the top level must be {what}"),
    "models-size": ("E9", "policy file {path}: models has {count} entries (at most 1000)"),
    "entry-type": ("E10", ("policy file {path}: models['{key}']: must be an object (use read, "
                           "create, write, unlink, call, schema, reason, expires, comment)")),
    "entry-comment": ("E10", "policy file {path}: models['{key}'].comment: must be text"),
    "call-size": ("E12", ("policy file {path}: models['{key}'].call: a method list holds 1 to "
                          "200 names")),
    "tools-type": ("E14", ('policy file {path}: tools: must be an object with "disabled", a '
                           "list of tool names")),
    "tools-key": ("E14", "policy file {path}: tools: unknown key '{key}' (use disabled)"),
    "reason-text": ("E15", ("policy file {path}: models['{key}'].reason: must be text of 10 to "
                            "200 characters")),
    "fields-type": ("E17", ('policy file {path}: fields: must be an object with "withhold" '
                            'and/or "allow"')),
    "fields-key": ("E17", ("policy file {path}: fields: unknown key '{key}' (use withhold, "
                           "allow)")),
    "fields-list": ("E17", "policy file {path}: fields.{list}: must be a list"),
    "allow-type": ("E17", ('policy file {path}: fields.allow[{index}]: must be an object with '
                           '"field" and "reason"')),
    "allow-reason": ("E20", ("policy file {path}: fields.allow[{index}].reason: must be text of "
                             "10 to 200 characters")),
}

WARNINGS: dict[str, str] = {
    "W1": "models['{key}'] refuses create/write/unlink but allows call: business methods "
          "(e.g. action_post) can still change these records; set \"call\": false or list "
          "the allowed methods",
    "W2": "models['{model}'] opens {ops} on '{model}' ({tier} tier){until}: {reason}",
    "W3": "the policy file can be changed by other users of this machine (mode {octal})",
    "W4": "models['{key}'] expired on {date}: its allowances are ignored, its refusals still "
          "apply",
    "W5": "models['{key}'] sets {op} on a pattern; models of the {tiers} tiers are not "
          "affected: name a model exactly to open one",
    "W6": "profile 'builder' lets the agent create automations and server actions, which run "
          "Python on the Odoo server with sudo() available: for confidentiality it equals "
          "'full'. Use it on sandboxes and staging.",
    "W7": "fields.allow releases {field}: {reason}",
}


class _DuplicateKey(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _error(code: str | None, variant: str | None = None, **values: Any) -> PolicyConfigError:
    """The PolicyConfigError of ``code``, or of a structural ``variant``."""
    if variant is not None:
        code, template = VARIANTS[variant]
    else:
        assert code is not None
        template = ERRORS[code]
    return PolicyConfigError(code, template.format(**values))


def _shown(value: Any, limit: int = 60) -> str:
    """A value from the file for a message: printable ASCII, one line, bounded."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True, default=str)
    text = text.encode("ascii", "backslashreplace").decode("ascii")
    text = "".join(ch if " " <= ch <= "~" else "?" for ch in text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _printable(text: str) -> str:
    """Control and format characters become spaces; runs of spaces collapse."""
    if not text.isprintable():
        text = "".join(" " if unicodedata.category(ch)[0] == "C" else ch for ch in text)
    return " ".join(text.split())


def _profile_name(value: Any) -> str:
    return str(value or "").strip().lower() or DEFAULT_PROFILE


# --- entry points -------------------------------------------------------------

def load_policy(settings: Any, tool_names: Iterable[str], *,
                today: datetime.date | None = None) -> Policy:
    """The policy of ``settings``: ``policy_profile``, ``policy_file``, ``readonly``.

    ``tool_names`` are the registered tools (``tools.disabled`` may name only
    those). ``today`` fixes the date for the expiry checks (tests); by default
    an expiry is checked against the UTC date of each decision. Never raises.
    """
    profile = _profile_name(getattr(settings, "policy_profile", ""))
    readonly = bool(getattr(settings, "readonly", False))
    configured = str(getattr(settings, "policy_file", "") or "").strip()
    path = os.path.expanduser(configured) if configured else ""
    try:
        if profile not in PROFILES:
            raise _error("E1", value=_shown(profile))
        if not path:
            return policy_from_document(None, path=None, profile=profile, readonly=readonly,
                                        tool_names=tool_names, today=today)
        if not os.path.isabs(path):
            raise _error("E2", value=_printable(configured))
        data, mode = _read(path)
    except PolicyConfigError as exc:
        return locked_policy(exc, profile=profile, readonly=readonly, source=path or None)
    except Exception as exc:  # never raises: an unexpected failure locks too
        log.exception("the permission policy could not be loaded")
        return locked_policy(_error("E3", path=_printable(path),
                                    strerror=f"unexpected {type(exc).__name__}"),
                             profile=profile, readonly=readonly, source=path or None)
    return load_bytes(data, path=path, profile=profile, readonly=readonly,
                      tool_names=tool_names, today=today, file_mode=mode)


def load_bytes(data: bytes, *, path: str, profile: str, readonly: bool = False,
               tool_names: Iterable[str] = (), today: datetime.date | None = None,
               file_mode: int | None = None) -> Policy:
    """The policy of a file's bytes, ``profile`` and ``readonly``. Never raises."""
    try:
        if profile not in PROFILES:
            raise _error("E1", value=_shown(profile))
        if len(data) > MAX_FILE_BYTES:
            raise _error("E4", path=_printable(path))
        document = parse_document(data, path)
        return policy_from_document(document, path=path, profile=profile, readonly=readonly,
                                    tool_names=tool_names, today=today, file_mode=file_mode)
    except PolicyConfigError as exc:
        return locked_policy(exc, profile=profile, readonly=readonly, source=path)
    except Exception as exc:  # never raises: an unexpected failure locks too
        log.exception("the permission policy file could not be checked")
        return locked_policy(_error("E3", path=_printable(path),
                                    strerror=f"unexpected {type(exc).__name__}"),
                             profile=profile, readonly=readonly, source=path)


def locked_policy(error: PolicyConfigError, *, profile: str, readonly: bool,
                  source: str | None) -> Policy:
    """A policy that refuses everything and says why (``error`` is the E-code text)."""
    shown = profile if profile in PROFILES else _shown(profile, 40)
    return Policy(profile_name=shown, readonly=readonly, source=source, error=str(error),
                  error_code=error.code)


# --- reading and parsing ----------------------------------------------------------

def _strerror(exc: OSError) -> str:
    return exc.strerror or type(exc).__name__


def _read(path: str) -> tuple[bytes, int | None]:
    """At most MAX_FILE_BYTES + 1 bytes of a regular file, and its mode (POSIX)."""
    shown = _printable(path)
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)  # O_NONBLOCK: a FIFO planted there cannot hang the start
    except OSError as exc:
        raise _error("E3", path=shown, strerror=_strerror(exc)) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _error("E3", path=shown, strerror="not a regular file")
        chunks, size = [], 0
        while size <= MAX_FILE_BYTES:
            chunk = os.read(fd, MAX_FILE_BYTES + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    except OSError as exc:
        raise _error("E3", path=shown, strerror=_strerror(exc)) from None
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) > MAX_FILE_BYTES:
        raise _error("E4", path=shown)
    return data, (info.st_mode if os.name == "posix" else None)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise _DuplicateKey(key)
        out[key] = value
    return out


def _too_deep(text: str) -> tuple[int, int] | None:
    """Where the nesting of ``text`` passes MAX_NESTING, before json recurses."""
    depth, line, column = 0, 1, 0
    in_string = escaped = False
    for ch in text:
        column += 1
        if ch == "\n":
            line, column = line + 1, 0
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            if depth > MAX_NESTING:
                return line, column
        elif ch in "]}":
            depth -= 1
    return None


def parse_document(data: bytes, path: str) -> Any:
    """UTF-8 JSON (a leading BOM is accepted) without duplicate keys."""
    shown = _printable(path)
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _error("E3", path=shown, strerror=f"not UTF-8 text at byte {exc.start}") from None
    deep = _too_deep(text)
    if deep is not None:
        raise _error("E5", path=shown, line=deep[0], column=deep[1],
                     msg=f"nested deeper than {MAX_NESTING} levels")
    try:
        return json.loads(text, object_pairs_hook=_unique_keys)
    except _DuplicateKey as exc:
        raise _error("E6", path=shown, key=_shown(exc.key)) from None
    except json.JSONDecodeError as exc:
        raise _error("E5", path=shown, line=exc.lineno, column=exc.colno, msg=exc.msg) from None
    except (ValueError, RecursionError) as exc:  # e.g. an integer past the digit limit
        raise _error("E5", path=shown, line=1, column=1, msg=_shown(str(exc), 80)) from None


# --- validation -----------------------------------------------------------------

def policy_from_document(document: Any, *, path: str | None, profile: str,
                         readonly: bool = False, tool_names: Iterable[str] = (),
                         today: datetime.date | None = None,
                         file_mode: int | None = None) -> Policy:
    """Validate a parsed file (``None``: no file) into a Policy.

    Raises :class:`PolicyConfigError` on the first problem, in file order;
    ``load_policy`` and ``load_bytes`` turn it into a locked policy.
    """
    if profile not in PROFILES:
        raise _error("E1", value=_shown(profile))
    load_day = today or utc_today()
    rules: tuple[Rule, ...] = ()
    withhold: frozenset[str] = frozenset()
    allow: tuple[tuple[str, str], ...] = ()
    disabled: frozenset[str] = frozenset()
    if document is not None:
        shown = _printable(path or "")
        if not isinstance(document, dict):
            raise _error("E7", path=shown)
        if "version" in document and not _is_version(document["version"]):
            raise _error("E7", path=shown)
        for key in document:
            if key not in TOP_KEYS:
                raise _error("E8", path=shown, key=_shown(key))
        if "version" not in document:
            raise _error("E7", path=shown)
        if not isinstance(document.get("comment", ""), str):
            raise _error(None, "top-type", path=shown, key="comment", what="text")
        rules = _rules(document.get("models", {}), shown)
        withhold, allow = _fields(document.get("fields", {}), shown)
        disabled = _tools(document.get("tools", {}), shown, tool_names)
    policy = Policy(profile_name=profile, readonly=readonly, rules=rules, withhold=withhold,
                    allow=allow, disabled=disabled, source=path,
                    clock=(lambda: today) if today is not None else utc_today)
    return replace(policy, warnings=policy_warnings(policy, load_day, file_mode))


def _is_version(value: Any) -> bool:
    return type(value) is int and value == FILE_VERSION


def _rules(models: Any, path: str) -> tuple[Rule, ...]:
    if not isinstance(models, dict):
        raise _error(None, "top-type", path=path, key="models", what="an object")
    if len(models) > MAX_MODELS:
        raise _error(None, "models-size", path=path, count=len(models))
    rules = []
    for key, entry in models.items():
        if len(key) > MAX_KEY_LENGTH or not _MODEL_KEY.fullmatch(key):
            raise _error("E9", path=path, key=_shown(key))
        if not isinstance(entry, dict):
            raise _error(None, "entry-type", path=path, key=key)
        for name in entry:
            if name not in ENTRY_KEYS:
                raise _error("E10", path=path, key=key, op=_shown(name))
        exact = key != "*" and not key.endswith(".*")
        if not exact and ("reason" in entry or "expires" in entry):
            raise _error("E19", path=path, key=key)
        ops: list[tuple[str, Any]] = []
        reason: str | None = None
        expires: datetime.date | None = None
        for name, value in entry.items():
            if name in BOOLEAN_OPS:
                if not isinstance(value, bool):
                    raise _error("E11", path=path, key=key, op=name)
                ops.append((name, value))
            elif name == "call":
                ops.append(("call", _call_value(value, key, path)))
            elif name == "reason":
                reason = _printable(value) if isinstance(value, str) else None
                if reason is None or len(reason) > REASON_MAX:
                    raise _error(None, "reason-text", path=path, key=key)
            elif name == "expires":
                expires = _date(value, key, path)
            elif not isinstance(value, str):  # comment
                raise _error(None, "entry-comment", path=path, key=key)
        ordered = tuple(sorted(ops, key=lambda item: OPERATIONS.index(item[0])))
        rule = Rule(key, ordered, reason=reason or "", expires=expires)
        if exact:
            _check_never(rule, path)
            _check_reason(rule, reason, path)
        rules.append(rule)
    return tuple(rules)


def _call_value(value: Any, key: str, path: str) -> Any:
    if isinstance(value, bool):
        return value
    if not isinstance(value, list):
        raise _error("E12", path=path, key=key)
    if not 1 <= len(value) <= MAX_CALL_METHODS:
        raise _error(None, "call-size", path=path, key=key)
    for method in value:
        if not valid_method(method):
            raise _error("E13", path=path, key=key, method=_shown(method))
    return frozenset(value)


def _date(value: Any, key: str, path: str) -> datetime.date:
    if isinstance(value, str) and _DATE.fullmatch(value):
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            pass
    raise _error("E16", path=path, key=key, value=_shown(value))


def _check_never(rule: Rule, path: str) -> None:
    names = model_aliases(rule.key)
    for entry in NEVER:
        if entry.model not in names:
            continue
        for op in OPERATIONS:
            if op not in entry.ops:
                continue
            value = rule.get(op)
            if op == "call" and entry.methods is not None:
                granted = isinstance(value, frozenset) and bool(value & entry.methods)
            else:
                granted = value is True or isinstance(value, frozenset)
            if granted:
                raise _error("E18", path=path, key=rule.key, op=op, reason=entry.reason)


def _openings_text(ops: tuple[str, ...], methods: tuple[str, ...]) -> str:
    parts = [op for op in ops if op != "call"]
    if "call" in ops or methods:
        parts.append(f"call ({', '.join(methods)})" if methods else "call")
    return ", ".join(parts)


def _check_reason(rule: Rule, reason: str | None, path: str) -> None:
    ops, tier, methods = rule_openings(rule)
    required = bool(ops or methods)
    if reason is not None and len(reason) > REASON_MAX:
        raise _error(None, "reason-text", path=path, key=rule.key)
    if reason is not None and len(reason) >= REASON_MIN:
        return
    if required:
        tier = tier or "outbound"
        raise _error("E15", path=path, key=rule.key, ops=_openings_text(ops, methods),
                     article="an" if tier[0] in "aeiou" else "a", tier=tier)
    if reason is not None:  # given but too short, on an entry that does not need one
        raise _error(None, "reason-text", path=path, key=rule.key)


def _fields(fields: Any, path: str) -> tuple[frozenset[str], tuple[tuple[str, str], ...]]:
    if not isinstance(fields, dict):
        raise _error(None, "fields-type", path=path)
    for key in fields:
        if key not in FIELDS_KEYS:
            raise _error(None, "fields-key", path=path, key=_shown(key))
    withhold = fields.get("withhold", [])
    if not isinstance(withhold, list):
        raise _error(None, "fields-list", path=path, list="withhold")
    for index, name in enumerate(withhold):
        if not isinstance(name, str) or not (
                _MODEL_FIELD.fullmatch(name) or _ANY_MODEL_FIELD.fullmatch(name)):
            raise _error("E17", path=path, list="withhold", index=index, value=_shown(name))
    allow = fields.get("allow", [])
    if not isinstance(allow, list):
        raise _error(None, "fields-list", path=path, list="allow")
    released = []
    for index, item in enumerate(allow):
        if not isinstance(item, dict) or "field" not in item or set(item) - set(ALLOW_KEYS):
            raise _error(None, "allow-type", path=path, index=index)
        name = item["field"]
        if not isinstance(name, str) or not _MODEL_FIELD.fullmatch(name):
            raise _error("E17", path=path, list="allow", index=index, value=_shown(name))
        reason = item.get("reason")
        text = _printable(reason) if isinstance(reason, str) else ""
        if len(text) < REASON_MIN:
            raise _error("E20", path=path, index=index)
        if len(text) > REASON_MAX:
            raise _error(None, "allow-reason", path=path, index=index)
        released.append((name, text))
    return frozenset(withhold), tuple(released)


def _tools(tools: Any, path: str, tool_names: Iterable[str]) -> frozenset[str]:
    if not isinstance(tools, dict):
        raise _error(None, "tools-type", path=path)
    for key in tools:
        if key not in TOOLS_KEYS:
            raise _error(None, "tools-key", path=path, key=_shown(key))
    disabled = tools.get("disabled", [])
    if not isinstance(disabled, list):
        raise _error(None, "tools-type", path=path)
    known = set(tool_names)
    for name in disabled:
        if not isinstance(name, str) or name not in known:
            raise _error("E14", path=path, name=_shown(name))
    return frozenset(disabled)


# --- warnings -------------------------------------------------------------------

def policy_warnings(policy: Policy, today: datetime.date,
                    file_mode: int | None = None) -> tuple[tuple[str, str], ...]:
    """W1 to W7 for a valid policy, ordered by code, in file order within a code.

    They do not lock: they appear in odoo_version, --check-policy and the audit
    start line.
    """
    found: list[tuple[str, str]] = []
    if policy.profile_name == "builder":
        found.append(("W6", WARNINGS["W6"]))
    if file_mode is not None and file_mode & 0o022:
        found.append(("W3", WARNINGS["W3"].format(octal=f"{file_mode & 0o7777:04o}")))
    for rule in policy.rules:
        if _refuses_writes_but_not_calls(policy, rule):
            found.append(("W1", WARNINGS["W1"].format(key=rule.key)))
        if rule.exact:
            if rule.expired(today):
                assert rule.expires is not None
                found.append(("W4", WARNINGS["W4"].format(key=rule.key,
                                                          date=rule.expires.isoformat())))
                continue
            ops, tier, methods = rule_openings(rule)
            if ops or methods:
                until = f" until {rule.expires.isoformat()}" if rule.expires else ""
                found.append(("W2", WARNINGS["W2"].format(
                    model=rule.key, ops=_openings_text(ops, methods), tier=tier or "outbound",
                    until=until, reason=rule.reason)))
        else:
            pattern = _pattern_warning(policy, rule)
            if pattern:
                found.append(("W5", pattern))
    for name, reason in policy.allow:
        found.append(("W7", WARNINGS["W7"].format(field=name, reason=reason)))
    return tuple(sorted(found, key=lambda item: int(item[0][1:])))


def _covers(broader: str, key: str) -> bool:
    """Whether the pattern ``broader`` matches every model ``key`` names."""
    if broader == key:
        return False
    if broader == "*":
        return True
    if key == "*":
        return False
    return key.startswith(broader[:-1])


def _refuses_writes_but_not_calls(policy: Policy, rule: Rule) -> bool:
    """W1: the entry refuses write, while business methods may still run."""
    if rule.get("write") is not False:
        return False
    call = rule.get("call")
    if call is not None:
        return call is True
    profile = policy.profile
    assert profile is not None
    if rule.exact and profile.tiers is not None:
        tiers = {tier for name in model_aliases(rule.key) for tier in model_tiers(name)}
        if any("call" not in profile.tiers[tier] for tier in tiers):
            return False  # a tier withholds call there anyway
    broader = [other for other in policy.rules if not other.exact
               and other.get("call") is not None and _covers(other.key, rule.key)]
    if broader:
        return max(broader, key=lambda other: other.specificity).get("call") is True
    return "call" in profile.default


def _overlaps(key: str, tier: Tier) -> bool:
    """Whether the pattern ``key`` can match a model of ``tier``."""
    if key == "*":
        return True
    prefix = key[:-1]
    for pattern in tier.models:
        if pattern.endswith(".*"):
            other = pattern[:-1]
            if other.startswith(prefix) or prefix.startswith(other):
                return True
        elif pattern.startswith(prefix):
            return True
    return False


def _pattern_warning(policy: Policy, rule: Rule) -> str | None:
    """W5: a pattern that allows an operation some tier it reaches withholds."""
    profile = policy.profile
    assert profile is not None
    if profile.tiers is None:
        return None
    ops = []
    for op in OPERATIONS:
        value = rule.get(op)
        if value is True or (isinstance(value, frozenset) and bool(value)):
            ops.append(op)
    tiers: set[str] = set()
    for op in ops:
        for tier in TIERS:
            if op not in profile.tiers[tier.name] and _overlaps(rule.key, tier):
                tiers.add(tier.name)
        if op != "read":
            for child, (parent, _link) in DELEGATES.items():
                if rule.matches(child):
                    tiers.update(name for name in model_tiers(parent)
                                 if op not in profile.tiers[name])
    call = rule.get("call")
    if isinstance(call, frozenset) and call & OUTBOUND_METHODS:
        tiers.add("outbound")
    if not tiers:
        return None
    return WARNINGS["W5"].format(key=rule.key, op=", ".join(ops),
                                 tiers=", ".join(name for name in TIER_NAMES if name in tiers))
