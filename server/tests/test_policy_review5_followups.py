# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Fifth adversarial round: the two findings the verifier raised after round four.

  * A ``default_<field>`` context key is applied by Odoo on create exactly as a value
    (``_add_missing_default_values``), so the metadata-free structural value rules that
    guard ``values`` -- the delegation link (4.4) and the ir.attachment create rules
    (4.5: public / res_field / res_model) -- must run over the context defaults too.
    Round four closed the context channel only for x2many commands; a scalar
    ``default_ir_attachment_id`` (re-pointing a delegating child at an existing, possibly
    secrets-tier, attachment), ``default_public``, ``default_res_field`` and
    ``default_res_model`` slipped through. Each is refused in the ``values`` form; the
    identical setting through the context is refused the same way now, and never reaches
    Odoo. A benign default still runs.
  * An expired ``call`` method list is an allowance that design 4.10 says is IGNORED, so
    the operation falls through to the profile; it must not turn into a blanket refusal of
    every business verb on the model. The flagship CFDI flow (``action_post`` /
    ``action_confirm``) keeps working under ``standard`` after a temporary opening expires.
"""

from __future__ import annotations

from policy_fakes import ScriptedSession, call, policy, server


def _execute(raw_s, model, *, method="create", args=None, context=None, p=None):
    """Run a tool call through the full server route (Layer A + the guard) and report
    whether it errored and whether the call reached the raw session."""
    kwargs = {"context": context} if context is not None else {}
    err, text = call(server(raw_s, p=p or policy("standard")), "odoo_execute",
                     model=model, method=method,
                     args=args if args is not None else [{"name": "x"}], kwargs=kwargs)
    return err, (model, method) in raw_s.sent(), text


# --- finding 1 (blocker): the context-default structural bypass ----------------------------

def test_default_ir_attachment_id_re_points_a_delegating_child_and_is_refused() -> None:
    # product.document delegates to ir.attachment through ir_attachment_id (design 4.4);
    # the attachment (id 5) is a secrets-tier certificate field attachment in the fakes.
    raw_s = ScriptedSession()
    err, sent, _ = _execute(raw_s, "product.document",
                            context={"default_ir_attachment_id": 5})
    assert err is True, "the delegation link was set through a context default"
    assert sent is False, "the create reached Odoo carrying default_ir_attachment_id"


def test_the_same_delegation_link_in_values_is_refused_too() -> None:
    # Control: the identical re-pointing through values is refused (the existing rule).
    raw_s = ScriptedSession()
    err, sent, _ = _execute(raw_s, "product.document",
                            args=[{"name": "x", "ir_attachment_id": 5}])
    assert err is True and sent is False


def test_default_public_true_on_ir_attachment_is_refused() -> None:
    # A public attachment is downloadable without a login: an exfiltration channel (4.5).
    raw_s = ScriptedSession()
    err, sent, _ = _execute(raw_s, "ir.attachment", context={"default_public": True})
    assert err is True and sent is False


def test_default_res_field_on_ir_attachment_is_refused() -> None:
    # res_field marks a field attachment (where certificate.key / l10n_mx_edi.certificate
    # store their bytes); the create rule forbids setting it (4.5).
    raw_s = ScriptedSession()
    err, sent, _ = _execute(raw_s, "ir.attachment", context={"default_res_field": "datas"})
    assert err is True and sent is False


def test_default_res_model_pointing_at_a_sealed_model_is_refused() -> None:
    # The create rule requires write on the attachment's parent model; res.users is
    # write-sealed under standard (security tier), so the attachment cannot be parented
    # there, whether res_model is set in values or through a context default.
    raw_s = ScriptedSession()
    err, sent, _ = _execute(raw_s, "ir.attachment", context={"default_res_model": "res.users"})
    assert err is True and sent is False


def test_the_same_attachment_flags_in_values_are_refused_too() -> None:
    for values in ({"name": "x", "public": True},
                   {"name": "x", "res_field": "datas"},
                   {"name": "x", "res_model": "res.users"}):
        raw_s = ScriptedSession()
        err, sent, _ = _execute(raw_s, "ir.attachment", args=[values])
        assert err is True and sent is False, values


def test_a_benign_scalar_default_still_runs() -> None:
    # default_name touches no structural rule, so a product.document create with its own
    # content (no delegation link, no attachment flags) still reaches Odoo under standard.
    raw_s = ScriptedSession()
    err, sent, text = _execute(raw_s, "product.document", context={"default_name": "spec"})
    assert err is False, text
    assert sent is True


def test_a_benign_attachment_default_still_runs() -> None:
    # An ir.attachment create whose only default is a plain name (no public/res_field/
    # res_model) is allowed: the fix refuses the structural flags, not every default.
    raw_s = ScriptedSession()
    err, sent, text = _execute(raw_s, "ir.attachment", context={"default_name": "scan.png"})
    assert err is False, text
    assert sent is True


# --- finding 2 (major): an expired method list keeps the business verbs working ------------

def test_an_expired_call_list_leaves_action_post_working_under_standard() -> None:
    # The documented temporary-opening pattern: a billing team opened action_post and
    # message_post on account.move with a reason and an expiry. After expiry the list is
    # ignored (design 4.10), so action_post falls through to the profile and still runs --
    # it does not become a blanket refusal of every call on the model.
    models = {"account.move": {"call": ["action_post", "message_post"],
                               "reason": "Billing agent posts and mails until year end",
                               "expires": "2026-01-01"}}
    expired = policy("standard", models)  # today (2026-10-22) is past the expiry
    raw_s = ScriptedSession()
    err, sent, text = _execute(raw_s, "account.move", method="action_post", args=[[7]],
                               p=expired)
    assert err is False, text
    assert sent is True
