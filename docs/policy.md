# Permission policy (1.5.0)

The odoo-tools MCP server applies a **permission policy** on top of the Odoo
user's own access rights. It is a ceiling: it never grants what Odoo refuses,
it only removes rights, and it is never weaker than Read-only mode. It works the
same on Community, Enterprise and Odoo Online, because it runs in the MCP server
and needs no Odoo module.

Two plugin options set it, both with defaults:

| Option | Environment variable | Default | What it is |
|---|---|---|---|
| **Permission profile** (`odoo_policy`) | `ODOO_POLICY` | `standard` | `readonly`, `standard`, `builder` or `full` |
| **Permission policy file** (`odoo_policy_file`) | `ODOO_POLICY_FILE` | empty | optional absolute path to a JSON file with per-model rules on top of the profile |

**To keep the 1.4 behaviour, set Permission profile to `full`.** That is the
one-step escape, for example on your own company instance where you decide to
keep every right the Odoo user has. `full` still refuses the short NEVER list
(API-key changes and module uninstall), and keeps the two argument checks that
enforce it ([Profiles](#profiles)). In a container or a standalone run, set
`ODOO_POLICY=full`.

The policy is read once, when the server starts. A change needs a reconnect
(`/mcp` in Claude Code), and the new digest then shows in `odoo_version` and on
the audit start line.

## What the policy protects, and what it does not

In the local (stdio) mode the permission policy limits what Claude can do
**through the odoo-tools MCP tools**. It protects against mistakes and against
instructions hidden in data Claude reads. It does not limit the person who holds
the API key, and it is not a sandbox for an agent that has unrestricted shell
access on the same machine. The boundary that holds against everyone is the Odoo
user itself: give the agent a dedicated, least-privilege Odoo user (not an
administrator) and an API key with an expiry. In a future remote mode, where the
server keeps the Odoo credential, the same policy becomes real enforcement.

It is also not record-level (record rules belong to Odoo) and not a sandbox for
what a business method does inside Odoo (see [Known limits](#known-limits)).
`odoo_version` warns (W10) when the Odoo user is an administrator
(`base.group_system`): Odoo's access rights then narrow nothing, and this policy
is the only narrowing layer.

## Operations

| Operation | Meaning | Comes from |
|---|---|---|
| `read` | Record data: search, read, count, group, export, translations, attachments of a record | the read tools; read-class methods through `odoo_execute` |
| `create` | Create records, including `copy`, `name_create`, and imports that insert rows | `odoo_create`, the imports, create-class methods |
| `write` | Change existing records, including archiving, translations and imports that update rows | `odoo_write`, `odoo_translate_set`, the imports, write-class methods |
| `unlink` | Delete records, including x2many commands that delete lines | `odoo_unlink`, `unlink` through `odoo_execute`, x2many commands |
| `call` | Run a model method through `odoo_execute`, optionally limited to a method list | `odoo_execute` only |
| `schema` | A Studio-style change to a model (a new `x_` field, an automation on the model) | `odoo_add_field`, `odoo_add_automation` |
| `inspect` | Field metadata and access checks about one model | `odoo_fields_get`, `odoo_api_catalog`, `odoo_access_check`, and the tools' own `fields_get` calls |

- `inspect` is never granted by a rule: it is allowed on a model when any
  operation is allowed there. A model whose every operation is refused (the
  `secrets` tier) also hides its field list.
- Export is `read`: an export returns what `odoo_search_read` returns.
- Imports need both `create` and `write`, because Odoo's `load()` inserts and
  updates.

## Profiles

| Operation by model class | `readonly` | `standard` (default) | `builder` | `full` |
|---|---|---|---|---|
| read, business models | yes | yes | yes | yes |
| create, write, business models | no | yes | yes | yes |
| unlink, business models | no | no | no | yes |
| call, business methods | no | yes | yes | yes |
| call of an outbound method | no | internal notes only | internal notes only | yes |
| schema, business models | no | no | yes | yes |
| read of `security`, `outbound` and `customization` models | yes | yes | yes | yes |
| any change on `security` and `outbound` models | no | no | no | yes |
| any change on `customization` models | no | no | yes | yes |
| anything on `secrets` models | no | no | no | yes |
| credential-like fields | withheld | withheld | withheld (the code fields of automations are released) | returned |
| attachment, identity, delegation-link and context rules | on | on | on | off |
| NEVER, the name checks and the guard's envelope | on | on | on | on |
| argument shapes and related-model lookups (rules `shape` and `unverified`) | on | on | on | on |

Two facts to keep in mind:

- **`builder` equals `full` for confidentiality and integrity.** It lets the
  agent create server actions and automations: Python that runs on the Odoo
  server, with `sudo()` available, possibly later as an administrator who
  triggers it. Such code can read a system parameter and copy it into a readable
  field. The tiers under `builder` stop mistakes through the generic tools; they
  do not stop an agent that writes automation code. Use `builder` on sandboxes
  and staging only. Loading it raises warning W6.
- **`full` is the 1.4 behaviour** except NEVER, the name checks, the guard's
  envelope (which only stops a bug in odoo-tools itself) and two argument checks
  that NEVER and a policy file depend on, so a few calls that 1.4 sent need
  another form:
  - arguments the policy cannot read with certainty are refused (rule `shape`),
    for example more than three positional arguments to `read_group` through
    `odoo_execute` (the later positions differ between Odoo series), or a
    keyword it does not know on a read or write method (a business method's
    arguments are not read). Pass the arguments by name, or use the dedicated
    tool;
  - the field definitions behind a dotted path, and behind a value that may be
    x2many commands (a list, `false` or `null` in a write), are read first with
    `fields_get`: an `api_key_ids` command on `res.users` reaches
    `res.users.apikeys`, which NEVER closes. When Odoo refuses that lookup, the
    call is refused (rule `unverified`). A plain field name, or a plain value,
    needs no lookup.

`standard` refuses `unlink` but allows `call`: deletes are the one generic
irreversible verb (Odoo has no trash, and archiving is the reversible path the
refusal suggests), while refusing `call` would break `action_confirm`,
`action_post` and wizard flows. Outbound methods are closed instead. For
production with an administrator user, the [hardened example](#examples)
limits `call` to method lists.

### Tools each profile lists

`tools/list` hides a tool the policy forbids on every model, as a read-only
consent hides write tools. Hiding only over-approximates: a listed tool can
still be refused for a given model, and a hidden tool called by name returns a
tool error that says why (it is never an unknown tool). Read-only mode
(`odoo_readonly`, `ODOO_READONLY=1`) hides the 9 write tools in every profile.

<!-- generated:hidden-tools -->
| Profile | Tools not listed | Listed |
|---|---|---|
| `readonly` | `odoo_create`, `odoo_write`, `odoo_unlink`, `odoo_execute`, `odoo_translate_set`, `odoo_import_preview`, `odoo_import`, `odoo_add_field`, `odoo_add_automation` | 19 |
| `standard` | `odoo_unlink`, `odoo_add_field`, `odoo_add_automation` | 25 |
| `builder` | none | 28 |
| `full` | none | 28 |
| any profile with Read-only mode on | `odoo_create`, `odoo_write`, `odoo_unlink`, `odoo_execute`, `odoo_translate_set`, `odoo_import_preview`, `odoo_import`, `odoo_add_field`, `odoo_add_automation` | 19 |
<!-- /generated:hidden-tools -->

The server instructions gain one line that names the profile, its digest and
the hidden tools, and says that a refusal naming the permission policy is final.
Outside `full`, the description of each tool that takes a model ends with a
short reminder of the profile, for example `[Policy 'standard': no deletes or
secrets; users, rights, mail-out and customization read-only. See
odoo_version.]`.

## Sensitive tiers

Four tiers are closed by default. A model matches a tier by an exact name or a
`prefix.*` pattern (which matches the names under the prefix, not the prefix
itself), through its alias closure and through its delegation parents. When any
tier of a model withholds an operation, the operation is refused, and the
refusal names the first tier in this order. Names that do not exist on a given
version never match; the best-effort names are confirmed against live
databases. The columns say what each profile allows inside the tier; `full`
allows everything.

<!-- generated:tiers -->
| Tier | Models | `readonly` | `standard` | `builder` | Why |
|---|---|---|---|---|---|
| `secrets` | `ir.config_parameter`, `res.config`, `res.config.*`, `ir.mail_server`, `fetchmail.server`, `payment.provider`, `payment.acquirer`, `payment.token`, `iap.account`, `res.users.apikeys.show`, `res.company.ldap`, `auth_totp.device` (best-effort), `l10n_mx_edi.certificate` (best-effort), `certificate.certificate` (best-effort), `certificate.key` (best-effort), `account.online.link` (best-effort), `account.online.account` (best-effort), `mail.mail` | nothing | nothing | nothing | They hold credentials, or values that act as credentials (system parameters, mail-server and LDAP passwords, payment-provider keys and tokens, IAP tokens, a new API key, bank-sync tokens, CFDI certificates and keys, queued reset e-mails). Reading them is already the damage. |
| `security` | `res.users`, `res.users.*`, `res.groups`, `res.groups.*`, `ir.model.access`, `ir.rule`, `ir.module.module`, `base.module.*`, `change.password.*`, `portal.wizard`, `portal.wizard.*`, `auth_totp.wizard`, `auth.oauth.provider`, `res.partner.bank`, `base.partner.merge.automatic.wizard`, `mail.message`, `mail.tracking.value`, `ir.sequence`, `ir.sequence.date_range` | read | read | read | Identity and rights, login redirection, bank accounts, partner merges, chatter history and fiscal sequences: reads stay open, changes need profile 'full' or an entry naming the model exactly. |
| `outbound` | `mail.compose.message`, `mail.followers`, `mail.template`, `sms.sms`, `sms.composer`, `sms.template`, `portal.share`, `mailing.*` (best-effort), `snailmail.letter`, `account.move.send`, `account.move.send.*` (best-effort), `account.invoice.send`, `mail.mail` | read | read | read | They send e-mail, SMS, letters or share links, or decide what is sent. |
| `customization` | `ir.*`, `base.automation`, `base.action.rule`, `studio.*`, `base_import.import`, `base.language.install`, `base.language.import`, except `ir.attachment` | read | read | everything | Server actions, automations, crons, views, assets, manual fields, defaults and other ir.* records run code or change how Odoo behaves later, and the bulk import and language engines upsert or install across models; they need profile 'builder'. |
<!-- /generated:tiers -->

Why the `customization` models are closed:

- `ir.actions.server`, `ir.cron` and `base.automation` run Python on later
  triggers, as other users, with `sudo()` available; `ir.server.object.lines`
  holds Python expressions.
- `ir.ui.view` QWeb is compiled to code (a stored script on the public website
  is one write away); `ir.asset` injects JavaScript and CSS.
- Manual `ir.model.fields` can carry `compute` code; `ir.model.data` re-points
  external ids; `ir.default` sets defaults on any model; `ir.property` (up to
  17) holds company-dependent values such as default accounts.
- `ir.filters`, `ir.embedded.actions`, `ir.ui.menu`, `ir.actions.*` (URL
  redirects, printed reports) and `ir.translation` (up to 15). As a prefix,
  `ir.*` also covers the models nobody listed.

The overlaps are intentional: `ir.config_parameter` and `ir.mail_server` are
both `ir.*` and `secrets`, so `builder` keeps them closed; `ir.model.access`,
`ir.rule`, `ir.module.module` and `ir.sequence` are both `ir.*` and `security`,
so `builder` cannot change rights, install modules or renumber invoices.

`account.journal` (its bank account and sequences) is a business model in
1.5.0. Whether its writes join a tier is decided with the CFDI team after the
live check of 1.5.0.

## NEVER

No profile and no rule allows these, `full` included. The loader refuses a file
that tries to (E18).

<!-- generated:never -->
| Model | Operations | Why |
|---|---|---|
| `res.users.apikeys` | create, write, unlink, call | odoo-tools never creates, changes or revokes API keys |
| `res.users.apikeys.description` | read, create, write, unlink, call, schema | the API-key creation wizard |
| `ir.module.module` | call (`button_immediate_uninstall`, `button_uninstall`, `module_uninstall`) | uninstalling a module deletes its data |
| `base.module.uninstall` | read, create, write, unlink, call, schema | the uninstall wizard |
<!-- /generated:never -->

Private methods need no entry: the method name check
(`^[A-Za-z][A-Za-z0-9_]{0,127}$`) refuses a leading `_` on every transport, as
Odoo does. Model names must match `^[a-z0-9_.]{1,128}$`.

## Built-in rules

Profile `full` turns off the delegation-link, `ir.attachment`, identity,
outbound-method and context rules below. Two parts stay on in every profile,
because NEVER and the rules of a policy file apply under `full` too: a
delegating child still takes its parent's decision, and related records are
still checked.

### Delegation (`_inherits`)

A child model that delegates to a closed parent writes the parent's fields:
`website.page` delegates to `ir.ui.view`, so writing its `arch` writes a QWeb
view. A child therefore inherits its parent's tiers for every operation except
`read`: `website.page` writes need `builder`, while reads stay open. The
children are `website.page` and `website.controller.page` (`ir.ui.view`),
`ir.cron` and `base.automation` on 11-16 (`ir.actions.server`), and
`product.document` and `documents.document` (`ir.attachment`).

The parent's whole decision applies to the child as well, file rules included:
an exact rule on `website.page` (or `ir.cron`) does not open its writes by
itself. Open the parent too (`ir.ui.view`, or `ir.actions.server`), or use
profile `builder`. The link field of a child (`view_id`, `ir_attachment_id`, and
so on) cannot be set through the generic tools (rule `delegation-link`):
pointing it at an existing record would expose or change that record through
the child.

### `ir.attachment` is pinned to its parent

`ir.attachment` holds the binary fields of other models, including certificate
keys, so a generic read of it could reach the `secrets` tier through the back
door. A generic call on `ir.attachment` must name its parent:

- **A search** (every read-class model method that takes a top-level domain:
  `search`, `search_read`, `search_count`, `read_group`, `formatted_read_group`,
  `web_search_read`, `web_read_group`, `name_search`, `web_name_search`,
  `read_grouping_sets`, `formatted_read_grouping_sets`, `search_fetch` and the
  pivot/panel readers `read_progress_bar`, `search_panel_select_range`,
  `search_panel_select_multi_range`) needs a top-level `["res_model", "=", X]` or
  `["res_model", "in", [...]]` whose models all allow `read`, and no leaf on
  `res_field`. The guard adds `["res_field", "=", False]`, so a search never sees
  files stored in fields. A `search_panel_*` reader carries no top-level domain
  argument, so on `ir.attachment` it can never name the parent and is refused.
- **A call by ids** first reads `res_model` and `res_field` of those ids (an
  internal read the agent does not get). Every id must have no `res_field`, and
  every `res_model` must allow `read` (for reads) or `write` (for changes).
- **A create** (or a write of these values) cannot be `public` and cannot set
  `res_field`; its `res_model` must allow `write`. This holds when the write
  reaches `ir.attachment` through a delegating child too: `product.document` and
  `documents.document` expose the parent's `public`, `res_field` and `datas`
  (`_inherits`), so creating or flipping a world-downloadable public attachment
  through one of them is refused, exactly as it is on `ir.attachment` directly.

Field attachments stay readable through their parent model (`odoo_read` of
`product.template` `image_1920`), and `odoo_record_documents` keeps working
through its own pinned internal calls.

### Identity (a user's contact e-mail)

The password-reset link of a user goes to the e-mail of the user's partner, so
changing that e-mail through `res.partner` would be an account takeover. A
`write` on `res.partner` that sets `email` makes the guard read `user_ids` of
those contacts first; when one of them is a user (portal users included), the
call also needs `write` on `res.users`, which the `security` tier withholds.
An import into `res.partner` with an `email` column and an `id` or `.id` column
(an update of existing contacts) is refused, and the refusal points to
`odoo_write`, which checks each contact.

### Outbound methods

A business method can send data out: `message_post` with a partner the agent
chose e-mails anyone, and `message_subscribe` forwards every future message.
These methods are refused as a `call` unless an entry naming the model exactly
lists the method, with a reason:

<!-- generated:outbound-methods -->
`action_send_and_print`, `action_send_mail`, `message_mail_with_source`, `message_notify`, `message_post`, `message_post_with_source`, `message_post_with_template`, `message_post_with_view`, `message_subscribe`, `send_and_print_action`, `send_mail`
<!-- /generated:outbound-methods -->

**Internal notes are allowed.** `message_post` passes as a plain `call` when its
keyword arguments carry `subtype_xmlid` `"mail.mt_note"` (13+) or `subtype`
`"mail.mt_note"` (10-12), there are no `partner_ids`, `message_type` is absent
or `"comment"`, and no other positional argument is given. An internal note
notifies nobody by e-mail.

### Context keys

A call may carry only these context keys, plus `default_<field>` with a plain
value (text, number, boolean or null) on a field that is not withheld.

**A `default_<field>` that holds a list or an object is refused** (rule
`context`), before anything is sent to Odoo, for every tool, method and model and
wherever the context sits (`kwargs["context"]`, a context nested in a read
specification, or one nested in `onchange`'s `fields_spec`): x2many commands
(`[(0, 0, {...})]`, `[(4, id)]`,
`[(6, 0, ids)]`), a bare id list, nested values, even an empty list. Odoo applies a
context default to every record created while the call runs: the record the call
names, the lines its x2many commands create, and the records of other models that
a business method, a wizard or an import creates (`action_confirm`, a validation
wizard, `load`). Such a value cannot be checked against the one model the call
names, so it is not checked at all. The refusal names the key, never its value.
Pass those values in the record's values instead, where each command is decided
against the model it reaches, or use profile `full`. For example, create the MRP
backorder wizard with its lines in values,

```json
{"model": "mrp.production.backorder", "method": "create",
 "args": [{"mrp_production_ids": [[6, 0, [5]]],
           "mrp_production_backorder_line_ids": [[0, 0, {"mrp_production_id": 5,
                                                          "to_backorder": true}]]}]}
```

instead of its action's `default_mrp_production_ids` and
`default_mrp_production_backorder_line_ids` keys, and the stock backorder wizard
with `pick_ids: [(4, id)]` in values instead of `default_pick_ids`.

Odoo applies a plain default exactly as the identical key in `values`, and it rides
every record a call creates, a nested line of another model included (a
`product.document` an x2many command builds during a write on `product.template`). So a
plain `default_<field>` naming a **structural field** is refused by construction under
the sealed profiles, on a call that can create a record (not a read, where it fills
nothing): the link field of a delegation whose parent is sensitive
(`default_ir_attachment_id`, `default_view_id`, and the other `DELEGATES` links to
`ir.attachment`, a tier or a NEVER model), and `default_public` or `default_res_field`,
are refused before anything is sent, with rule `context` and the remedy above. The
refusal does not depend on the model the call names, since the `values` checks it mirrors
(delegation-link 4.4, `ir.attachment` create 4.5) run only against that top model and
cannot follow a nested create. A direct create of the model also still meets the `values`
rules.

`default_res_model` and `default_res_id` stay allowed: activity scheduling and the mail
composer pass them to bind a new record to another. The known limits note the one thing
this accepts.

The stock and manufacturing validation
wizards need some of these keys: without, for example, `button_validate_picking_ids`
or `skip_backorder`, the wizard returns `True` and validates nothing. The invoice
Confirm/Post button sends `validate_analytic` (16+), which `account.move._post`
reads to force analytic-distribution validation, and the Odoo web client puts the
signed-in user's id in `uid` on every call; it is informational, since the acting
user is the authenticated session, not `context['uid']`. None of the allowed keys
suppress chatter tracking.

<!-- generated:context-keys -->
`active_id`, `active_ids`, `active_model`, `active_test`, `allowed_company_ids`, `bin_size`, `button_validate_picking_ids`, `lang`, `location`, `mail_create_nosubscribe`, `mo_ids_to_backorder`, `picking_ids_not_to_backorder`, `read_group_expand`, `skip_backorder`, `skip_immediate`, `tz`, `uid`, `validate_analytic`, `warehouse`
<!-- /generated:context-keys -->

`tracking_disable`, `mail_notrack` and `mail_create_nolog` are absent on
purpose: they silence the chatter tracking that the `security` tier protects as
evidence.

### Related records: x2many commands and field paths

A write is checked for every record it changes, not only the model it names.
In `values` (create, write, copy defaults, `web_save`):

| Command | one2many | many2many |
|---|---|---|
| `(0, _, vals)` | create on the comodel, then its `vals` | the same |
| `(1, id, vals)` | write on the comodel, then its `vals` | the same |
| `(2, id)` | unlink on the comodel | the same |
| `(3, id)`, `(5,)`, `(6, _, ids)`, a bare id list, `False` | in a write: unlink on the comodel (Odoo deletes removed lines when the inverse is `ondelete='cascade'`); in a create: write on the comodel | write on the comodel when a tier, a file rule or NEVER refuses write there, else read |
| `(4, id)` | write on the comodel (it re-parents the line) | as above |
| anything else, depth over 4, or a field Odoo does not report while it carries commands | refused (`shape`) | the same |

So `res.partner` `user_ids: [(1, uid, {"groups_id": ...})]` is a write on
`res.users` and `res.groups`, `bank_ids` changes are writes on
`res.partner.bank`, and `order_line: [(5,)]` is a delete under `standard`. A
many2many link to a write-withheld model counts as a change to it when the link
carries the target's rights -- a user's groups (`res.users.groups_id`) or a
company's users (`res.company.user_ids`, the inverse of a user's allowed
companies). A link that only references the target changes no field of it and no
right, so a business assignment such as `project.task.user_ids` or a
`helpdesk.team` member link is a read of `res.users` and runs under `standard`.

Reads are checked along their paths: every hop of a domain leaf (including
`any` and `not any`), the nested `specification` of `web_read` and
`web_search_read`, `export_data` paths, import columns, and dotted `groupby` and
`order` terms. Each model reached must allow `read`, and no segment may be a
withheld field. In import columns, a path into a one2many (`order_line/product_id`)
creates and writes lines on the comodel. When the field metadata needed for
these checks cannot be read, the call is refused (rule `unverified`), in every
profile.

## Credential-like fields

Outside `full`, a field whose name matches
`(^|_)(password|passwd|pass|pwd|secret|token|apikey|api_key|private_key|privkey|credentials?)($|_)`,
or is `signup_url`, `smtp_pass` or `totp_secret`, is withheld. A name that
denotes a token RELATION or COUNT rather than a token value is not: the exact
names `payment_token_id`, `payment_token_ids` and `token_count`, and any name
ending in `token_id`, `token_ids` or `token_count` (so `token_id`,
`suitable_payment_token_ids` and `payment_token_count` too). They only reference
the secrets-tier `payment.token`, whose own values stay sealed. The `code` of
`ir.actions.server`,
`ir.cron` and `base.automation`, the `webhook_url` of server actions and the
`webhook_uuid` of automations are withheld too, except under `builder`
(integrations often hard-code tokens there).

A withheld field is refused wherever it appears: field lists, the `field` of
the translation tools, `values` keys (nested command values included), import
columns and export paths (every segment), `specification` keys at any depth,
`groupby`, the source fields of aggregates, `order`, and every segment of a
domain path. A filter on a secret would leak it one guess at a time. Reads lose
withheld keys at any depth, and the tool result then names them in
`policy_withheld_fields` (for example
`["res.company.l10n_mx_edi_pac_password"]`), so nothing disappears silently.

Every public method that reads record data or filters it goes through these
checks, not only `search`/`read`: the web client's `web_name_search`, the pivot
readers `read_grouping_sets` and `formatted_read_grouping_sets`, and
`filtered_domain` are reads, so their domains, grouping sets and specifications
are parsed and refused like any other. `read_progress_bar` buckets its records
by `progress_bar["field"]` (and sums `sum_field`), a second grouping dimension,
so those are checked as its `group_by` is; its result is not redacted, since its
keys are the distinct values of those (already checked) grouping fields, not field
names, and a column whose value reads like a credential word would otherwise be
dropped. These readers accept the trailing options a series adds (a panel's
`hierarchize`, `group_by` or `group_domain`), checking only the field and the
domains over the model.

A method that stays a plain `call` (a business verb such as `action_confirm`, or
a method no version of odoo-tools lists) has no such shape, so two backstops
cover it. Its result is redacted at any depth, the same as a read's, so a
value-returning method cannot become a door around the withheld-field rule. And
its arguments are scanned with the model's field metadata before it is sent: a
string argument that is a field path of the model (its first segment a field,
with any `:function` or `:granularity` aggregate suffix stripped as the grouping
readers do, so `signup_token:count` is caught) is checked as a read of that path,
so a withheld segment or a dotted leaf that hops into a sealed model is refused
(`mapped("provider_id.name")` into a secrets-tier provider, say); a Mapping
argument whose keys are fields is checked as write values, so a withheld key such
as `signup_token` and the models its x2many commands reach are refused, except on
a write-nothing simulation verb (`onchange`), whose values are the record's
existing lines and are not a write; and a domain-shaped argument (a list whose
leaves carry a recognised operator) goes through the read-path analysis. A string
that is NOT a field of the model -- a message body, a subject, an attachment file
name, a status word -- is left alone, so an
internal note and a business verb with a plain word argument still run.

The policy file can change the list: `fields.withhold` adds names (`model.field`
or `*.field`, for data minimisation), and `fields.allow` releases exact
`model.field` names, each with a reason. `withhold` beats `allow`, which beats
the built-in list.

## Precedence

`decide(op, model, method)` runs these steps in order, and the first that
decides, decides:

1. `invalid-name`: the model or method fails its name check.
2. `never:<id>`: a NEVER entry matches.
3. `readonly`: Read-only mode is on and the operation is not `read` or `inspect`.
4. `locked`: the policy could not be loaded.
5. `tool-disabled`: the tool is in `tools.disabled` (checked per tool).
6. `file:<model>`: an exact, unexpired entry that sets the operation. For
   `call`, `false` refuses, a list decides by membership (and opens tiers and
   outbound methods for the methods it lists), and `true` opens the model's
   tiers for `call` but not the outbound methods, which still need a list.
7. `tier:<name>`: a tier of the model (its own, an alias's or a delegation
   parent's) withholds the operation under the profile.
8. `outbound-method`: a `call` of an outbound method that is not an internal
   note.
9. `file:<pattern>`: the most specific pattern that sets the operation (the
   longest `prefix.*` first, then `*`).
10. `profile:<name>`: the profile default.

Steps 7 and 8 never see a pattern's allowance, so a pattern can never open a
tier or an outbound method: only an entry naming the model exactly, with a
reason, can. Adding a `false` never turns a refusal into an allowance.

**Aliases.** A rule on either name of a renamed or merged pair applies to both,
on every version: `account.invoice` and `account.move`, their `.line` models,
`stock.quant.package` and `stock.package`, `base.automation` and
`base.action.rule`, and the other renames of the compatibility map. A refusal on
either name wins. On 10 to 12 a rule on `account.move` (journal entries)
therefore also restricts `account.invoice`, and the other way round.

## The policy file

```json
{
  "version": 1,
  "comment": "Acme production: confirm and post only, no imports",
  "models": {
    "*":                {"call": false},
    "sale.order":       {"call": ["action_confirm", "action_cancel"]},
    "account.move":     {"call": ["action_post", "message_post"],
                         "reason": "Invoices are sent from the chatter by the billing agent"},
    "res.partner.bank": {"create": true, "write": true,
                         "reason": "Ticket 4312: supplier onboarding", "expires": "2026-11-15"},
    "hr.*":             {"read": false, "create": false, "write": false, "call": false}
  },
  "fields": {
    "withhold": ["hr.employee.private_email", "*.vat"],
    "allow": [{"field": "sale.order.access_token", "reason": "Portal links for the sales agent"}]
  },
  "tools": {"disabled": ["odoo_import", "odoo_import_preview"]}
}
```

The file layers rules on the profile chosen in the option and carries no profile
of its own. The schema is strict: any unknown key is an error, so a typo cannot
silently drop a refusal. An editor schema is in
[`policy.schema.json`](policy.schema.json) (the server validates in code).

| Key | Rule |
|---|---|
| top level | `version` (required, `1`), `models`, `fields`, `tools`, `comment` |
| `models` | keys are an exact model, `prefix.*` or `*`; at most 1000 entries |
| an entry | `read`, `create`, `write`, `unlink`, `schema` (true or false); `call` (true, false, or a list of 1 to 200 public method names); `reason` (10 to 200 characters); `expires` (`YYYY-MM-DD`); `comment` |
| `fields` | `withhold`: a list of `model.field` or `*.field`; `allow`: a list of `{"field": "model.field", "reason": "..."}` |
| `tools` | `{"disabled": [tool names]}` |
| parsing | at most 256 KiB, UTF-8 (a leading BOM is accepted); a duplicate key is an error |

- An entry sets only the operations it names. Method lists are not merged: the
  most specific entry that sets `call` decides.
- **Openings need a reason.** An exact entry that opens a tier operation, or
  that lists an outbound method, needs a `reason` of at least 10 characters
  (E15). `reason` and `expires` are for exact entries only (E19).
- **Expiry fails closed.** After its date (end of day, UTC) an entry's
  allowances -- a `true` value and a `call` method list alike -- are ignored and
  only its `false` refusals still apply, so the operation falls through to the
  profile. An expired method list does not become a blanket `call` refusal: the
  business verbs it named keep working under `standard`, and an expired entry
  never allows more than the same file without its allowances. Openings show in
  `odoo_version` (`opened_sensitive`), in `--check-policy` and on the audit start
  line.
- The digest is a SHA-256 over the profile, the normalised rules, the field
  rules, the disabled tools, the read-only flag and the tier data version, cut to
  12 hex characters. Comments, reasons and key order do not change it; any
  operation value does.

### Where the file lives

- **An explicit absolute path only.** The server looks in no default location,
  because an agent could create a file there and have it picked up silently.
- Recommended: `~/.config/odoo-tools/policy.json` on macOS and Linux,
  `%APPDATA%\odoo-tools\policy.json` on Windows. Keep it outside every project
  folder, and make it writable by you alone (warning W3 otherwise).
- In a container: `-v ~/.odoo-tools/policy.json:/policy/policy.json:ro -e
  ODOO_POLICY_FILE=/policy/policy.json`.

### Protecting the file and the options

None of this is required, and in stdio none of it stops an agent with an
unrestricted shell (see the statement above); it makes the seatbelt harder to
unbuckle:

- Claude Code permission rules such as
  `{"permissions": {"deny": ["Edit(~/.config/odoo-tools/**)", "Write(~/.config/odoo-tools/**)"]}}`
  cover Claude Code's file tools and the file commands it recognizes in Bash,
  not arbitrary subprocesses. Keep Bash approval prompts on.
- Plugin options from project files are ignored: Claude Code reads plugin
  options from user or managed settings only, so a cloned repository cannot set
  the profile to `full`.
- The server instructions tell the agent that a policy refusal is final and that
  it must not look for a workaround through another tool or the shell.

## Loading errors and warnings

The server never crashes on a bad policy. An unknown profile, a relative path or
an invalid file **locks** it: `tools/list` lists only `odoo_version`, which
returns the `policy` block with the error without contacting Odoo; every other
tool refuses with a text that names the error and the option that fixes it, and
says nothing was sent to Odoo; the startup log and the instructions line carry
the error, and the audit start line its E-code. In Claude Code, the plugin's SessionStart
hook also checks the two policy options and says when the server would start
locked (it reads only those two options and the three connection options it
already read, never the API key or the password).

<!-- generated:errors -->
| Code | Text |
|---|---|
| E1 | `unknown permission profile '{value}' (use readonly, standard, builder, full)` |
| E2 | `the policy file path must be absolute (got '{value}')` |
| E3 | `policy file {path}: cannot be read ({strerror})` |
| E4 | `policy file {path}: is larger than 262144 bytes` |
| E5 | `policy file {path}: is not valid JSON (line {line}, column {column}: {msg})` |
| E6 | `policy file {path}: duplicate key '{key}' (a repeated entry could hide a rule)` |
| E7 | `policy file {path}: the top level must be an object with "version": 1` |
| E8 | `policy file {path}: unknown key '{key}' at the top level (use version, models, fields, tools, comment)` |
| E9 | `policy file {path}: models['{key}']: not a model name, 'prefix.*' or '*'` |
| E10 | `policy file {path}: models['{key}']: unknown key '{op}' (use read, create, write, unlink, call, schema, reason, expires, comment)` |
| E11 | `policy file {path}: models['{key}'].{op}: must be true or false` |
| E12 | `policy file {path}: models['{key}'].call: must be true, false or a list of method names` |
| E13 | `policy file {path}: models['{key}'].call: '{method}' is not a public method name` |
| E14 | `policy file {path}: tools.disabled: unknown tool '{name}'` |
| E15 | `policy file {path}: models['{key}'] opens {ops} on {article} {tier}-tier model and needs "reason" (at least 10 characters): it is shown in odoo_version and written to the audit log` |
| E16 | `policy file {path}: models['{key}'].expires: '{value}' is not a date (YYYY-MM-DD)` |
| E17 | `policy file {path}: fields.{list}[{index}]: '{value}' is not model.field (withhold also accepts *.field)` |
| E18 | `policy file {path}: models['{key}'].{op}: cannot be granted: {reason}` |
| E19 | `policy file {path}: models['{key}']: "reason" and "expires" only apply to an entry that names one model exactly` |
| E20 | `policy file {path}: fields.allow[{index}] needs "reason" (at least 10 characters)` |
<!-- /generated:errors -->

Warnings do not lock. They appear in `odoo_version.policy.warnings`, in
`--check-policy` and on the audit start line. W10 comes from `odoo_version` at
run time: `the Odoo user of this connection is an administrator
(base.group_system): Odoo's access rights narrow nothing, so this policy is the
only narrowing layer. Prefer a dedicated user with the fewest groups that work.`

<!-- generated:warnings -->
| Code | Text |
|---|---|
| W1 | `models['{key}'] refuses create/write/unlink but allows call: business methods (e.g. action_post) can still change these records; set "call": false or list the allowed methods` |
| W2 | `models['{model}'] opens {ops} on '{model}' ({tier} tier){until}: {reason}` |
| W3 | `the policy file can be changed by other users of this machine (mode {octal})` |
| W4 | `models['{key}'] expired on {date}: its allowances are ignored, its refusals still apply` |
| W5 | `models['{key}'] sets {op} on a pattern; models of the {tiers} tiers are not affected: name a model exactly to open one` |
| W6 | `profile 'builder' lets the agent create automations and server actions, which run Python on the Odoo server with sudo() available: for confidentiality it equals 'full'. Use it on sandboxes and staging.` |
| W7 | `fields.allow releases {field}: {reason}` |
<!-- /generated:warnings -->

## Checking a file offline: `--check-policy`

```
python3 "<plugin>/server/run_stdio.py" --check-policy FILE [--profile standard] \
        [--explain MODEL:OP[:METHOD] ...] [--json]
```

It loads the file as the server would, with Read-only mode off, never contacts
Odoo, and prints the profile and the digest, the normalised rules under their
keys, the openings with their reason and expiry, the warnings, the hidden tools
and one line per `--explain`. The digest covers the read-only flag, so a server
running with `ODOO_READONLY=1` reports another digest for the same file and
profile (its `odoo_version` policy block then shows `"readonly": true`):

```
explain: res.users write: REFUSED (tier:security)
explain: sale.order call action_confirm: ALLOWED (file:sale.order)
explain: account.move read: REFUSED (file:account.invoice, alias of account.move)
explain: website.page write: REFUSED (tier:customization, through ir.ui.view, which website.page delegates to)
```

Exit codes: 0 when the file is valid, 1 when it has an error (the server would
start locked), 2 on bad usage. A relative FILE is resolved against the current
folder for the check (the option itself must be absolute), and an empty FILE
(`--check-policy ""`) checks the profile alone. `--json` prints the same report
as JSON. A team's policy repository can run it in CI.

## What `odoo_version` reports

```json
"policy": {"profile": "standard", "file": null, "digest": "e033dc413852", "readonly": false,
           "hidden_tools": ["odoo_unlink", "odoo_add_field", "odoo_add_automation"],
           "opened_sensitive": [], "released_fields": [], "warnings": [],
           "error": null, "error_code": null}
```

An `opened_sensitive` entry looks like `{"model": "res.partner.bank", "ops":
["create", "write"], "tier": "security", "reason": "...", "expires":
"2026-11-15"}`. `odoo_access_check` returns `policy` (`{op: true or false}`)
next to Odoo's own answer, with a note when Odoo allows what the policy refuses.
`odoo_list_models` leaves out the models the policy allows nothing on and says
how many (`hidden_by_policy`). `odoo_online_profile` reports a section the
policy withholds in `unavailable` instead of failing.

## Refusals

A refusal is a tool error. It names the operation, the model, the profile and
the rule that decided, then says where the call stopped, gives the remedy, and
asks the agent not to reach the same result through another tool. Only
validated names are echoed (model, field, method, operation and context key
names), never an argument value.

- **Before sign-in** (most refusals): decided from the declared accesses and
  the arguments alone, before any session exists. It ends with `Nothing was
  sent to Odoo.` and is not counted as a tool call. A context key outside the
  allowlist, and a `default_<field>` that holds a list or an object, are refused
  here (rule `context`); the second names the key and says to pass those values
  in the record's values, where they are checked, or to use profile `full`.
- **After sign-in** (the guard): every Odoo call a tool makes is checked again,
  with its values and paths, as it is sent. Such a refusal ends with `The call
  was stopped before Odoo ran it: nothing was changed and no record data was
  returned.` The server may have read field definitions to decide.
- A call outside a tool's own declared mapping is stopped as a bug in
  odoo-tools (rule `envelope`), in every profile; please report it.

The agent must treat a refusal that names the permission policy as final: tell
the user, who can change the profile or the policy file.

## Audit trail

Every tool call, refusals included, leaves one JSON line: the tool, the model
and operation names it touched (`op:model[:method]`), the layer and rule of a
refusal, counts, the duration, the exception class name of an error and the
policy digest. It never holds argument values, domains, field values, ids, file
contents, the URL, tokens, keys, passwords or error message texts. The Odoo
database and login appear only on the `start` line written when the server
starts, which also carries the profile, the file path, the warnings (codes) and
the openings with their reasons.

```json
{"v":1,"ts":"2026-10-21T15:02:11Z","seq":42,"prev":"9c1e0b7d2a44f1e3","event":"call",
 "tool":"odoo_write","layer":"B","decision":"deny","rule":"relational",
 "touches":["write:res.partner"],"effective":["write:res.users"],"n":3,"status":"refused",
 "ms":41,"policy":"a4f1c0d2e9b7"}
```

The keys are `v`, `ts`, `seq`, `prev`, `event` (`start`, `call`,
`chain_reset`), `tool`, `layer` (`tool`, `A` or `B`), `decision`, `rule`,
`touches`, `effective`, `n`, `withheld`, `status` (`ok`, `refused`, `error`,
`invalid`), `error`, `ms`, `policy`, and on the start line `profile`,
`readonly`, `version`, `pid`, `source`, `db`, `login`, `opened` and `warnings`.

| `ODOO_AUDIT_DIR` | Where the lines go |
|---|---|
| a folder (the plugin sets `${CLAUDE_PLUGIN_DATA}/audit`) | one file per UTC day, `odoo-tools-audit-YYYY-MM-DD.jsonl`, folder 0700, files 0600, never through a symlink |
| unset or `stderr` | the `odoo_mcp.audit` logger on stderr (`docker logs` in a container) |
| `off` | nothing |

`ODOO_AUDIT_RETENTION_DAYS` (default 90, `0` keeps files forever) prunes old
daily files when the server starts and at the first write after UTC midnight;
only regular files with an audit file name are ever removed. Claude Code
deletes the plugin data folder when the plugin is uninstalled from its last
scope. A failure to write never breaks a tool call.

Each line's `prev` is the first 16 hex characters of the SHA-256 of the
previous line of the same file (`genesis` on the first). `python3
server/run_stdio.py --verify-audit FILE` checks that chain: exit 0 when it
holds, 1 at the first line whose content was edited, whose order changed, or
that was inserted, or when the final line is incomplete (which it names), 2 when
the file cannot be read. Because each line only links to the one before,
verification of a single file cannot by itself detect whole trailing lines
removed from the end of a day, or a day file deleted outright: the surviving
prefix still chains. Locally this is evidence, not prevention anyway: whoever
can write the folder can rewrite the files and recompute the chain. A sink that
anchors the chain across files and restarts (so tail-truncation and a deleted
day are caught) is a remote-mode addition, not shipped here.

## Examples

Four files ship in [`policy-examples/`](policy-examples/), and CI loads each one:

| File | Profile | For |
|---|---|---|
| [`production-hardened.json`](policy-examples/production-hardened.json) | `standard` | production with an administrator user, until a least-privilege user exists: curated verbs only, no HR data, no chatter reads, no website changes, no imports |
| [`sales-team.json`](policy-examples/sales-team.json) | `standard` | a sales agent: CRM and quotations, replies to customers from the chatter, no accounting changes |
| [`read-only-analyst.json`](policy-examples/read-only-analyst.json) | `readonly` | reporting: aggregates and exports without HR data, chatter or contact details |
| [`sandbox-builder.json`](policy-examples/sandbox-builder.json) | `builder` | a training sandbox: Studio-style changes, deletes and test users |

The hardened file, for production with an administrator user:

```json
{
  "version": 1,
  "comment": "Production hardening: business reads and writes, curated verbs only, no imports",
  "models": {
    "*":            {"call": false},
    "res.partner":  {"call": ["message_post"], "reason": "Agents reply to customers from the chatter"},
    "crm.lead":     {"call": ["action_set_won", "action_set_lost"]},
    "sale.order":   {"call": ["action_confirm", "action_cancel"]},
    "account.move": {"call": ["action_post"]},
    "hr.*":         {"read": false, "create": false, "write": false, "call": false},
    "mail.message": {"read": false},
    "mail.activity":{"read": false},
    "website.*":    {"write": false, "create": false}
  },
  "fields": {"withhold": ["*.vat", "hr.employee.private_email"]},
  "tools": {"disabled": ["odoo_import", "odoo_import_preview"]}
}
```

- `"*": {"call": false}` turns `odoo_execute` into curated verbs only; its read
  methods are refused too, because `call` is required.
- The `hr.*`, `mail.message` and `mail.activity` refusals keep HR data out of
  reach through the chatter as well (see the known limits).
- The `website.*` refusal closes the published-content channel.

## Tool mapping

Every tool declares what it touches (`access=` on its `registry.tool`
decorator), and a tool without a mapping cannot be registered, listed or
called. A tool declares every model whose data it returns or whose records it
leaves changed (Layer A decides those from the arguments before any session
exists). The fixed mechanics calls it makes are `Internal` entries, each pinned
by a predicate on the actual call and given a reason; the guard (Layer B)
refuses any call that is neither declared nor an internal whose predicate holds.

<!-- generated:tool-mapping -->
| Tool | Read-only | Declared (Layer A) | Internal calls, each pinned by a predicate | Hidden in readonly / standard / builder |
|---|---|---|---|---|
| `odoo_access_check` | yes | inspect on the model asked for | `res.users` has_group | no / no / no |
| `odoo_add_automation` | no | schema on the model asked for; create `base.automation`; create `ir.actions.server` | `$automation` create, fields_get; `ir.model` search; `ir.actions.server` create, unlink | yes / yes / no |
| `odoo_add_field` | no | schema on the model asked for; inspect on the model in `relation`, when given | `ir.model` search; `ir.model.fields` create | yes / yes / no |
| `odoo_api_catalog` | yes | inspect on the model asked for | none | no / no / no |
| `odoo_connections` | yes | no model | none | no / no / no |
| `odoo_create` | no | create on the model asked for | none | yes / no / no |
| `odoo_execute` | no | call of the method asked for, plus its class (for example unlink) | none | yes / no / no |
| `odoo_export_records_csv` | yes | read on the model asked for | none | no / no / no |
| `odoo_export_records_json` | yes | read on the model asked for | none | no / no / no |
| `odoo_fields_get` | yes | inspect on the model asked for | none | no / no / no |
| `odoo_import` | no | create, write on the model asked for; the paths of the `fields` columns | none | yes / no / no |
| `odoo_import_preview` | no | create, write on the model asked for; the paths of the `fields` columns | `base_import.import` create, execute_import, unlink | yes / no / no |
| `odoo_list_models` | yes | read `ir.model` | none | no / no / no |
| `odoo_module_info` | yes | read `ir.module.module` | none | no / no / no |
| `odoo_online_profile` | yes | read `res.users`; read `res.company`; read `res.users.apikeys`; read `ir.module.module`; inspect `res.partner`; a refused section is reported, the tool still runs | none | no / no / no |
| `odoo_read` | yes | read on the model asked for | none | no / no / no |
| `odoo_read_group` | yes | read on the model asked for | none | no / no / no |
| `odoo_record_documents` | yes | read on the model asked for; read `ir.attachment` | `ir.attachment` read, search_read | no / no / no |
| `odoo_report` | yes | never calls Odoo | none | no / no / no |
| `odoo_search` | yes | read on the model asked for | none | no / no / no |
| `odoo_search_count` | yes | read on the model asked for | none | no / no / no |
| `odoo_search_read` | yes | read on the model asked for | none | no / no / no |
| `odoo_telemetry_preview` | yes | no model | none | no / no / no |
| `odoo_translate_get` | yes | read on the model asked for | none | no / no / no |
| `odoo_translate_set` | no | write on the model asked for | none | yes / no / no |
| `odoo_unlink` | no | unlink on the model asked for | none | yes / yes / no |
| `odoo_version` | yes | no model | `res.users` has_group | no / no / no |
| `odoo_write` | no | write on the model asked for | none | yes / no / no |
<!-- /generated:tool-mapping -->

The guard's own calls (`SYSTEM_CALLS` in `policy/guard.py`) return nothing to
the agent: field metadata (`type`, `relation`, `relation_field`), the
`res_model` and `res_field` of attachments, and the `user_ids` of contacts.

To add a tool:

1. Pass `access=Access(...)` to `registry.tool`: `arg_ops` for the model the
   agent names, `fixed` for models every call touches, `optional` for a model
   named by another argument, `dynamic` for a method the agent names, and
   `degrade` or `stub` where they apply. A write tool also states
   `destructive=`.
2. Declare each fixed mechanics call as
   `registry.Internal(model, methods, check=..., reason=...)`, where `check` is a
   predicate on the actual call, with one positive and one negative test.
3. Add a row to `GOLDEN` in `server/tests/test_policy_mapping.py` with sample
   arguments and the expected touches. The mapping and coverage tests explain
   what is missing when they fail.
4. Run `python3 scripts/policy_docs.py --write` to refresh the tables of this
   page (CI checks them).

## Known limits

1. **Side effects inside methods.** `action_confirm` may send a confirmation
   e-mail when Odoo is configured to, and existing automations run on allowed
   writes. Odoo governs these for the signed-in user. The hardened file limits
   `call` to method lists.
2. **Strings returned by methods are not redacted**, for example a portal URL
   that carries a token.
3. **Pointer models other than `ir.attachment`** (`mail.message`,
   `mail.activity`, `mail.followers`, `rating.rating`) matter once a file refuses
   reads on business models; the hardened example refuses them alongside
   `hr.*`.
4. **Related and computed fields with harmless names**, and display names, can
   carry data of a withheld model. Odoo field groups remain the control there.
5. **Many2one links are not checked as touches.** Setting `partner_bank_id` to
   an existing bank account is a write on the parent only.
6. **Public-facing fields are an outbound channel by effect**, for example a
   published website description. Hardened files can refuse `website.*` and
   `product.template` writes.
7. **Inference** from counts and aggregates is not prevented.
8. **In stdio, an agent with a shell can go around the policy**, and `builder`
   equals `full` for confidentiality.
9. **A nested attachment can be bound to a record through a context default.**
   `default_res_model` and `default_res_id` stay allowed, because activity
   scheduling and the mail composer pass them, so a call that creates a nested
   `ir.attachment` (directly, or through a delegating child such as
   `product.document`) can set that attachment's `res_model` and `res_id` from the
   context, binding it to another record. A direct create of the attachment with
   these values is still checked (the parent must allow `write`); only the
   nested-create path, which no check against the call's top model can follow, is
   accepted. `public` and `res_field`, which would make the attachment
   world-downloadable or a field attachment, are refused as defaults, so this binds
   an attachment, it does not expose one.
