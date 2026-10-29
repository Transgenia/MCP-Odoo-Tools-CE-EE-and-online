#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""End-to-end check of a local sandbox through the plugin's own MCP server.

Used by the sandbox matrix workflow after ``deploy_local.py sandbox up``:
``python3 scripts/sandbox_smoke.py --dir <sandbox dir> --expect 17
[--install-automation]``.
It starts ``server/run_stdio.py`` with the sandbox credentials (read from the
owner-only ``.env``, never printed), speaks MCP over stdio exactly as Claude
Code does, and checks ``odoo_version`` plus a bounded ``odoo_search_read``.
It then checks the field entries of the plugin's cross-version table
(``compat/deltas.py``) against the live instance, for every model it has.

The permission policy is checked against the same instance (design 9.7):

* under the default profile ``standard``: the ``policy`` block of
  ``odoo_version`` (profile, digest and hidden tools, compared with
  ``run_stdio.py --check-policy``); the refusals that need live metadata (a
  ``res.company`` write linking ``user_ids``, a ``res.partner`` write with a
  ``user_ids`` command, a user's contact e-mail, credential-like fields in field
  lists, filters and full reads, ``ir.attachment`` searches pinned to
  ``certificate.key``, an ``odoo_execute`` read whose trailing positional
  argument is a context holding a list default, which Odoo 10 to 12 would take as
  the call's context); each ``DELEGATES`` row whose child model is installed
  (its link field is a many2one to the parent); and a table of the tier model
  names that exist on this series (``ir.model``), printed, not asserted;
* under ``builder``: ``odoo_add_field`` adds a throwaway ``x_`` field on
  ``res.partner``, and ``odoo_add_automation`` creates an automation that never
  fires (``base.action.rule`` on 10, ``base.automation`` from 11) when Odoo's
  automated actions module is installed. Both are removed again;
* afterwards, the audit trail both sessions wrote to a folder inside the
  sandbox directory verifies with ``run_stdio.py --verify-audit``, records every
  refusal above with its rule, and never holds the admin password. The folder
  is removed when every check passes and kept for inspection otherwise.

A check whose model or field does not exist on the series is skipped, with the
reason in the report. ``--install-automation`` first installs the automated
actions module (``base_action_rule`` on 10, ``base_automation`` from 11) over
XML-RPC as the sandbox admin: odoo-tools itself never installs modules.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import xmlrpc.client
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server" / "src"))

from odoo_mcp.compat import EnvFacts, resolve_field, resolve_model
from odoo_mcp.compat.deltas import FIELD_REMOVED, FIELD_RENAMES
from odoo_mcp.compat.detect import parse_version
from odoo_mcp.policy.tiers import BEST_EFFORT, DELEGATES, NEVER, TIERS, pattern_matches

RUN_STDIO = ROOT / "server" / "run_stdio.py"
DIGEST = re.compile(r"[0-9a-f]{12}")
# "(profile 'standard', rule tier:security, alias of ...)": the rule token alone.
RULE = re.compile(r"\(profile '[^']*', rule ([^\s,)]+)")
AUDIT_FILES = "odoo-tools-audit-*.jsonl"
# The series on which each DELEGATES row is documented to delegate (the comments
# of policy/tiers.py). Inside them the link field must be there; outside them a
# missing link field is reported as skipped, and a present one as a note.
DELEGATE_SERIES: dict[str, tuple[int | None, int | None]] = {
    "website.page": (11, None),
    "website.controller.page": (17, None),
    "ir.cron": (11, None),  # Odoo 10 crons call a model method, not a server action
    "base.automation": (11, 16),  # 17 links its actions through action_server_ids
    "product.document": (17, None),
    "documents.document": (None, 17),
}
# A field only the parent has: shown on the child when it really delegates.
PARENT_FIELDS = {"ir.ui.view": "arch", "ir.actions.server": "code", "ir.attachment": "datas"}
LINK_FIELDS = ("action_server_id", "action_server_ids", "server_action_ids")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def call(proc: subprocess.Popen, msg_id: int, method: str, params: dict) -> dict:
    assert proc.stdin and proc.stdout
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method,
                                 "params": params}) + "\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            raise SystemExit(f"MCP server exited before answering {method}")
        reply = json.loads(line)
        if reply.get("id") == msg_id:
            return reply


def tool(proc: subprocess.Popen, msg_id: int, name: str, arguments: dict) -> dict:
    reply = call(proc, msg_id, "tools/call", {"name": name, "arguments": arguments})
    result = reply.get("result") or {}
    text = (result.get("content") or [{}])[0].get("text", "")
    if result.get("isError") or "error" in reply:
        raise SystemExit(f"{name} failed: {text or reply.get('error')}")
    return json.loads(text)


def check_deltas(proc: subprocess.Popen, first_id: int, version: dict) -> dict:
    """Compare each field delta with the live ``fields_get`` of its model."""
    major, minor, raw = parse_version({"server_version": version.get("raw_version", "")})
    facts = EnvFacts(major, "community", "onprem", raw, minor)
    msg_id, checked, skipped, mismatches = first_id, [], [], []
    fields_of: dict[str, set[str] | None] = {}
    entries = [(d.model, d.field, "removed") for d in FIELD_REMOVED]
    entries += [(d.model, d.old, "renamed") for d in FIELD_RENAMES]
    for model, field, kind in entries:
        live_model = resolve_model(model, facts)
        if live_model not in fields_of:
            msg_id += 1
            models = tool(proc, msg_id, "odoo_list_models", {"like": live_model, "limit": 50})
            present = any(row.get("model") == live_model for row in models.get("models", []))
            fields_of[live_model] = None
            if present:
                msg_id += 1
                reply = tool(proc, msg_id, "odoo_fields_get",
                             {"model": live_model, "attributes": ["type"]})
                fields_of[live_model] = set(reply.get("fields", {}))
        live_fields = fields_of[live_model]
        label = f"{live_model}.{field}"
        if live_fields is None:
            skipped.append(f"{label} (model not installed)")
            continue
        expected = resolve_field(model, field, facts)
        if kind == "removed":
            ok = (expected is not None) == (field in live_fields)
        else:
            ok = expected in live_fields
        checked.append(f"{label} -> {expected}")
        if not ok:
            mismatches.append(f"{label}: the table resolves it to {expected!r}, the live "
                              f"model {'has' if field in live_fields else 'lacks'} '{field}'")
    return {"checked": checked, "skipped": skipped, "mismatches": mismatches}


# --------------------------------------------------------------- policy checks


@dataclasses.dataclass
class Outcome:
    """What one ``tools/call`` answered: its JSON, or the text of a tool error."""

    ok: bool
    text: str
    data: Any = None

    @property
    def rule(self) -> str | None:
        """The rule a policy refusal names (``relational``, ``tier:secrets``...)."""
        found = RULE.search(self.text)
        return found.group(1) if found else None


Run = Callable[[str, dict], Outcome]


def outcome(result: dict) -> Outcome:
    """The ``result`` of a ``tools/call`` reply as an Outcome."""
    text = (result.get("content") or [{}])[0].get("text", "")
    if result.get("isError"):
        return Outcome(False, text)
    return Outcome(True, text, json.loads(text))


def attempt(proc: subprocess.Popen, msg_id: int, name: str, arguments: dict) -> Outcome:
    """A ``tools/call`` whose tool error is an answer, not a failure of the run."""
    reply = call(proc, msg_id, "tools/call", {"name": name, "arguments": arguments})
    if "error" in reply:
        raise SystemExit(f"{name}: the MCP server answered with a protocol error: "
                         f"{reply['error']}")
    return outcome(reply.get("result") or {})


class Client:
    """Numbered ``tools/call`` requests to one server process, as a ``Run``."""

    def __init__(self, proc: subprocess.Popen, first_id: int = 100000) -> None:
        self.proc = proc
        self.msg_id = first_id

    def __call__(self, name: str, arguments: dict) -> Outcome:
        self.msg_id += 1
        return attempt(self.proc, self.msg_id, name, arguments)


@dataclasses.dataclass
class Checks:
    """What one group of checks found. ``refusals`` are the (tool, rule) pairs the
    policy refused as expected, which the audit trail must also hold."""

    checked: list[str] = dataclasses.field(default_factory=list)
    skipped: list[str] = dataclasses.field(default_factory=list)
    problems: list[str] = dataclasses.field(default_factory=list)
    notes: list[str] = dataclasses.field(default_factory=list)
    refusals: list[tuple[str, str]] = dataclasses.field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"checked": self.checked, "skipped": self.skipped,
                               "problems": self.problems}
        if self.notes:
            out["notes"] = self.notes
        return out


def short(text: str, limit: int = 300) -> str:
    """A tool's text on one line, cut to ``limit`` characters."""
    return " ".join(text.split())[:limit]


def expect_refused(run: Run, checks: Checks, label: str, name: str, arguments: dict,
                   rules: Iterable[str]) -> Outcome:
    """``name`` must be refused by the policy with one of ``rules``."""
    wanted = sorted(rules)
    got = run(name, arguments)
    if got.ok:
        checks.problems.append(f"{label}: {name} was allowed; expected a refusal by rule "
                               f"{' or '.join(wanted)}")
    elif got.rule not in wanted:
        checks.problems.append(f"{label}: {name} answered {short(got.text)!r}; expected a "
                               f"refusal by rule {' or '.join(wanted)}")
    else:
        checks.checked.append(f"{label}: refused (rule {got.rule})")
        checks.refusals.append((name, str(got.rule)))
    return got


def expect_allowed(run: Run, checks: Checks, label: str, name: str,
                   arguments: dict) -> Outcome:
    got = run(name, arguments)
    if got.ok:
        checks.checked.append(f"{label}: allowed")
    else:
        checks.problems.append(f"{label}: {name} answered {short(got.text)!r}; expected it "
                               "to be allowed")
    return got


def record_id(value: Any) -> int | None:
    """An id, a many2one ``[id, name]`` or a one-id list (JSON-2 ``create``)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, list) and value and isinstance(value[0], int) \
            and not isinstance(value[0], bool):
        return value[0]
    return None


def present_models(run: Run, names: Iterable[str]) -> set[str] | None:
    """Which of ``names`` exist on the instance (``ir.model``); None when unreadable."""
    wanted = sorted(set(names))
    got = run("odoo_search_read", {"model": "ir.model", "domain": [["model", "in", wanted]],
                                   "fields": ["model"], "limit": len(wanted) + 10})
    if not got.ok:
        return None
    return {row.get("model") for row in got.data.get("records") or [] if isinstance(row, dict)}


def fields_of(run: Run, model: str) -> dict[str, Any] | None:
    """``fields_get`` of ``model`` (type and relation); None when it fails."""
    got = run("odoo_fields_get", {"model": model, "attributes": ["type", "relation"]})
    if not got.ok or not isinstance(got.data.get("fields"), dict):
        return None
    return got.data["fields"]


def is_relation(fields: dict[str, Any] | None, name: str, ftype: str, comodel: str) -> bool:
    info = (fields or {}).get(name)
    return isinstance(info, dict) and info.get("type") == ftype \
        and info.get("relation") == comodel


def offline_policy(profile: str) -> dict[str, Any]:
    """What ``run_stdio.py --check-policy`` says about ``profile`` without a file."""
    proc = subprocess.run([sys.executable, str(RUN_STDIO), "--check-policy", "", "--profile",
                           profile, "--json"], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"--check-policy --profile {profile} failed: {short(proc.stdout)}")
    return json.loads(proc.stdout)


def check_policy_block(version: dict, profile: str, offline: dict[str, Any]) -> Checks:
    """The ``policy`` block of ``odoo_version`` against the offline check."""
    checks = Checks()
    block = version.get("policy")
    if not isinstance(block, dict):
        checks.problems.append("odoo_version returned no policy block")
        return checks
    expected = {"profile": profile, "error": None, "readonly": False,
                "digest": offline.get("digest"), "hidden_tools": offline.get("hidden_tools")}
    for key, value in expected.items():
        if block.get(key) != value:
            checks.problems.append(f"policy.{key} is {block.get(key)!r}, expected {value!r}")
        else:
            checks.checked.append(f"policy.{key} = {value!r}")
    if not DIGEST.fullmatch(str(block.get("digest"))):
        checks.problems.append("policy.digest is not 12 hex characters")
    codes = [w.get("code") for w in block.get("warnings") or [] if isinstance(w, dict)]
    if profile == "builder" and "W6" not in codes:
        checks.problems.append("profile builder loaded without warning W6")
    checks.notes.append(f"warnings: {', '.join(c for c in codes if c) or 'none'}"
                        + (" (W10: the sandbox admin is an administrator)" if "W10" in codes
                           else ""))
    return checks


def check_standard(run: Run, login: str) -> Checks:
    """The refusals of profile ``standard`` that need the instance's own metadata."""
    checks = Checks()
    me = run("odoo_search_read", {"model": "res.users", "domain": [["login", "=", login]],
                                  "fields": ["partner_id", "company_id"], "limit": 1})
    rows = me.data.get("records") if me.ok else None
    uid = partner = company = None
    if rows and isinstance(rows[0], dict):
        uid, partner = record_id(rows[0].get("id")), record_id(rows[0].get("partner_id"))
        company = record_id(rows[0].get("company_id"))
    if uid is None:
        checks.problems.append(f"the signed-in user could not be read: {short(me.text)!r}")
    company_fields = fields_of(run, "res.company")
    partner_fields = fields_of(run, "res.partner")
    user_fields = fields_of(run, "res.users")

    # A company's users are their allowed companies: linking one changes res.users.
    label = "res.company write linking user_ids"
    if uid is None or company is None:
        checks.skipped.append(f"{label} (no user or company to try it on)")
    elif not is_relation(company_fields, "user_ids", "many2many", "res.users"):
        checks.skipped.append(f"{label} (res.company.user_ids is not a many2many to res.users "
                              "on this series)")
    else:  # (4, uid) on the admin's own company: a no-op if it ever got through
        expect_refused(run, checks, label, "odoo_write",
                       {"model": "res.company", "ids": [company],
                        "values": {"user_ids": [[4, uid]]}}, {"relational"})

    label = "res.partner write with a user_ids command"
    if uid is None or partner is None:
        checks.skipped.append(f"{label} (no user or contact to try it on)")
    elif not is_relation(partner_fields, "user_ids", "one2many", "res.users"):
        checks.skipped.append(f"{label} (res.partner.user_ids is not a one2many to res.users "
                              "on this series)")
    else:  # (4, uid) on the admin's own contact: a no-op if it ever got through
        expect_refused(run, checks, label, "odoo_write",
                       {"model": "res.partner", "ids": [partner],
                        "values": {"user_ids": [[4, uid]]}}, {"relational"})

    label = "a user's contact e-mail"
    if partner is None or "email" not in (partner_fields or {}):
        checks.skipped.append(f"{label} (no contact with an email field)")
    else:
        current = run("odoo_read", {"model": "res.partner", "ids": [partner],
                                    "fields": ["email"]})
        records = current.data.get("records") if current.ok else None
        if not records:
            checks.problems.append(f"{label}: the contact could not be read: "
                                   f"{short(current.text)!r}")
        else:  # the e-mail it already has: a no-op if it ever got through
            expect_refused(run, checks, label, "odoo_write",
                           {"model": "res.partner", "ids": [partner],
                            "values": {"email": records[0].get("email")}}, {"identity"})

    label = "res.users.password"
    if uid is None or "password" not in (user_fields or {}):
        checks.skipped.append(f"{label} (no user, or no password field on this series)")
    else:
        expect_refused(run, checks, f"{label} in a field list", "odoo_read",
                       {"model": "res.users", "ids": [uid], "fields": ["login", "password"]},
                       {"field"})
        whole = run("odoo_read", {"model": "res.users", "ids": [uid]})
        records = whole.data.get("records") if whole.ok else None
        if not whole.ok and whole.rule:
            checks.problems.append(f"{label}: a read without a field list was refused: "
                                   f"{short(whole.text)!r}")
        elif not whole.ok:
            checks.skipped.append(f"{label} in a full read (Odoo refused the read: "
                                  f"{short(whole.text, 120)})")
        elif not records:
            checks.skipped.append(f"{label} in a full read (no row returned)")
        elif any(isinstance(row, dict) and "password" in row for row in records):
            checks.problems.append(f"{label}: a read without a field list returned it")
        else:
            checks.checked.append(f"{label} withheld from a read without a field list "
                                  f"(policy_withheld_fields: "
                                  f"{whole.data.get('policy_withheld_fields') or []})")

    label = "res.partner.signup_token"
    if "signup_token" not in (partner_fields or {}):
        checks.skipped.append(f"{label} (not on this series or auth_signup not installed)")
    else:
        expect_refused(run, checks, f"{label} in a field list", "odoo_search_read",
                       {"model": "res.partner", "fields": ["name", "signup_token"],
                        "limit": 1}, {"field"})
        expect_refused(run, checks, f"{label} in a filter", "odoo_search_count",
                       {"model": "res.partner", "domain": [["signup_token", "=like", "a%"]]},
                       {"field"})

    label = "ir.attachment"
    if "res_model" not in (fields_of(run, "ir.attachment") or {}):
        checks.skipped.append(f"{label} (no res_model field on this series)")
    else:
        present = present_models(run, ["certificate.key"]) or set()
        checks.notes.append("certificate.key " + ("exists" if "certificate.key" in present
                                                  else "does not exist") + " on this series")
        expect_refused(run, checks, f"{label} search pinned to certificate.key",
                       "odoo_search_read",
                       {"model": "ir.attachment", "domain": [["res_model", "=", "certificate.key"]],
                        "fields": ["name"], "limit": 1}, {"tier:secrets"})
        expect_refused(run, checks, f"{label} search for certificate.key field files",
                       "odoo_search_read",
                       {"model": "ir.attachment",
                        "domain": [["res_model", "=", "certificate.key"],
                                   ["res_field", "!=", False]],
                        "fields": ["name", "datas"], "limit": 1}, {"attachment-pin"})
        expect_refused(run, checks, f"{label} search without res_model", "odoo_search_read",
                       {"model": "ir.attachment", "domain": [], "fields": ["name"], "limit": 1},
                       {"attachment-pin"})
        expect_allowed(run, checks, f"{label} search pinned to res.partner", "odoo_search_read",
                       {"model": "ir.attachment", "domain": [["res_model", "=", "res.partner"]],
                        "fields": ["name"], "limit": 1})

    # Odoo 10 to 12 also take a call's context from the positional argument after the
    # method's parameters. The policy reads it as one on every series, so a list default
    # there is refused before anything reaches Odoo (design E1). A search_read on a domain
    # that matches nothing: a read, so nothing would be created even if the control failed.
    expect_refused(run, checks, "odoo_execute with a trailing positional context holding a "
                   "list default", "odoo_execute",
                   {"model": "res.partner", "method": "search_read",
                    "args": [[["id", "=", 0]], ["name"], 0, 1, "id",
                             {"default_category_id": [[6, 0, []]]}]}, {"context"})
    return checks


def in_series(major: int, span: tuple[int | None, int | None]) -> bool:
    first, last = span
    return (first is None or major >= first) and (last is None or major <= last)


def span_text(span: tuple[int | None, int | None]) -> str:
    first, last = span
    if first is None:
        return f"up to {last}"
    return f"{first}+" if last is None else f"{first}-{last}"


def check_delegates(run: Run, major: int) -> Checks:
    """Each installed DELEGATES child links its parent through a many2one."""
    checks = Checks()
    present = present_models(run, DELEGATES)
    if present is None:
        checks.problems.append("ir.model could not be read for the DELEGATES rows")
        return checks
    for child, (parent, link) in sorted(DELEGATES.items()):
        span = DELEGATE_SERIES.get(child, (None, None))
        label = f"{child}.{link}"
        if child not in present:
            checks.skipped.append(f"{label} (model not installed)")
            continue
        fields = fields_of(run, child)
        if fields is None:
            checks.problems.append(f"{label}: fields_get({child}) failed")
            continue
        info = fields.get(link)
        if not isinstance(info, dict):
            if in_series(major, span):
                checks.problems.append(f"{label} is missing, but the table says {child} "
                                       f"delegates to {parent} on Odoo {span_text(span)}")
            else:
                checks.skipped.append(f"{label} (no delegation on this series; documented "
                                      f"for Odoo {span_text(span)})")
            continue
        if info.get("type") != "many2one" or info.get("relation") != parent:
            checks.problems.append(f"{label} is a {info.get('type')} to "
                                   f"{info.get('relation')}, the table says a many2one to "
                                   f"{parent}")
            continue
        probe = PARENT_FIELDS.get(parent)
        if probe and probe not in fields:
            checks.problems.append(f"{child} does not show {parent}.{probe}, so it does not "
                                   f"delegate to {parent} through {link}")
            continue
        checks.checked.append(f"{label} -> many2one {parent}"
                              + (f" ({parent}.{probe} shown on {child})" if probe else ""))
        if not in_series(major, span):
            checks.notes.append(f"{child} delegates to {parent} on Odoo {major} too, outside "
                                f"the documented series ({span_text(span)})")
    return checks


def tier_patterns() -> list[tuple[str, str]]:
    """(group, pattern): every tier entry, then the DELEGATES children and NEVER."""
    rows = [(tier.name, pattern) for tier in TIERS for pattern in tier.models]
    rows += [("delegates", child) for child in DELEGATES]
    rows += [("never", entry.model) for entry in NEVER]
    out: list[tuple[str, str]] = []
    for row in rows:
        if row not in out:
            out.append(row)
    return out


def tier_models(run: Run) -> tuple[list[dict[str, Any]], list[str]]:
    """Which tier model names exist here (``ir.model``): rows for the table, problems."""
    patterns = tier_patterns()
    exact = sorted({p for _g, p in patterns if not p.endswith(".*")})
    prefixes = sorted({p for _g, p in patterns if p.endswith(".*")})
    found: set[str] = set()
    problems: list[str] = []
    named = present_models(run, exact)
    if named is None:
        problems.append("ir.model could not be read for the tier table")
    found |= named or set()
    for prefix in prefixes:
        got = run("odoo_search_read", {"model": "ir.model",
                                       "domain": [["model", "=like", prefix[:-1] + "%"]],
                                       "fields": ["model"], "limit": 5000})
        if not got.ok:
            problems.append(f"ir.model could not be read for {prefix}")
            continue
        found |= {row.get("model") for row in got.data.get("records") or []
                  if isinstance(row, dict) and isinstance(row.get("model"), str)}
    tiers = {tier.name: tier for tier in TIERS}
    rows = []
    for group, pattern in patterns:
        tier = tiers.get(group)
        names = sorted(m for m in found if isinstance(m, str) and pattern_matches(pattern, m)
                       and (tier is None or m not in tier.exceptions))
        rows.append({"group": group, "pattern": pattern, "best_effort": pattern in BEST_EFFORT,
                     "found": names})
    return rows, problems


def format_table(rows: list[dict[str, Any]], major: Any, shown: int = 6) -> str:
    """The tier table as fixed-width text: group, pattern, best-effort, what exists."""
    head = ("tier", "pattern", "best-effort", f"on Odoo {major}")
    lines = []
    for row in rows:
        names = row["found"]
        if not names:
            where = "-"
        elif row["pattern"].endswith(".*"):
            where = f"{len(names)}: " + ", ".join(names[:shown]) \
                + (", ..." if len(names) > shown else "")
        else:
            where = "yes"
        lines.append((row["group"], row["pattern"], "yes" if row["best_effort"] else "", where))
    widths = [max(len(line[i]) for line in [head, *lines]) for i in range(3)]
    out = [f"Tier model names on Odoo {major} (read from ir.model; reported, not asserted)"]
    for line in [head, *lines]:
        out.append("  ".join(cell.ljust(width) for cell, width in zip(line, widths))
                   + "  " + line[3])
    return "\n".join(out)


def automation_state(run: Run, major: int) -> bool | str:
    """True when Odoo's automated actions module is installed, else the reason."""
    module = "base_action_rule" if major == 10 else "base_automation"
    got = run("odoo_module_info", {"name": module})
    if not got.ok:
        return f"odoo_module_info({module}) failed: {short(got.text, 120)}"
    info = got.data.get("module")
    if not isinstance(info, dict):
        return f"{module} is not available on this series"
    if info.get("state") != "installed":
        return f"{module} is not installed (run with --install-automation)"
    return True


def check_builder(run: Run, major: int, field_name: str, automation: bool | str) -> Checks:
    """The Studio-style tools under profile ``builder``, each change removed again."""
    checks = Checks()
    added = run("odoo_add_field", {"model": "res.partner", "name": field_name,
                                   "label": "odoo-tools smoke test", "field_type": "char",
                                   "help": "Created by scripts/sandbox_smoke.py and removed "
                                           "by it."})
    field_id = record_id(added.data.get("field_id")) if added.ok else None
    if not added.ok or field_id is None:
        checks.problems.append(f"odoo_add_field res.partner.{field_name}: "
                               f"{short(added.text)!r}")
    else:
        live = fields_of(run, "res.partner") or {}
        if (live.get(field_name) or {}).get("type") != "char":
            checks.problems.append(f"odoo_add_field: res.partner.{field_name} is not a char "
                                   "field in fields_get afterwards")
        else:
            checks.checked.append(f"odoo_add_field: res.partner.{field_name} (char) created")
        removed = run("odoo_unlink", {"model": "ir.model.fields", "ids": [field_id]})
        checks.notes.append(f"removing res.partner.{field_name}: "
                            + ("done" if removed.ok else short(removed.text, 160)))

    model = "base.action.rule" if major == 10 else "base.automation"
    if automation is not True:
        checks.skipped.append(f"odoo_add_automation on {model} ({automation})")
        return checks
    made = run("odoo_add_automation", {"model": "res.partner", "name": "odoo-tools smoke test",
                                       "code": "pass", "trigger": "on_create_or_write",
                                       "filter_domain": [["id", "=", 0]]})
    auto_id = record_id(made.data.get("automation_id")) if made.ok else None
    if not made.ok or auto_id is None:
        checks.problems.append(f"odoo_add_automation on {model}: {short(made.text)!r}")
        return checks
    mode = made.data.get("mode")
    server_id = record_id(made.data.get("server_action_id"))
    automation_fields = fields_of(run, model) or {}
    link = next((name for name in LINK_FIELDS if name in automation_fields), None)
    wanted = ["name"] + ([link] if mode == "linked-server-action" and link else [])
    read = run("odoo_read", {"model": model, "ids": [auto_id], "fields": wanted})
    rows = read.data.get("records") if read.ok else None
    if not rows:
        checks.problems.append(f"odoo_add_automation: {model} {auto_id} cannot be read back: "
                               f"{short(read.text)!r}")
    elif mode == "linked-server-action":
        value = rows[0].get(link) if link else None
        linked = value if isinstance(value, list) else [value]
        if server_id is None or not (server_id in linked or record_id(value) == server_id):
            checks.problems.append(f"odoo_add_automation: {model} {auto_id} is not linked to "
                                   f"server action {server_id} ({link} = {value!r})")
        else:
            checks.checked.append(f"odoo_add_automation: {model} {auto_id} linked to server "
                                  f"action {server_id} through {link}")
    else:
        checks.checked.append(f"odoo_add_automation: {model} {auto_id} created ({mode})")
    cleanup = [(model, auto_id)] + ([("ir.actions.server", server_id)] if server_id else [])
    for target, record in cleanup:
        removed = run("odoo_unlink", {"model": target, "ids": [record]})
        checks.notes.append(f"removing {target} {record}: "
                            + ("done" if removed.ok else short(removed.text, 160)))
    return checks


def check_audit(directory: Path, *, starts: int, refusals: Iterable[tuple[str, str]],
                secret: str) -> Checks:
    """The audit files verify, hold the expected starts and refusals, and no secret."""
    checks = Checks()
    files = sorted(Path(directory).glob(AUDIT_FILES))
    if not files:
        checks.problems.append(f"no audit file was written in {directory}")
        return checks
    lines: list[dict[str, Any]] = []
    for path in files:
        proc = subprocess.run([sys.executable, str(RUN_STDIO), "--verify-audit", str(path)],
                              capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            checks.problems.append(f"--verify-audit {path.name}: {short(proc.stdout)}")
        else:
            checks.checked.append(f"--verify-audit {path.name}: chain intact")
        raw = path.read_bytes()
        if secret and secret.encode("utf-8") in raw:
            checks.problems.append(f"{path.name} holds the sandbox admin password")
        for line in raw.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue  # --verify-audit names the line
            if isinstance(entry, dict):
                lines.append(entry)
    started = sum(1 for entry in lines if entry.get("event") == "start")
    if started != starts:
        checks.problems.append(f"the audit holds {started} start lines, expected {starts}")
    else:
        checks.checked.append(f"{started} start lines, one per server start")
    denied = {(entry.get("tool"), entry.get("rule")) for entry in lines
              if entry.get("event") == "call" and entry.get("decision") == "deny"}
    for name, rule in refusals:
        if (name, rule) not in denied:
            checks.problems.append(f"the audit has no refused {name} call with rule {rule}")
    calls = sum(1 for entry in lines if entry.get("event") == "call")
    checks.checked.append(f"{calls} call lines, {len(denied)} distinct refusals (tool, rule)")
    return checks


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout: float) -> None:
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host: Any) -> Any:
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


def install_automation(url: str, db: str, login: str, password: str, major: int,
                       timeout: float = 900.0) -> str:
    """Install Odoo's automated actions module over XML-RPC, as the sandbox admin,
    before the MCP sessions start (test setup: the policy closes ir.module.module
    to the agent). Returns what was done; the password is never shown."""
    module = "base_action_rule" if major == 10 else "base_automation"

    def proxy(service: str) -> xmlrpc.client.ServerProxy:
        return xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/{service}", allow_none=True,
                                         transport=_TimeoutTransport(timeout))

    try:
        uid = proxy("common").authenticate(db, login, password, {})
        if not uid:
            raise SystemExit("the sandbox admin could not sign in over XML-RPC")
        objects = proxy("object")
        rows = objects.execute_kw(db, uid, password, "ir.module.module", "search_read",
                                  [[["name", "=", module]]], {"fields": ["state"]})
        if not rows:
            return f"{module} is not available on this series"
        if rows[0].get("state") == "installed":
            return f"{module} was already installed"
        objects.execute_kw(db, uid, password, "ir.module.module", "button_immediate_install",
                           [[rows[0]["id"]]])
    except xmlrpc.client.Fault as exc:
        last = (str(exc.faultString or "").strip().splitlines() or [""])[-1]
        raise SystemExit(f"installing {module} failed: {short(last, 200)}") from None
    return f"{module} installed"


def start_server(env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, str(RUN_STDIO)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, env=env)


def stop_server(proc: subprocess.Popen) -> None:
    if proc.stdin:
        proc.stdin.close()
    proc.wait(timeout=30)


def initialize(proc: subprocess.Popen) -> dict:
    init = call(proc, 1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                        "clientInfo": {"name": "sandbox-smoke", "version": "1"}})
    return init["result"]["serverInfo"]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dir", required=True, help="sandbox directory (holds .env)")
    parser.add_argument("--expect", type=int, required=True, help="expected Odoo major")
    parser.add_argument("--install-automation", action="store_true",
                        help="install Odoo's automated actions module first (XML-RPC, as "
                        "the sandbox admin) so the builder check covers odoo_add_automation")
    args = parser.parse_args(argv)
    sandbox = Path(args.dir).expanduser()
    env_file = read_env(sandbox / ".env")
    url = f"http://localhost:{env_file['ODOO_PORT']}"
    login, secret = env_file["ODOO_ADMIN_LOGIN"], env_file["ODOO_ADMIN_PASSWORD"]
    fixture = None
    if args.install_automation:
        fixture = install_automation(url, env_file["ODOO_DB"], login, secret, args.expect)
    offline = {profile: offline_policy(profile) for profile in ("standard", "builder")}
    audit_dir = Path(tempfile.mkdtemp(prefix="smoke-audit-", dir=str(sandbox)))
    env = dict(os.environ)
    env.update({
        "ODOO_URL": url,
        "ODOO_DB": env_file["ODOO_DB"],
        "ODOO_LOGIN": login,
        "ODOO_PASSWORD": secret,
        "ODOO_API_KEY": "",
        "ODOO_POLICY": "standard",
        "ODOO_POLICY_FILE": "",
        "ODOO_READONLY": "",
        "ODOO_AUDIT_DIR": str(audit_dir),
    })
    proc = start_server(env)
    try:
        server = initialize(proc)
        version = tool(proc, 2, "odoo_version", {})
        partners = tool(proc, 3, "odoo_search_read",
                        {"model": "res.partner", "fields": ["name"], "limit": 1})
        deltas = check_deltas(proc, 3, version)
        major = version.get("version") if isinstance(version.get("version"), int) \
            else args.expect
        run = Client(proc)
        standard_block = check_policy_block(version, "standard", offline["standard"])
        standard = check_standard(run, login)
        delegates = check_delegates(run, major)
        tier_rows, tier_problems = tier_models(run)
        automation = automation_state(run, major)
    finally:
        stop_server(proc)

    env["ODOO_POLICY"] = "builder"
    proc = start_server(env)
    try:
        initialize(proc)
        builder_version = tool(proc, 2, "odoo_version", {})
        builder_block = check_policy_block(builder_version, "builder", offline["builder"])
        builder = check_builder(Client(proc), major, f"x_smoke_{secrets.token_hex(3)}",
                                automation)
    finally:
        stop_server(proc)

    audit = check_audit(audit_dir, starts=2, refusals=standard.refusals, secret=secret)
    print(format_table(tier_rows, major))
    groups = {"standard: odoo_version": standard_block, "standard: refusals": standard,
              "standard: delegation": delegates, "builder: odoo_version": builder_block,
              "builder: studio tools": builder, "audit": audit}
    report = {"server": server, "odoo": version,
              "partners_read": len(partners.get("records", [])), "deltas": deltas,
              "policy": {name: checks.as_dict() for name, checks in groups.items()}}
    report["policy"]["tier_models"] = {f"{row['group']}:{row['pattern']}": row["found"]
                                       for row in tier_rows}
    if fixture:
        report["policy"]["fixture"] = fixture
    report["policy"]["audit_dir"] = str(audit_dir)
    print(json.dumps(report, indent=2))
    if version.get("version") != args.expect:
        raise SystemExit(f"expected Odoo {args.expect}, the server reports {version}")
    if version.get("edition") != "community":
        raise SystemExit(f"expected a Community sandbox, got {version.get('edition')}")
    if report["partners_read"] < 1:
        raise SystemExit("res.partner returned no record")
    if not deltas["checked"]:
        raise SystemExit("no cross-version field entry could be checked")
    if deltas["mismatches"]:
        raise SystemExit("cross-version table disagrees with the live instance: "
                         + "; ".join(deltas["mismatches"]))
    problems = [f"{name}: {problem}" for name, checks in groups.items()
                for problem in checks.problems] + tier_problems
    if problems:
        raise SystemExit(f"permission policy checks failed (audit kept in {audit_dir}): "
                         + "; ".join(problems))
    shutil.rmtree(audit_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
