# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The permission policy's decision: precedence, profiles, tiers, aliases, delegation.

The policy core is pure (no session, no Odoo), so every case here is a direct
``Policy.decide`` call. The tool table at the end mirrors the permission mapping
the server will declare for its 28 tools, to check what ``tools/list`` hides.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from typing import Any

import pytest

from odoo_mcp.errors import CompatError, PolicyDenied, PolicyError
from odoo_mcp.policy.loader import load_bytes
from odoo_mcp.policy.model import (
    PROFILES,
    TIER_WITHHELD,
    Policy,
    Rule,
    Touch,
    model_aliases,
    parse_explain,
)
from odoo_mcp.policy.tiers import (
    DELEGATES,
    NEVER,
    OPERATIONS,
    TIER_NAMES,
    TIERS,
    WRITE_OPERATIONS,
)
from odoo_mcp.registry import registry
from odoo_mcp.tools import crud  # noqa: F401  (registers the tools)

TODAY = datetime.date(2026, 10, 21)
REASON = "Ticket 4312: reviewed by the owner"


def policy(profile: str = "standard", models: dict[str, Any] | None = None, *,
           readonly: bool = False, today: datetime.date = TODAY, locked: bool = False,
           **document: Any) -> Policy:
    """The policy of a file holding ``models`` (and ``fields``, ``tools``)."""
    body: dict[str, Any] = {"version": 1, **document}
    if models is not None:
        body["models"] = models
    loaded = load_bytes(json.dumps(body).encode("utf-8"), path="/etc/odoo-tools/policy.json",
                        profile=profile, readonly=readonly,
                        tool_names=[t.name for t in registry.all()], today=today)
    assert loaded.locked is locked, loaded.error
    return loaded


def decided(p: Policy, op: str, model: str, method: str | None = None,
            args: dict[str, Any] | None = None) -> tuple[bool, str]:
    d = p.decide(op, model, method, args)
    return d.allowed, d.rule


# --- precedence, one case per step -------------------------------------------

@pytest.mark.parametrize("model", ["Res.Partner", "res partner", "res.partner\n", "",
                                   "a" * 129, "res/partner", None, 7])
def test_step_1_invalid_model_names_are_refused(model: Any) -> None:
    d = Policy(profile_name="full").decide("read", model)
    assert (d.allowed, d.rule) == (False, "invalid-name")
    assert d.touch.model is None  # an invalid name is never kept for a message


@pytest.mark.parametrize("method", ["_private", "__init__", "1abc", "a-b", "a b", "x" * 129,
                                    "message_post\n"])
def test_step_1_invalid_method_names_are_refused(method: str) -> None:
    assert decided(Policy(profile_name="full"), "call", "res.partner", method) == (
        False, "invalid-name")


def test_step_2_never_beats_full_and_an_exact_rule() -> None:
    # The loader refuses these grants (E18); built by hand, decide() still refuses.
    grants = Policy(profile_name="full", rules=(
        Rule("res.users.apikeys", (("create", True), ("write", True), ("unlink", True),
                                   ("call", True)), reason=REASON),
        Rule("res.users.apikeys.description", tuple((op, True) for op in OPERATIONS),
             reason=REASON),
        Rule("ir.module.module", (("call", frozenset({"button_immediate_uninstall"})),),
             reason=REASON),
    ))
    for op in ("create", "write", "unlink", "call"):
        assert decided(grants, op, "res.users.apikeys", "action_x" if op == "call" else None) == (
            False, "never:api-keys")
    for op in OPERATIONS:
        assert decided(grants, op, "res.users.apikeys.description") == (False, "never:api-keys")
    for method in ("button_uninstall", "button_immediate_uninstall", "module_uninstall"):
        assert decided(grants, "call", "ir.module.module", method) == (
            False, "never:module-uninstall")
    for op in OPERATIONS:
        assert decided(grants, op, "base.module.uninstall") == (False, "never:module-uninstall")
    # what NEVER does not name stays open under full
    assert decided(Policy(profile_name="full"), "call", "ir.module.module",
                   "button_immediate_install") == (True, "profile:full")
    assert decided(grants, "read", "res.users.apikeys") == (True, "profile:full")


def test_step_3_readonly_beats_every_profile_and_rule() -> None:
    p = policy("full", {"res.partner": {"write": True, "unlink": True, "call": True}},
               readonly=True)
    for op in WRITE_OPERATIONS:
        assert decided(p, op, "res.partner", "action_x" if op == "call" else None) == (
            False, "readonly")
    assert decided(p, "read", "res.partner") == (True, "profile:full")
    assert p.decide("inspect", "res.partner").allowed


def test_step_4_a_locked_policy_refuses_everything_after_the_name_never_and_readonly_steps(
) -> None:
    locked = policy("standard", {"res.partner": {"read": "yes"}}, locked=True)
    assert locked.locked and locked.error_code == "E11"
    assert decided(locked, "read", "res.partner") == (False, "locked")
    assert decided(locked, "inspect", "res.partner") == (False, "locked")
    assert decided(locked, "read", "Bad Name") == (False, "invalid-name")
    assert decided(locked, "create", "res.users.apikeys") == (False, "never:api-keys")
    assert locked.ops_for("res.partner") == frozenset()


def test_step_5_a_disabled_tool_is_hidden_but_decisions_do_not_change() -> None:
    p = policy("standard", tools={"disabled": ["odoo_import"]})
    assert not p.tool_visible(TOOL["odoo_import"])
    assert p.tool_visible(TOOL["odoo_import_preview"])
    assert decided(p, "create", "res.partner") == (True, "profile:standard")


def test_step_6_an_exact_rule_decides_and_opens_tiers() -> None:
    p = policy("standard", {
        "res.partner": {"write": False},
        "res.users": {"write": True, "reason": REASON},
        "ir.config_parameter": {"read": True, "reason": REASON},
    })
    assert decided(p, "write", "res.partner") == (False, "file:res.partner")
    assert decided(p, "write", "res.users") == (True, "file:res.users")
    assert decided(p, "create", "res.users") == (False, "tier:security")  # only what it names
    assert decided(p, "read", "ir.config_parameter") == (True, "file:ir.config_parameter")


def test_step_6_call_true_opens_a_tier_but_not_the_outbound_methods() -> None:
    p = policy("standard", {"res.users": {"call": True, "reason": REASON},
                            "res.partner": {"call": True}})
    assert decided(p, "call", "res.users", "action_reset_password") == (True, "file:res.users")
    assert decided(p, "call", "res.users", "message_post") == (False, "outbound-method")
    assert decided(p, "call", "res.partner", "message_subscribe") == (False, "outbound-method")


def test_step_6_a_call_list_decides_by_membership_and_opens_what_it_lists() -> None:
    p = policy("standard", {
        "sale.order": {"call": ["action_confirm", "action_cancel"]},
        "res.partner": {"call": ["message_post"], "reason": "Agents reply from the chatter"},
        "res.users": {"call": ["action_reset_password"], "reason": REASON},
    })
    assert decided(p, "call", "sale.order", "action_confirm") == (True, "file:sale.order")
    refused = p.decide("call", "sale.order", "action_done")
    assert (refused.allowed, refused.rule) == (False, "file:sale.order")
    assert refused.methods == ("action_cancel", "action_confirm")
    assert decided(p, "call", "res.partner", "message_post") == (True, "file:res.partner")
    assert decided(p, "call", "res.users", "action_reset_password") == (True, "file:res.users")
    assert decided(p, "call", "res.users", "write_x") == (False, "file:res.users")


@pytest.mark.parametrize(("op", "model", "tier"), [
    ("read", "ir.config_parameter", "secrets"),
    ("read", "res.config.settings", "secrets"),
    ("read", "payment.provider", "secrets"),
    ("read", "mail.mail", "secrets"),
    ("read", "certificate.key", "secrets"),
    ("write", "res.users", "security"),
    ("write", "res.partner.bank", "security"),
    ("unlink", "mail.message", "security"),
    ("write", "ir.sequence", "security"),
    ("call", "ir.module.module", "security"),
    ("create", "mail.followers", "outbound"),
    ("write", "mail.template", "outbound"),
    ("create", "account.move.send.wizard", "outbound"),
    ("write", "ir.property", "customization"),
    ("create", "ir.actions.server", "customization"),
    ("write", "studio.approval.rule", "customization"),
])
def test_step_7_tiers_refuse_and_the_first_tier_in_severity_order_is_named(
        op: str, model: str, tier: str) -> None:
    d = Policy().decide(op, model, "action_x" if op == "call" else None)
    assert (d.allowed, d.rule, d.tier) == (False, f"tier:{tier}", tier)


def test_step_8_outbound_methods_are_refused_outside_full() -> None:
    for profile in ("standard", "builder"):
        p = Policy(profile_name=profile)
        assert decided(p, "call", "res.partner", "message_post") == (False, "outbound-method")
        assert decided(p, "call", "crm.lead", "message_subscribe") == (False, "outbound-method")
        assert decided(p, "call", "account.move", "action_send_and_print") == (
            False, "outbound-method")
    assert decided(Policy(profile_name="full"), "call", "res.partner", "message_post") == (
        True, "profile:full")


def test_step_9_the_most_specific_pattern_decides_and_never_opens_a_tier() -> None:
    p = policy("standard", {
        "*": {"write": False, "call": ["action_confirm"]},
        "sale.*": {"write": True},
        "sale.order.*": {"write": False},
        "res.*": {"write": True, "call": True},
    })
    assert decided(p, "write", "sale.order") == (True, "file:sale.*")
    assert decided(p, "write", "sale.order.line") == (False, "file:sale.order.*")
    assert decided(p, "write", "crm.lead") == (False, "file:*")
    assert decided(p, "write", "res.users") == (False, "tier:security")
    assert decided(p, "call", "crm.lead", "action_confirm") == (True, "file:*")
    refused = p.decide("call", "crm.lead", "action_set_won")
    assert (refused.allowed, refused.rule, refused.methods) == (
        False, "file:*", ("action_confirm",))
    assert decided(p, "call", "res.partner", "message_post") == (False, "outbound-method")


def test_step_10_the_profile_decides_last() -> None:
    assert decided(Policy(), "unlink", "res.partner") == (False, "profile:standard")
    assert decided(Policy(), "call", "sale.order", "action_confirm") == (True, "profile:standard")
    assert decided(Policy(profile_name="builder"), "unlink", "ir.ui.view") == (
        True, "profile:builder")


def test_unknown_operations_are_a_programming_error() -> None:
    with pytest.raises(ValueError, match="unknown operation"):
        Policy().decide("delete", "res.partner")


# --- profiles x tiers x operations (the table of design 4.8) --------------------

SAMPLE = {
    "business": "res.partner",
    "secrets": "ir.config_parameter",
    "security": "res.users",
    "outbound": "mail.template",
    "customization": "ir.ui.view",
}
ALL = set(OPERATIONS)
EXPECTED = {
    "readonly": {"business": {"read"}, "secrets": set(), "security": {"read"},
                 "outbound": {"read"}, "customization": {"read"}},
    "standard": {"business": {"read", "create", "write", "call"}, "secrets": set(),
                 "security": {"read"}, "outbound": {"read"}, "customization": {"read"}},
    "builder": {"business": {"read", "create", "write", "call", "schema"}, "secrets": set(),
                "security": {"read"}, "outbound": {"read"}, "customization": ALL},
    "full": {name: ALL for name in SAMPLE},
}


@pytest.mark.parametrize("profile", list(PROFILES))
@pytest.mark.parametrize("kind", list(SAMPLE))
def test_every_profile_tier_and_operation_cell(profile: str, kind: str) -> None:
    p = Policy(profile_name=profile)
    allowed = {op for op in OPERATIONS
               if p.decide(op, SAMPLE[kind], "action_x" if op == "call" else None).allowed}
    assert allowed == EXPECTED[profile][kind]
    assert p.ops_for(SAMPLE[kind]) == frozenset(EXPECTED[profile][kind])
    assert p.decide("inspect", SAMPLE[kind]).allowed is bool(EXPECTED[profile][kind])


@pytest.mark.parametrize("profile", list(PROFILES))
def test_outbound_methods_and_internal_notes_per_profile(profile: str) -> None:
    p = Policy(profile_name=profile)
    note = {"ids": [7], "args": [], "kwargs": {"subtype_xmlid": "mail.mt_note", "body": "x"}}
    mail = {"ids": [7], "args": [], "kwargs": {"body": "x", "partner_ids": [3]}}
    expected_mail = profile == "full"
    expected_note = profile in ("standard", "builder", "full")
    assert p.decide("call", "res.partner", "message_post", mail).allowed is expected_mail
    assert p.decide("call", "res.partner", "message_post", note).allowed is expected_note


def test_the_tier_table_withholds_what_design_4_2_says() -> None:
    assert TIER_NAMES == ("secrets", "security", "outbound", "customization")
    assert TIER_WITHHELD["secrets"] == frozenset(OPERATIONS)
    for tier in ("security", "outbound", "customization"):
        assert TIER_WITHHELD[tier] == WRITE_OPERATIONS
    by_name = {tier.name: tier for tier in TIERS}
    assert not by_name["customization"].matches("ir.attachment")  # a pointer model
    assert by_name["customization"].matches("ir.ui.view")
    assert by_name["secrets"].matches("res.config.settings")
    assert by_name["secrets"].matches("res.config")
    assert not by_name["secrets"].matches("res.configx")  # a prefix ends at a dot
    # Overlaps are intentional: builder never opens these.
    for model, tiers in {"ir.config_parameter": {"secrets", "customization"},
                         "ir.mail_server": {"secrets", "customization"},
                         "ir.model.access": {"security", "customization"},
                         "ir.sequence": {"security", "customization"},
                         "mail.mail": {"secrets", "outbound"}}.items():
        assert {tier.name for tier in TIERS if tier.matches(model)} == tiers
        assert not Policy(profile_name="builder").decide("write", model).allowed


# --- aliases (a symmetric closure, merges included) -----------------------------

PAIRS = [("account.invoice", "account.move"), ("account.invoice.line", "account.move.line"),
         ("stock.quant.package", "stock.package"), ("base.automation", "base.action.rule")]


@pytest.mark.parametrize(("a", "b"), PAIRS)
def test_aliases_are_symmetric(a: str, b: str) -> None:
    assert model_aliases(a) == model_aliases(b) == frozenset({a, b})


@pytest.mark.parametrize(("a", "b"), PAIRS + [(b, a) for a, b in PAIRS])
def test_a_rule_on_either_name_of_a_pair_applies_to_both(a: str, b: str) -> None:
    profile = "builder"  # base.automation is customization: builder opens it
    deny = policy(profile, {a: {"read": False, "write": False}})
    for op in ("read", "write"):
        d = deny.decide(op, b)
        assert (d.allowed, d.rule, d.via, d.relation) == (False, f"file:{a}", a, "alias")
    assert deny.explain(b, "read") == f"{b} read: REFUSED (file:{a}, alias of {b})"
    allow = policy(profile, {"*": {"read": False}, a: {"read": True}})
    assert decided(allow, "read", b) == (True, f"file:{a}")


def test_the_mvp_asymmetry_is_gone() -> None:
    # A merge (account.invoice into account.move) used to restrict one way only.
    assert not policy(models={"account.invoice": {"read": False}}).decide(
        "read", "account.move").allowed
    assert not policy(models={"account.move": {"read": False}}).decide(
        "read", "account.invoice").allowed


def test_conflicting_exact_rules_in_a_pair_refuse() -> None:
    p = policy("standard", {"account.move": {"write": True}, "account.invoice": {"write": False}})
    assert decided(p, "write", "account.move") == (False, "file:account.invoice")
    lists = policy("standard", {"account.move": {"call": ["action_post", "button_draft"]},
                                "account.invoice": {"call": ["action_post"]}})
    assert lists.decide("call", "account.move", "action_post").allowed
    assert not lists.decide("call", "account.move", "button_draft").allowed


# --- delegation (_inherits) -----------------------------------------------------

def test_delegating_children_need_their_parent_for_every_operation_but_read() -> None:
    std = Policy()
    d = std.decide("write", "website.page")
    assert (d.allowed, d.rule, d.via, d.relation) == (
        False, "tier:customization", "ir.ui.view", "delegation")
    assert std.decide("read", "website.page").allowed
    assert std.explain("website.page", "write") == (
        "website.page write: REFUSED (tier:customization, through ir.ui.view, which "
        "website.page delegates to)")
    assert Policy(profile_name="builder").decide("write", "website.page").allowed


@pytest.mark.parametrize(("child", "parent"), [(c, p) for c, (p, _link) in DELEGATES.items()])
def test_every_delegates_row_propagates_a_refusal_on_the_parent(child: str, parent: str) -> None:
    for op in sorted(WRITE_OPERATIONS):
        refuse = policy("full", {parent: {op: False}})
        method = "action_x" if op == "call" else None
        d = refuse.decide(op, child, method)
        assert (d.allowed, d.rule, d.via, d.relation) == (
            False, f"file:{parent}", parent, "delegation"), (child, op)
        assert refuse.decide("read", child).allowed  # reads are not delegated writes
    # an explicit refusal on the parent also stops an exact opening of the child
    both = policy("builder", {child: {"write": True, "reason": REASON}, parent: {"write": False}})
    assert not both.decide("write", child).allowed


def test_delegates_is_acyclic() -> None:
    for child in DELEGATES:
        seen, current = {child}, child
        while current in DELEGATES:
            current = DELEGATES[current][0]
            assert current not in seen
            seen.add(current)


# --- the internal-note allowance (4.7) -----------------------------------------

@pytest.mark.parametrize(("args", "allowed"), [
    ({"ids": [5], "args": [], "kwargs": {"subtype_xmlid": "mail.mt_note", "body": "Called"}},
     True),  # 13+
    ({"ids": [5], "kwargs": {"subtype": "mail.mt_note", "body": "Called"}}, True),  # 10-12
    ({"args": [[5]], "kwargs": {"subtype_xmlid": "mail.mt_note"}}, True),  # ids first, legacy
    ({"args": [5], "kwargs": {"subtype_xmlid": "mail.mt_note"}}, True),
    ({"ids": [5], "kwargs": {"subtype_xmlid": "mail.mt_note", "message_type": "comment"}}, True),
    ({"ids": [5], "kwargs": {"subtype_xmlid": "mail.mt_note", "partner_ids": []}}, True),
    ({"ids": [5], "kwargs": {"subtype_xmlid": "mail.mt_note", "partner_ids": [3]}}, False),
    ({"ids": [5], "kwargs": {"subtype_xmlid": "mail.mt_comment"}}, False),
    ({"ids": [5], "kwargs": {"subtype_xmlid": "mail.mt_note", "subtype": "mail.mt_comment"}},
     False),
    ({"ids": [5], "kwargs": {"subtype_xmlid": "mail.mt_note", "subtype_id": 2}}, False),
    ({"ids": [5], "kwargs": {"subtype_xmlid": "mail.mt_note", "message_type": "email"}}, False),
    ({"ids": [5], "kwargs": {"subtype_xmlid": "mail.mt_note", "message_type": None}}, False),
    ({"ids": [5], "args": ["body"], "kwargs": {"subtype_xmlid": "mail.mt_note"}}, False),
    ({"args": [[5], "body"], "kwargs": {"subtype_xmlid": "mail.mt_note"}}, False),
    ({"ids": [5], "kwargs": {"body": "no subtype"}}, False),
    ({"ids": [5], "args": "x", "kwargs": {"subtype_xmlid": "mail.mt_note"}}, False),
    (None, False),
])
def test_the_internal_note_predicate(args: dict[str, Any] | None, allowed: bool) -> None:
    assert Policy().decide("call", "crm.lead", "message_post", args).allowed is allowed


def test_only_message_post_has_a_note_allowance() -> None:
    note = {"ids": [5], "kwargs": {"subtype_xmlid": "mail.mt_note"}}
    assert not Policy().decide("call", "crm.lead", "message_notify", note).allowed


# --- expiry (fails closed) ------------------------------------------------------

def test_expiry_drops_allowances_at_the_end_of_the_day_and_keeps_refusals() -> None:
    models = {"res.partner.bank": {"create": True, "write": True, "reason": REASON,
                                   "expires": "2026-11-15"},
              "sale.order": {"write": False, "expires": "2026-01-31"}}
    on_the_day = policy("standard", models, today=datetime.date(2026, 11, 15))
    after = policy("standard", models, today=datetime.date(2026, 11, 16))
    assert decided(on_the_day, "write", "res.partner.bank") == (True, "file:res.partner.bank")
    assert decided(after, "write", "res.partner.bank") == (False, "tier:security")
    assert decided(after, "write", "sale.order") == (False, "file:sale.order")
    # W1: sale.order refuses write while business methods still run
    assert [code for code, _text in after.warnings] == ["W1", "W4", "W4"]
    assert [code for code, _text in on_the_day.warnings] == ["W1", "W2", "W4"]
    assert after.opened_sensitive() == []
    assert [entry["model"] for entry in on_the_day.opened_sensitive()] == ["res.partner.bank"]


def test_an_expired_method_list_refuses_every_method() -> None:
    models = {"sale.order": {"call": ["action_confirm"], "expires": "2026-10-20"}}
    expired = policy("standard", models)
    assert decided(expired, "call", "sale.order", "action_confirm") == (False, "file:sale.order")
    assert decided(expired, "call", "sale.order", "action_cancel") == (False, "file:sale.order")
    live = policy("standard", models, today=datetime.date(2026, 10, 20))
    assert live.decide("call", "sale.order", "action_confirm").allowed
    assert not live.decide("call", "sale.order", "action_cancel").allowed


def test_expiry_is_checked_against_the_clock_of_each_decision() -> None:
    day = [datetime.date(2026, 11, 15)]
    p = Policy(rules=(Rule("res.partner.bank", (("write", True),), reason=REASON,
                           expires=datetime.date(2026, 11, 15)),),
               clock=lambda: day[0])
    assert p.decide("write", "res.partner.bank").allowed
    day[0] = datetime.date(2026, 11, 16)  # a long session crosses the end of the day
    assert not p.decide("write", "res.partner.bank").allowed


# --- inspect --------------------------------------------------------------------

def test_inspect_follows_any_allowed_operation() -> None:
    std = Policy()
    assert std.decide("inspect", "res.partner").allowed
    hidden = std.decide("inspect", "payment.provider")
    assert (hidden.allowed, hidden.rule) == (False, "tier:secrets")
    intake = policy("standard", {"*": {"read": False}})  # a create-only intake profile
    assert intake.decide("inspect", "crm.lead").allowed
    assert intake.ops_for("crm.lead") == frozenset({"create", "write", "call"})
    deny_all = policy("readonly", {"*": {op: False for op in OPERATIONS}})
    assert decided(deny_all, "inspect", "crm.lead") == (False, "file:*")
    readonly = policy("standard", {"crm.lead": {"read": False}}, readonly=True)
    assert not readonly.decide("inspect", "crm.lead").allowed


def test_inspect_counts_an_internal_note_and_a_listed_method() -> None:
    notes = policy("readonly", {"*": {"read": False, "call": ["message_post"]}})
    assert notes.ops_for("crm.lead") == frozenset({"call"})
    assert notes.decide("inspect", "crm.lead").allowed
    listed = policy("readonly", {"*": {"read": False}, "sale.order": {"call": ["action_confirm"]}})
    assert listed.ops_for("sale.order") == frozenset({"call"})
    assert not listed.decide("inspect", "crm.lead").allowed


# --- withheld fields (4.11) ------------------------------------------------------

@pytest.mark.parametrize(("name", "withheld"), [
    ("l10n_mx_edi_pac_password", True), ("smtp_pass", True), ("signup_token", True),
    ("signup_url", True), ("access_token", True), ("oauth_access_token", True),
    ("stripe_secret_key", True), ("ups_passwd", True), ("easypost_production_api_key", True),
    ("api_key_ids", True), ("totp_secret", True), ("password_crypt", True),
    ("credentials", True), ("Password", True),
    ("payment_token_id", False), ("payment_token_ids", False), ("token_count", False),
    ("passport_id", False), ("name", False), ("email", False), ("company_secretary", False),
])
def test_the_built_in_withheld_names(name: str, withheld: bool) -> None:
    assert Policy().field_withheld("res.company", name) is withheld


def test_withhold_beats_allow_which_beats_the_built_in_list() -> None:
    p = policy("standard", fields={
        "withhold": ["hr.employee.private_email", "*.vat", "sale.order.access_token"],
        "allow": [{"field": "sale.order.access_token", "reason": "Portal links for sales"},
                  {"field": "res.partner.signup_token", "reason": "Signup links for onboarding"}],
    })
    assert p.field_withheld("hr.employee", "private_email")
    assert p.field_withheld("res.partner", "vat") and p.field_withheld("account.move", "vat")
    assert p.field_withheld("sale.order", "access_token")  # withhold beats allow
    assert not p.field_withheld("res.partner", "signup_token")  # allow beats the built-in list
    assert p.field_withheld("res.users", "signup_token")


def test_automation_code_is_released_by_builder_and_everything_by_full_but_the_file() -> None:
    for model in ("ir.actions.server", "ir.cron", "base.automation", "base.action.rule"):
        assert Policy().field_withheld(model, "code")
        assert not Policy(profile_name="builder").field_withheld(model, "code")
    assert Policy(profile_name="builder").field_withheld("res.users", "password")
    full = policy("full", fields={"withhold": ["*.vat"]})
    assert not full.field_withheld("res.users", "password")
    assert full.field_withheld("res.partner", "vat")


def test_field_rules_follow_the_alias_closure() -> None:
    p = policy("standard", fields={"withhold": ["account.invoice.narration"]})
    assert p.field_withheld("account.move", "narration")


# --- tools/list ------------------------------------------------------------------

@dataclass(frozen=True)
class Access:
    """The shape of the permission mapping each tool will declare (registry.Access)."""

    arg_ops: tuple[str, ...] = ()
    fixed: tuple[tuple[str, str], ...] = ()
    optional: tuple[tuple[str, str], ...] = ()
    dynamic: Any = None
    degrade: bool = False
    stub: bool = False


@dataclass(frozen=True)
class Tool:
    name: str
    read_only: bool
    access: Access | None


R, W = True, False
READS = Access(arg_ops=("read",))
INSPECTS = Access(arg_ops=("inspect",))
TOOLS = [
    Tool("odoo_version", R, Access()),
    Tool("odoo_connections", R, Access()),
    Tool("odoo_telemetry_preview", R, Access()),
    Tool("odoo_list_models", R, Access(fixed=(("read", "ir.model"),))),
    Tool("odoo_module_info", R, Access(fixed=(("read", "ir.module.module"),))),
    Tool("odoo_fields_get", R, INSPECTS),
    Tool("odoo_search", R, READS),
    Tool("odoo_search_count", R, READS),
    Tool("odoo_read", R, READS),
    Tool("odoo_search_read", R, READS),
    Tool("odoo_read_group", R, READS),
    Tool("odoo_export_records_json", R, READS),
    Tool("odoo_export_records_csv", R, READS),
    Tool("odoo_translate_get", R, READS),
    Tool("odoo_api_catalog", R, INSPECTS),
    Tool("odoo_access_check", R, INSPECTS),
    Tool("odoo_record_documents", R, Access(arg_ops=("read",),
                                            fixed=(("read", "ir.attachment"),))),
    Tool("odoo_online_profile", R, Access(fixed=(
        ("read", "res.users"), ("read", "res.company"), ("read", "res.users.apikeys"),
        ("read", "ir.module.module"), ("inspect", "res.partner")), degrade=True)),
    Tool("odoo_report", R, Access(stub=True)),
    Tool("odoo_create", W, Access(arg_ops=("create",))),
    Tool("odoo_write", W, Access(arg_ops=("write",))),
    Tool("odoo_unlink", W, Access(arg_ops=("unlink",))),
    Tool("odoo_translate_set", W, Access(arg_ops=("write",))),
    Tool("odoo_import_preview", W, Access(arg_ops=("create", "write"))),
    Tool("odoo_import", W, Access(arg_ops=("create", "write"))),
    Tool("odoo_add_field", W, Access(arg_ops=("schema",), optional=(("inspect", "relation"),))),
    Tool("odoo_add_automation", W, Access(arg_ops=("schema",), fixed=(
        ("create", "base.automation"), ("create", "ir.actions.server")))),
    Tool("odoo_execute", W, Access(dynamic=lambda args: [])),
]
TOOL = {tool.name: tool for tool in TOOLS}
WRITE_TOOLS = {"odoo_create", "odoo_write", "odoo_unlink", "odoo_translate_set",
               "odoo_import_preview", "odoo_import", "odoo_add_field", "odoo_add_automation",
               "odoo_execute"}


def hidden(p: Policy) -> set[str]:
    return {tool.name for tool in TOOLS if not p.tool_visible(tool)}


def test_the_tool_table_matches_the_registry() -> None:
    real = {tool.name: tool.read_only for tool in registry.all()}
    assert {tool.name: tool.read_only for tool in TOOLS} == real
    assert len(real) == 28 and {name for name, ro in real.items() if not ro} == WRITE_TOOLS


@pytest.mark.parametrize(("profile", "expected"), [
    ("readonly", WRITE_TOOLS),
    ("standard", {"odoo_unlink", "odoo_add_field", "odoo_add_automation"}),
    ("builder", set()),
    ("full", set()),
])
def test_hidden_tools_per_profile(profile: str, expected: set[str]) -> None:
    assert hidden(Policy(profile_name=profile)) == expected
    assert len(TOOLS) - len(expected) == {"readonly": 19, "standard": 25, "builder": 28,
                                          "full": 28}[profile]


@pytest.mark.parametrize("profile", list(PROFILES))
def test_odoo_readonly_hides_exactly_the_write_tools(profile: str) -> None:
    assert hidden(Policy(profile_name=profile, readonly=True)) == WRITE_TOOLS


def test_a_locked_policy_lists_only_odoo_version() -> None:
    locked = policy("standard", {"res.partner": {"read": 1}}, locked=True)
    assert hidden(locked) == set(TOOL) - {"odoo_version"}


def test_a_tool_without_a_mapping_is_hidden() -> None:
    assert not Policy(profile_name="full").tool_visible(Tool("odoo_new", True, None))


def test_fields_yes_automations_no() -> None:
    p = policy("standard", {"*": {"schema": True}})
    assert p.tool_visible(TOOL["odoo_add_field"])
    assert not p.tool_visible(TOOL["odoo_add_automation"])  # its fixed create is customization
    assert decided(Policy(profile_name="builder"), "create", "base.automation") == (
        True, "profile:builder")


def test_an_exact_opening_makes_a_hidden_tool_visible() -> None:
    p = policy("standard", {"x_ticket": {"unlink": True}})
    assert p.tool_visible(TOOL["odoo_unlink"])
    expired = policy("standard", {"x_ticket": {"unlink": True, "expires": "2026-10-01"}})
    assert not expired.tool_visible(TOOL["odoo_unlink"])


def test_a_hidden_tool_is_refused_for_every_sampled_model() -> None:
    std = Policy()
    for model in ("res.partner", "ir.ui.view", "res.users", "x_custom", "mail.template"):
        assert not std.decide("unlink", model).allowed
        assert not std.decide("schema", model).allowed


# --- describe, explain, lock ------------------------------------------------------

def test_describe_is_the_odoo_version_policy_block() -> None:
    p = policy("standard", {"res.partner.bank": {"create": True, "write": True,
                                                 "reason": "Ticket 4312: supplier onboarding",
                                                 "expires": "2026-11-15"},
                            "res.partner": {"call": ["message_post"],
                                            "reason": "Agents reply from the chatter"}},
               fields={"allow": [{"field": "sale.order.access_token",
                                  "reason": "Portal links for the sales agent"}]})
    block = p.describe(TOOLS)
    assert set(block) == {"profile", "file", "digest", "readonly", "hidden_tools",
                          "opened_sensitive", "released_fields", "warnings", "error",
                          "error_code"}
    assert block["profile"] == "standard" and block["file"] == "/etc/odoo-tools/policy.json"
    assert len(block["digest"]) == 12 and block["error"] is None and block["readonly"] is False
    assert set(block["hidden_tools"]) == {"odoo_unlink", "odoo_add_field", "odoo_add_automation"}
    assert block["opened_sensitive"] == [
        {"model": "res.partner.bank", "ops": ["create", "write"], "tier": "security",
         "reason": "Ticket 4312: supplier onboarding", "expires": "2026-11-15"},
        {"model": "res.partner", "ops": ["call"], "tier": "outbound",
         "methods": ["message_post"], "reason": "Agents reply from the chatter",
         "expires": None},
    ]
    assert block["released_fields"] == [{"field": "sale.order.access_token",
                                          "reason": "Portal links for the sales agent"}]
    assert [w["code"] for w in block["warnings"]] == ["W2", "W2", "W7"]


@pytest.mark.parametrize(("p", "args", "line"), [
    (Policy(), ("res.users", "write"), "res.users write: REFUSED (tier:security)"),
    (Policy(), ("sale.order", "call", "action_confirm"),
     "sale.order call action_confirm: ALLOWED (profile:standard)"),
    (Policy(), ("res.partner", "call", "message_post"),
     "res.partner call message_post: REFUSED (outbound-method)"),
    (Policy(), ("ir.config_parameter", "inspect"),
     "ir.config_parameter inspect: REFUSED (tier:secrets)"),
])
def test_explain_lines(p: Policy, args: tuple[str, ...], line: str) -> None:
    assert p.explain(*args) == line


def test_explain_names_the_file_rule() -> None:
    p = policy("standard", {"sale.order": {"call": ["action_confirm", "action_cancel"]}})
    assert p.explain("sale.order", "call", "action_confirm") == (
        "sale.order call action_confirm: ALLOWED (file:sale.order)")


@pytest.mark.parametrize(("spec", "parsed"), [
    ("res.users:write", ("res.users", "write", None)),
    ("sale.order:call:action_confirm", ("sale.order", "call", "action_confirm")),
    ("res.partner:inspect", ("res.partner", "inspect", None)),
])
def test_parse_explain(spec: str, parsed: tuple[Any, ...]) -> None:
    assert parse_explain(spec) == parsed


@pytest.mark.parametrize("spec", ["res.users", "res.users:delete", ":read", "a:read:", "a:b:c:d"])
def test_parse_explain_refuses_malformed_specs(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_explain(spec)


def test_the_lock_error_has_no_setup_hint_and_names_the_option() -> None:
    locked = policy("standard", {"res.partner": {"read": 1}}, locked=True)
    exc = locked.lock_error()
    assert isinstance(exc, PolicyDenied) and isinstance(exc, PolicyError)
    assert isinstance(exc, CompatError)
    assert (exc.rule, exc.layer) == ("locked", "tool")
    assert str(exc) == (
        "odoo-tools is locked: its permission policy could not be loaded (policy file "
        "/etc/odoo-tools/policy.json: models['res.partner'].read: must be true or false). "
        "Every Odoo tool except odoo_version is disabled. Nothing was sent to Odoo. \u2014 fix "
        "the file or clear the option 'Permission policy file', then reconnect the server "
        "(/mcp in Claude Code).")
    with pytest.raises(ValueError):
        Policy().lock_error()


def test_touches_print_in_the_audit_form() -> None:
    assert str(Touch("write", "res.partner")) == "write:res.partner"
    assert str(Touch("call", "sale.order", "action_confirm")) == "call:sale.order:action_confirm"


def test_never_entries_are_well_formed() -> None:
    for entry in NEVER:
        assert entry.ops <= set(OPERATIONS) and entry.reason
        assert entry.methods is None or entry.ops == {"call"}


def test_an_unknown_profile_cannot_be_built_unlocked() -> None:
    with pytest.raises(ValueError):
        Policy(profile_name="readonyl")
