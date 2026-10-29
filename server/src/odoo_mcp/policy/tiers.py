# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The policy's data: operations, sensitive tiers, NEVER, delegation, fields.

This is DATA, like ``compat/deltas.py``. A change here changes what every
profile except ``full`` allows, so it also bumps ``TIERS_VERSION``, which feeds
the policy digest: the startup log, the audit start line and ``odoo_version``
then show that the effective policy changed.

Conventions:
  * A model pattern is an exact name (``res.users``) or ``prefix.*``, which
    matches the names under that prefix (``res.users.apikeys``) but not the
    prefix itself.
  * Names that do not exist on a given Odoo version never match, so one list
    holds the names of every series. Entries marked "best-effort" are named in
    ``BEST_EFFORT`` and confirmed against live databases before they are relied
    on (the live run reads ``ir.model`` on each series).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TIERS_VERSION = "2026-10-29.1"

OPERATIONS = ("read", "create", "write", "unlink", "call", "schema")
WRITE_OPERATIONS = frozenset(OPERATIONS) - {"read"}
# Field metadata and access checks about one model. Never granted by a rule:
# it is allowed wherever any operation is allowed on the model.
INSPECT = "inspect"
PSEUDO = (INSPECT,)


def pattern_matches(pattern: str, model: str) -> bool:
    """``prefix.*`` matches the names under ``prefix``; anything else is exact."""
    if pattern.endswith(".*"):
        return model.startswith(pattern[:-1])
    return model == pattern


@dataclass(frozen=True)
class Tier:
    name: str
    models: tuple[str, ...]  # exact names or "prefix.*"
    reason: str
    exceptions: frozenset[str] = frozenset()

    def matches(self, model: str) -> bool:
        if model in self.exceptions:
            return False
        return any(pattern_matches(pattern, model) for pattern in self.models)


# In severity order: a refusal names the first tier that withholds the operation.
TIERS: tuple[Tier, ...] = (
    Tier(
        "secrets",
        (
            "ir.config_parameter",  # database.secret signs reset, signup and portal tokens
            "res.config",
            "res.config.*",  # res.config.settings: integration keys in related fields
            "ir.mail_server",
            "fetchmail.server",
            "payment.provider",  # 16+
            "payment.acquirer",  # up to 15
            "payment.token",
            "iap.account",
            "res.users.apikeys.show",  # the one-time view of a new API key
            "res.company.ldap",
            "auth_totp.device",  # best-effort
            "l10n_mx_edi.certificate",  # best-effort: the SAT CSD certificate and key
            "certificate.certificate",  # 17.x/18+, best-effort
            "certificate.key",  # 17.x/18+, best-effort
            "account.online.link",  # EE, best-effort: bank-sync tokens
            "account.online.account",  # EE, best-effort
            "mail.mail",  # the outgoing queue: reset and signup links
        ),
        "They hold credentials, or values that act as credentials (system parameters, "
        "mail-server and LDAP passwords, payment-provider keys and tokens, IAP tokens, a "
        "new API key, bank-sync tokens, CFDI certificates and keys, queued reset e-mails). "
        "Reading them is already the damage.",
    ),
    Tier(
        "security",
        (
            "res.users",
            "res.users.*",
            "res.groups",
            "res.groups.*",
            "ir.model.access",
            "ir.rule",
            "ir.module.module",
            "base.module.*",
            "change.password.*",
            "portal.wizard",
            "portal.wizard.*",
            "auth_totp.wizard",
            "auth.oauth.provider",
            "res.partner.bank",  # changing a vendor's account number is payment diversion
            "base.partner.merge.automatic.wizard",
            "mail.message",  # chatter and tracking are the audit history
            "mail.tracking.value",
            "ir.sequence",  # fiscal numbering (CFDI folios)
            "ir.sequence.date_range",
        ),
        "Identity and rights, login redirection, bank accounts, partner merges, chatter "
        "history and fiscal sequences: reads stay open, changes need profile 'full' or an "
        "entry naming the model exactly.",
    ),
    Tier(
        "outbound",
        (
            "mail.compose.message",
            "mail.followers",  # an external follower receives every future message
            "mail.template",  # rendered with record access, sent from the company address
            "sms.sms",
            "sms.composer",
            "sms.template",
            "portal.share",
            "mailing.*",  # best-effort
            "snailmail.letter",
            "account.move.send",
            "account.move.send.*",  # 17+, best-effort
            "account.invoice.send",  # up to 16
            "mail.mail",  # also secrets
        ),
        "They send e-mail, SMS, letters or share links, or decide what is sent.",
    ),
    Tier(
        "customization",
        ("ir.*", "base.automation", "base.action.rule", "studio.*",
         # Bulk engines reachable as plain models through odoo_execute: the import
         # engine upserts into ANY model (its res_model is just a value), and the
         # language wizards install a language or import translations. The import
         # tools reach base_import.import through registry.Internal predicates, which
         # the tiers do not gate (decide_internal), so these entries only close the
         # generic door, not odoo_import / odoo_import_preview.
         "base_import.import", "base.language.install", "base.language.import"),
        "Server actions, automations, crons, views, assets, manual fields, defaults and "
        "other ir.* records run code or change how Odoo behaves later, and the bulk import "
        "and language engines upsert or install across models; they need profile 'builder'.",
        exceptions=frozenset({"ir.attachment"}),  # a pointer model, pinned to its parent
    ),
)

TIER_NAMES = tuple(tier.name for tier in TIERS)

BEST_EFFORT = frozenset({
    "auth_totp.device", "l10n_mx_edi.certificate", "certificate.certificate",
    "certificate.key", "account.online.link", "account.online.account", "mailing.*",
    "account.move.send.*", "website.controller.page", "product.document",
    "documents.document",
})


@dataclass(frozen=True)
class Never:
    """An operation no profile and no rule can allow, ``full`` included."""

    id: str
    model: str
    ops: frozenset[str]
    reason: str
    methods: frozenset[str] | None = None  # for "call": only these methods


NEVER: tuple[Never, ...] = (
    Never("api-keys", "res.users.apikeys", frozenset({"create", "write", "unlink", "call"}),
          "odoo-tools never creates, changes or revokes API keys"),
    Never("api-keys", "res.users.apikeys.description", frozenset(OPERATIONS),
          "the API-key creation wizard"),
    Never("module-uninstall", "ir.module.module", frozenset({"call"}),
          "uninstalling a module deletes its data",
          methods=frozenset({"button_uninstall", "button_immediate_uninstall",
                             "module_uninstall"})),
    Never("module-uninstall", "base.module.uninstall", frozenset(OPERATIONS),
          "the uninstall wizard"),
)

# Delegation (_inherits): child -> (parent, link field). Writing the child writes
# the parent's fields (website.page "arch" is the QWeb of an ir.ui.view), so
# every operation except "read" on the child also needs it on the parent.
DELEGATES: dict[str, tuple[str, str]] = {
    "website.page": ("ir.ui.view", "view_id"),
    "website.controller.page": ("ir.ui.view", "view_id"),  # 17+, best-effort
    "ir.cron": ("ir.actions.server", "ir_actions_server_id"),
    "base.automation": ("ir.actions.server", "action_server_id"),  # 11-16
    "product.document": ("ir.attachment", "ir_attachment_id"),  # 17+, best-effort
    "documents.document": ("ir.attachment", "attachment_id"),  # EE, up to 17, best-effort
}

# The ir.attachment fields the create/write rules (4.5) treat as structural, and the one
# place they are named: public and res_field are refused outright (a public attachment is
# downloadable without a login; res_field marks a field attachment), and res_model must
# point at a parent the agent may write. A plain default_<field> naming one of these,
# except default_res_model and default_res_id, is refused by construction (policy/check.py),
# because Odoo applies a context default to the nested attachment a call creates, which no
# check against the call's top model can follow. res_model and res_id stay allowed, since
# activity and composer flows pass default_res_model / default_res_id; a nested attachment
# bound through them during a call is an accepted, documented limit (docs/policy.md).
ATTACHMENT_STRUCTURAL_FIELDS = frozenset({"public", "res_field", "res_model"})

# many2many links to a write-withheld (tier) model that only REFERENCE it: adding or
# removing one changes no field of the target and grants no right, so it counts as a
# read of the target, not a write. Assigning a user to a task or a helpdesk team is the
# task's or team's own relation (design 6.6). Every other m2m to a write-withheld model
# stays a write, so a privilege link -- a user's groups (res.users.groups_id, m2m to the
# security-tier res.groups) or a company's users (res.company.user_ids, the inverse of a
# user's allowed companies) -- is still refused outside 'full'. Keyed by (owner model,
# field): the owner, not the comodel, tells an assignment from a privilege.
REFERENCE_LINKS: frozenset[tuple[str, str]] = frozenset({
    ("project.task", "user_ids"),      # task assignees (16+)
    ("helpdesk.team", "member_ids"),   # helpdesk team members (EE)
})

# Names the policy treats as one model besides the renames and merges of
# compat/deltas.py (MODEL_RENAMES): Odoo 10's automated actions.
POLICY_ALIASES: dict[str, frozenset[str]] = {
    "base.automation": frozenset({"base.action.rule"}),
    "base.action.rule": frozenset({"base.automation"}),
}

# Business methods that send data out: refused outside "full" unless an entry
# naming the model exactly lists the method (internal notes excepted, 4.7).
OUTBOUND_METHODS = frozenset({
    "message_post", "message_notify", "message_subscribe", "message_post_with_template",
    "message_post_with_view", "message_post_with_source", "message_mail_with_source",
    "send_mail", "action_send_mail", "action_send_and_print", "send_and_print_action",
})
NOTE_SUBTYPE = "mail.mt_note"

# Credential-like field names, withheld in every profile except "full": refused
# in arguments (field lists, values, paths, groupby, order) and removed from
# results. Matched on the lowercased name.
WITHHELD_FIELD_PATTERN = re.compile(
    r"(^|_)(password|passwd|pass|pwd|secret|token|apikey|api_key|private_key|privkey|"
    r"credentials?)($|_)")
WITHHELD_FIELD_NAMES = frozenset({"signup_url", "smtp_pass", "totp_secret"})  # named for the docs
NOT_WITHHELD = frozenset({"payment_token_id", "payment_token_ids", "token_count"})
# Names that carry a credential word but denote a RELATION to, or a COUNT of, token
# records rather than a token VALUE: a link to payment.token (token_id, token_ids,
# suitable_payment_token_ids) or a count of them (token_count, payment_token_count).
# payment.token itself is secrets-tier, so its values stay sealed; these fields only
# reference it, so withholding them would hide harmless links without protecting a
# secret. Matched on the lowercased name; a value field such as access_token or
# refresh_token (no _id/_ids/_count suffix) is unaffected and stays withheld.
NOT_WITHHELD_PATTERN = re.compile(r"(^|_)(token_id|token_ids|token_count)$")
# Integrations often hard-code tokens in automation code: withheld, except under
# profile "builder", which writes that code.
WITHHELD_MODEL_FIELDS = frozenset({
    ("ir.actions.server", "code"), ("ir.cron", "code"), ("base.automation", "code"),
    ("ir.actions.server", "webhook_url"), ("base.automation", "webhook_uuid"),
})

# Context keys a call may carry, besides default_<field> with a plain value (a list or an
# object in a default_<field> is refused: policy/check.py check_context).
# The keys that silence chatter tracking (tracking_disable, mail_notrack,
# mail_create_nolog) are absent on purpose: tracking is evidence. The stock and
# manufacturing validation wizards (stock.picking.button_validate ->
# stock.backorder.confirmation / stock.immediate.transfer,
# mrp.production.button_mark_done) only validate the records their context names, so
# their keys are allowed; none suppress tracking (design section 10). warehouse and
# location drive the read-only qty_available computation.
SAFE_CONTEXT_KEYS = frozenset({
    "lang", "tz", "active_test", "allowed_company_ids", "active_model", "active_id",
    "active_ids", "bin_size", "read_group_expand", "mail_create_nosubscribe",
    # uid: the Odoo web client puts the signed-in user's id in every call's context. It
    # is informational -- the acting user is the authenticated session, not context['uid']
    # -- and suppresses no chatter tracking, so a replayed web-client context (which
    # carries it) runs. action_post / action_confirm with the real web context were
    # refused on this key alone before it was added (design section 10).
    "uid",
    # stock / mrp validation wizards (design finding): they validate only the records
    # the context names; without the key the wizard returns True and changes nothing.
    "button_validate_picking_ids", "skip_backorder", "picking_ids_not_to_backorder",
    "skip_immediate", "mo_ids_to_backorder",
    # stock on hand per warehouse / location (qty_available is computed from them).
    "warehouse", "location",
    # account.move._post reads this on the invoice Confirm/Post button (16+) to force
    # analytic-distribution validation; action_post is a business verb kept under
    # standard, and the key suppresses no chatter tracking (the flagship CFDI flow).
    "validate_analytic",
})
