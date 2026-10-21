# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""What the permission policy tells the agent: refusals, their hints, the instructions line.

A refusal names the profile and the rule that decided, says whether anything
reached Odoo, gives the remedy, and asks the agent not to reach the same result
through another tool. Only validated tokens are echoed: model, field, method
and operation names, the rule names and the keys of the policy file. An
argument value never is (an invalid name is described, not repeated); record
ids, which the schemas hold to integers, are the one exception the attachment
and identity hints make.

Each refusal is a :class:`~odoo_mcp.errors.PolicyDenied`, whose message and
remedy CompatError joins with its usual separator.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from ..errors import PolicyDenied, PolicyEnvelopeError
from ..support import SUPPORT_EMAIL
from .classify import valid_model
from .model import Decision, Policy

# --- where a refusal comes from --------------------------------------------------
LAYER_A_SUFFIX = "Nothing was sent to Odoo."
LAYER_B_SUFFIX = ("The call was stopped before Odoo ran it: nothing was changed and no record "
                  "data was returned.")
SUFFIXES = {"tool": LAYER_A_SUFFIX, "A": LAYER_A_SUFFIX, "B": LAYER_B_SUFFIX}
NO_WORKAROUND = "do not use another tool to do the same thing."

# --- tool-level refusals (tools/list hides these tools) ----------------------------
HIDDEN = ("{tool} is not available: the odoo-tools permission policy (profile '{profile}') "
          "allows '{op}' on no model. Nothing was sent to Odoo.")
HIDDEN_REMEDY = ("the user can change this in the plugin options 'Permission profile' or "
                 "'Permission policy file'; " + NO_WORKAROUND)
DISABLED = ("{tool} is disabled by the odoo-tools permission policy file ({path}). Nothing was "
            "sent to Odoo.")
DISABLED_REMEDY = "the user can change this in the policy file; " + NO_WORKAROUND
UNMAPPED = ("internal error: tool '{tool}' has no permission mapping, so it is refused (fail "
            "closed)")
# The same words as server.check_readonly, which runs first and stays unchanged.
READ_ONLY_TOOL = "tool '{tool}' is disabled: the server runs with ODOO_READONLY=1"
READ_ONLY_REMEDY = ("unset ODOO_READONLY and restart for writes, or use a read-only tool "
                    "(search/read/fields_get/export/report/odoo_online_profile/"
                    "odoo_access_check)")

# --- a refused check -------------------------------------------------------------
REFUSED = ("the odoo-tools permission policy refuses '{op}' on '{model}' (profile '{profile}', "
           "rule {rule}). {suffix}")
REFUSED_UNNAMED = ("the odoo-tools permission policy refuses '{op}' on this model (profile "
                   "'{profile}', rule {rule}). {suffix}")
ENVELOPE = ("internal error: {tool} tried {model}.{method}, which its permission mapping does "
            "not declare. The call was stopped before it reached Odoo. This is a bug in "
            "odoo-tools; please report it to " + SUPPORT_EMAIL + ".")
GUARD_FAILURE = ("internal error: the odoo-tools permission policy could not check a call of "
                 "{tool} ({kind}), so it was stopped before it reached Odoo (fail closed). This "
                 "is a bug in odoo-tools; please report it to " + SUPPORT_EMAIL + ".")
# odoo_online_profile reports a section the policy refuses instead of failing.
WITHHELD_SECTION = "withheld by the odoo-tools permission policy ({op} on {model})"
WITHHELD_SECTION_RULE = "withheld by the odoo-tools permission policy (rule {rule})"

# --- hints, by rule ----------------------------------------------------------------
NEVER_HINT = ("odoo-tools never creates, changes or revokes API keys and never uninstalls "
              "modules, in any profile; do this in Odoo itself")
TIER_HINTS = {
    "secrets": ("this model holds credentials or acts as one; only an entry naming it exactly, "
                "with a reason, in the policy file opens it"),
    "security": ("users, groups, access rules, modules, API keys, bank accounts, chatter "
                 "history and fiscal sequences are read-only outside profile 'full' unless the "
                 "policy file names the model exactly, with a reason"),
    "outbound": ("this model sends e-mail, SMS, letters or share links, or decides what is sent; "
                 "only an entry naming it exactly, with a reason, opens it"),
    "customization": ("fields, views, automations and other ir.* records need profile "
                      "'builder', or an entry naming the model exactly, with a reason"),
}
OUTBOUND_HINT = ("'{method}' sends e-mail, SMS or notifications; profile '{profile}' allows "
                 "internal notes only (message_post with subtype_xmlid 'mail.mt_note' and no "
                 "partner_ids). An entry naming '{model}' exactly with \"call\": [\"{method}\"] "
                 "and a reason allows it")
UNLINK_HINT = ("profile '{profile}' does not delete: archive instead (odoo_write "
               "{{\"active\": false}}) where the model has an active field, or ask the user to "
               "allow unlink")
SCHEMA_HINT = ("profile '{profile}' makes no Studio-style changes (new fields, automations): "
               "they need profile 'builder', or an entry setting \"schema\": true for the model "
               "in the policy file")
READONLY_PROFILE_HINT = ("profile 'readonly' allows reads only; the user can choose another "
                         "profile in the plugin option 'Permission profile'")
PROFILE_HINT = ("profile '{profile}' does not allow '{op}' here; the user can choose another "
                "profile in the plugin option 'Permission profile', or allow it in the policy "
                "file")
READONLY_HINT = ("Read-only mode is on (ODOO_READONLY=1): only reads are allowed until the user "
                 "turns it off in the plugin options")
FIELD_HINT = ("field '{field}' of '{model}' looks like a credential or token and is not read, "
              "written, filtered, grouped or sorted on through these tools; read other fields, "
              "or release it with fields.allow in the policy file")
FIELD_FILE_HINT = ("field '{field}' of '{model}' is withheld by the policy file "
                   "(fields.withhold) and is not read, written, filtered, grouped or sorted on "
                   "through these tools; read other fields")
RELATIONAL_HINT = ("this {method} on '{model}' also {op}s '{comodel}' through field '{field}' "
                   "(command {n}), and the policy refuses '{op}' on '{comodel}' ({rule})")
# A field path (a domain leaf, a read specification, an export or import column,
# a groupby or order term) that reaches another model.
PATH_HINT = ("this {method} on '{model}' also {op}s '{comodel}' through '{path}', and the "
             "policy refuses '{op}' on '{comodel}' ({rule})")
UNVERIFIED_HINT = ("could not verify the related models of this call (fields_get failed); "
                   "check that the Odoo user can read the field definitions of these models, "
                   "then retry")
ATTACHMENT_CREATE_HINT = ("an attachment created or changed through these tools cannot be "
                          "public and cannot store a field of a record (res_field); use "
                          "odoo_record_documents for a record's files")
IDENTITY_IMPORT_HINT = ("an import that updates existing contacts (an 'id' or '.id' column) "
                        "cannot set their 'email': a contact's e-mail can be the login identity "
                        "of an Odoo user (it receives password-reset links); change e-mails with "
                        "odoo_write, which checks each contact")
ATTACHMENT_PIN_HINT = ("generic access to ir.attachment must name the parent model: add "
                       "[\"res_model\", \"=\", \"<model>\"] to the domain and do not filter on "
                       "res_field, or use odoo_record_documents")
ATTACHMENT_FIELD_HINT = ("attachment {id} stores a field of a record, or belongs to a model the "
                         "policy does not let you {op}; use odoo_record_documents for a record's "
                         "files")
IDENTITY_HINT = ("contact {id} is the login identity of an Odoo user (its e-mail receives "
                 "password-reset links), so changing its e-mail counts as a change to "
                 "res.users; change it in Odoo's user settings")
DELEGATION_LINK_HINT = ("'{field}' would link {model} to an existing {parent} record and expose "
                        "or change it through {model}; create the {model} with its own content "
                        "instead")
CONTEXT_ALLOWED = ("lang, tz, active_test, allowed_company_ids, active_model, active_id, "
                   "active_ids, bin_size, read_group_expand, mail_create_nosubscribe, "
                   "button_validate_picking_ids, skip_backorder, picking_ids_not_to_backorder, "
                   "skip_immediate, mo_ids_to_backorder, warehouse, location, validate_analytic, "
                   "default_<field> with a plain value or a link-only list")
CONTEXT_HINT = "context key {key} is not allowed through these tools (allowed: {allowed})"
CALL_LIST_HINT = "method '{method}' is not among the methods allowed on '{model}' ({list})"
FILE_HINT = "the policy file rule '{key}' refuses it"
INVALID_MODEL_HINT = ("the model name is not a valid Odoo model name (lowercase letters, digits, "
                      "'_' and '.', e.g. res.partner)")
INVALID_METHOD_HINT = ("the method name is not a public method name (a letter first, then "
                       "letters, digits and '_'; Odoo refuses private methods over RPC)")
INVALID_NAME_HINT = ("the model or method name is not valid (models: lowercase letters, digits, "
                     "'_' and '.'; methods: public names, a letter first)")
SHAPE_HINT = ("the arguments of this {method} call cannot be checked ({detail}); use the "
              "dedicated tool (odoo_create, odoo_write, odoo_search_read) or pass the arguments "
              "by name")
SHAPE_TOOL_HINT = "the arguments of this {tool} call cannot be checked ({detail}); correct them"

_PLAIN_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


def plain_name(value: Any) -> str:
    """``'name'`` for a plain identifier the agent sent (a context key), else a description."""
    if isinstance(value, str) and _PLAIN_NAME.fullmatch(value):
        return f"'{value}'"
    return "of that name"


def _one_line(text: str) -> str:
    """A configured value (the policy file path) on one printable line."""
    return "".join(ch if ch.isprintable() else "?" for ch in text)


def _denied(message: str, hint: str, *, rule: str, layer: str, touches: Iterable[Any] = (),
            workaround: bool = True) -> PolicyDenied:
    remediation = f"{hint}; {NO_WORKAROUND}" if workaround else hint
    return PolicyDenied(message, remediation=remediation, touches=tuple(str(t) for t in touches),
                        rule=rule, layer=layer)


# --- tool level ------------------------------------------------------------------

def hidden(tool: str, profile: str, op: str) -> PolicyDenied:
    return PolicyDenied(HIDDEN.format(tool=tool, profile=profile, op=op), remediation=HIDDEN_REMEDY,
                        rule=f"profile:{profile}", layer="tool")


def disabled(tool: str, path: str | None) -> PolicyDenied:
    return PolicyDenied(DISABLED.format(tool=tool, path=_one_line(path or "?")),
                        remediation=DISABLED_REMEDY, rule="tool-disabled", layer="tool")


def unmapped(tool: str) -> PolicyEnvelopeError:
    return PolicyEnvelopeError(UNMAPPED.format(tool=tool), rule="unmapped", layer="tool")


def read_only_tool(tool: str) -> PolicyDenied:
    return PolicyDenied(READ_ONLY_TOOL.format(tool=tool), remediation=READ_ONLY_REMEDY,
                        rule="readonly", layer="tool")


def envelope(tool: str, model: str, method: str) -> PolicyEnvelopeError:
    return PolicyEnvelopeError(ENVELOPE.format(tool=tool, model=model, method=method),
                               rule="envelope", layer="B")


def guard_failure(tool: str, kind: str) -> PolicyEnvelopeError:
    """The guarded session failed while checking a call: refused, never sent. ``kind``
    is an exception class name, never its message (which could echo a value)."""
    return PolicyEnvelopeError(GUARD_FAILURE.format(tool=tool, kind=kind), rule="guard",
                               layer="B")


def withheld_section(exc: Any) -> str:
    """What ``odoo_online_profile`` reports for a section the policy refused."""
    touches = getattr(exc, "touches", ()) or ()
    parts = str(touches[0]).split(":") if touches else []
    if len(parts) >= 2 and valid_model(parts[1]):
        return WITHHELD_SECTION.format(op=parts[0], model=parts[1])
    return WITHHELD_SECTION_RULE.format(rule=getattr(exc, "rule", "") or "policy")


# --- refused checks --------------------------------------------------------------

def rule_text(decision: Decision) -> str:
    """The rule as a refusal shows it, with the alias or delegation it came through."""
    text, model = decision.rule, decision.touch.model
    if decision.relation == "alias":
        text += f", alias of {model}"
    elif decision.relation == "delegation":
        text += f", through {decision.via}, which {model} delegates to"
    return text


def hint(policy: Policy, decision: Decision) -> str:
    """The remedy of a ``decide()`` refusal, by its rule."""
    rule, touch = decision.rule, decision.touch
    profile = policy.profile_name
    if rule.startswith("never:"):
        return NEVER_HINT
    if rule.startswith("tier:"):
        return TIER_HINTS[rule[len("tier:"):]]
    if rule == "outbound-method":
        return OUTBOUND_HINT.format(method=touch.method, profile=profile, model=touch.model)
    if rule.startswith("file:"):
        if decision.methods is not None:
            return CALL_LIST_HINT.format(method=touch.method, model=touch.model,
                                         list=", ".join(decision.methods))
        return FILE_HINT.format(key=rule[len("file:"):])
    if rule == "readonly":
        return READONLY_HINT
    if rule.startswith("profile:"):
        if profile == "readonly":
            return READONLY_PROFILE_HINT
        if touch.op == "unlink":
            return UNLINK_HINT.format(profile=profile)
        if touch.op == "schema":
            return SCHEMA_HINT.format(profile=profile)
        return PROFILE_HINT.format(profile=profile, op=touch.op)
    if rule == "invalid-name":  # invalid_name() says which name, when the caller knows
        return INVALID_NAME_HINT
    return FILE_HINT.format(key=rule)  # pragma: no cover - every rule above has its hint


def refused(policy: Policy, decision: Decision, *, layer: str = "A") -> PolicyDenied:
    """The refusal of a ``decide()`` decision."""
    touch = decision.touch
    values = {"op": touch.op, "model": touch.model, "profile": policy.profile_name,
              "rule": rule_text(decision), "suffix": SUFFIXES[layer]}
    template = REFUSED if touch.model is not None else REFUSED_UNNAMED
    return _denied(template.format(**values), hint(policy, decision), rule=decision.rule,
                   layer=layer, touches=(touch,))


def invalid_name(policy: Policy, op: str, model: Any, *, layer: str = "A") -> PolicyDenied:
    """A model or method name that fails its check: described, never echoed."""
    values = {"op": op, "profile": policy.profile_name, "rule": "invalid-name",
              "suffix": SUFFIXES[layer]}
    if valid_model(model):
        return _denied(REFUSED.format(model=model, **values), INVALID_METHOD_HINT,
                       rule="invalid-name", layer=layer)
    return _denied(REFUSED_UNNAMED.format(**values), INVALID_MODEL_HINT, rule="invalid-name",
                   layer=layer)


def _check(policy: Policy, op: str, model: str, rule: str, hint_text: str, *, layer: str,
           workaround: bool = True) -> PolicyDenied:
    message = REFUSED.format(op=op, model=model, profile=policy.profile_name, rule=rule,
                             suffix=SUFFIXES[layer])
    return _denied(message, hint_text, rule=rule, layer=layer, workaround=workaround)


def field(policy: Policy, op: str, model: str, name: str, *, by_file: bool = False,
          layer: str = "A") -> PolicyDenied:
    """A withheld field (``name`` is a field, or a path of fields, of ``model``)."""
    template = FIELD_FILE_HINT if by_file else FIELD_HINT
    return _check(policy, op, model, "field", template.format(field=name, model=model),
                  layer=layer)


def relational(policy: Policy, *, method: str, model: str, op: str, comodel: str, field: str,
               command: int, rule: str, layer: str = "B") -> PolicyDenied:
    return _check(policy, op, comodel, "relational", RELATIONAL_HINT.format(
        method=method, model=model, op=op, comodel=comodel, field=field, n=command, rule=rule),
        layer=layer)


def path(policy: Policy, *, method: str, model: str, op: str, comodel: str, field_path: str,
         rule: str, layer: str = "B") -> PolicyDenied:
    """A field path of ``model`` that reaches ``comodel``, which the policy refuses."""
    return _check(policy, op, comodel, "relational", PATH_HINT.format(
        method=method, model=model, op=op, comodel=comodel, path=field_path, rule=rule),
        layer=layer)


def unverified(policy: Policy, op: str, model: str, *, layer: str = "B") -> PolicyDenied:
    """The field metadata the checks need could not be read: refused, never sent."""
    return _check(policy, op, model, "unverified", UNVERIFIED_HINT, layer=layer)


def attachment_create(policy: Policy, op: str, *, layer: str = "B") -> PolicyDenied:
    """An ir.attachment created or written as public, or as a field of a record."""
    return _check(policy, op, "ir.attachment", "attachment-field", ATTACHMENT_CREATE_HINT,
                  layer=layer)


def identity_import(policy: Policy, model: str, *, layer: str = "B") -> PolicyDenied:
    """An import that would update existing contacts' e-mails."""
    return _check(policy, "write", model, "identity", IDENTITY_IMPORT_HINT, layer=layer)


def attachment_pin(policy: Policy, *, layer: str = "A") -> PolicyDenied:
    return _check(policy, "read", "ir.attachment", "attachment-pin", ATTACHMENT_PIN_HINT,
                  layer=layer)


def attachment_field(policy: Policy, op: str, attachment_id: int, *, layer: str = "B"
                     ) -> PolicyDenied:
    return _check(policy, op, "ir.attachment", "attachment-field",
                  ATTACHMENT_FIELD_HINT.format(id=int(attachment_id), op=op), layer=layer)


def identity(policy: Policy, partner_id: int, *, layer: str = "B") -> PolicyDenied:
    return _check(policy, "write", "res.partner", "identity",
                  IDENTITY_HINT.format(id=int(partner_id)), layer=layer)


def delegation_link(policy: Policy, op: str, model: str, field: str, parent: str, *,
                    layer: str = "B") -> PolicyDenied:
    return _check(policy, op, model, "delegation-link",
                  DELEGATION_LINK_HINT.format(field=field, model=model, parent=parent),
                  layer=layer)


def context(policy: Policy, op: str, model: str, key: Any, *, layer: str = "A") -> PolicyDenied:
    return _check(policy, op, model, "context",
                  CONTEXT_HINT.format(key=plain_name(key), allowed=CONTEXT_ALLOWED), layer=layer)


def shape(policy: Policy, op: str, model: str, *, detail: str, method: str | None = None,
          tool: str | None = None, layer: str = "A") -> PolicyDenied:
    """Arguments the policy cannot read with certainty. Through odoo_execute the hint
    sends the agent to the dedicated tools, which the same policy governs."""
    if method is not None:
        return _check(policy, op, model, "shape", SHAPE_HINT.format(method=method, detail=detail),
                      layer=layer, workaround=False)
    return _check(policy, op, model, "shape", SHAPE_TOOL_HINT.format(tool=tool, detail=detail),
                  layer=layer)


# --- warnings odoo_version adds at runtime (the loader's are W1 to W7) -------------
ADMIN_WARNING = ("the Odoo user of this connection is an administrator (base.group_system): "
                 "Odoo's access rights narrow nothing, so this policy is the only narrowing "
                 "layer. Prefer a dedicated user with the fewest groups that work.")
RUNTIME_WARNINGS = {"W10": ADMIN_WARNING}


# --- what the agent is told before it calls ---------------------------------------

INSTRUCTIONS_LIMIT = 400
FINAL = ("A refusal that names the permission policy is final: tell the user, who can change it "
         "in the plugin options; never try another tool or the shell to get the same result.")
LOCKED_HEAD = "Permission policy for this connection: locked, because it could not be loaded ("
LOCKED_TAIL = ("). Only odoo_version works: tell the user, who can fix the policy file or the "
               "plugin options and reconnect the server; never try another tool or the shell "
               "to get the same result.")


def instructions_line(policy: Policy, tools: Iterable[Any]) -> str:
    """The line ``initialize`` appends to the server instructions (under 400 characters)."""
    if policy.locked:
        error = policy.error or ""
        room = INSTRUCTIONS_LIMIT - 1 - len(LOCKED_HEAD) - len(LOCKED_TAIL)
        if len(error) > room:
            error = error[: room - 3] + "..."
        return LOCKED_HEAD + error + LOCKED_TAIL
    source = " plus a policy file" if policy.source else ""
    line = (f"Permission policy for this connection: profile '{policy.profile_name}'{source} "
            f"({policy.digest}).")
    if policy.readonly:
        line += " Read-only mode is on."
    hidden_tools = [tool.name for tool in tools if not policy.tool_visible(tool)]
    if hidden_tools:
        listed = f" Not listed because the policy forbids them: {', '.join(hidden_tools)}."
        if len(line) + len(listed) + 1 + len(FINAL) >= INSTRUCTIONS_LIMIT:
            listed = (f" Not listed because the policy forbids them: {len(hidden_tools)} tools "
                      "(odoo_version names them).")
        line += listed
    return f"{line} {FINAL}"


DESCRIPTION_LIMIT = 120
DESCRIPTION_SUFFIXES = {
    "readonly": " [Policy 'readonly': reads only, no secrets. See odoo_version.]",
    "standard": (" [Policy 'standard': no deletes or secrets; users, rights, mail-out and "
                 "customization read-only. See odoo_version.]"),
    "builder": (" [Policy 'builder': no business deletes or secrets; users, rights and mail-out "
                "read-only. See odoo_version.]"),
}


def description_suffix(policy: Policy) -> str:
    """Appended to the description of every tool that takes a model, outside ``full``."""
    if policy.locked:
        return ""
    return DESCRIPTION_SUFFIXES.get(policy.profile_name, "")
