# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## [1.5.1] - 2026-10-29

Honest on every surface, local diagnostics, and what the Claude plugin directory
flagged. On 2026-10-28 a user who had installed the plugin in Cowork ran
`/odoo-doctor`: with no Odoo tools loaded, Claude checked Python inside Cowork's
virtual machine and then sent the user to check their Odoo Online plan. Neither
could be the cause, and nothing on the user's computer recorded what had
happened. 1.5.1 checks the surface first everywhere, keeps small metadata-only
diagnostics on the user's computer, and stops reading a credential the plugin
never asked for. The policy digest changes (`TIERS_VERSION` 2026-10-29.1) because
the sealed profiles refuse a little more; the tool count stays 28.

### Fixed

- **The doctor checks where it runs before anything else.** `/odoo-tools:odoo-doctor`
  starts with step 0: when `odoo_version` is not among the tools, it runs no shell
  command, checks no Python and gives no Odoo-side advice (plan, API key,
  database). It finds the surface, sends Cowork and Claude chat users to the Code
  tab of Claude Desktop, where the plugin installed on their Claude account
  appears as a synced plugin, or to Transgenia, and ends with a support report.
  The same check opens every skill, command and agent that calls the Odoo tools
  (`odoo-connect`, `odoo-crossversion`, `odoo-mcp-tools`, `odoo-studio-style`,
  `/odoo-tools:odoo-export`, the `odoo` and `odoo-migrator` agents), and
  `odoo-setup-mcp` says that a Python version read in Cowork belongs to its
  virtual machine, not to the user's computer.
- **Every listing says where the Odoo tools run.** The description of the
  marketplace entry overrode the one in `plugin.json`, so the 1.4.1 surface note
  never showed for marketplace installs. Both now say that the Odoo tools run in
  Claude Code and that Cowork and Claude chat load the skills and commands
  without them, with Transgenia's contact. The README says it above the badges,
  since the directory shows the README as the listing's description, and
  `plugin.json` gains the directory listing fields: icon, documentation, support,
  privacy policy and terms URLs.
- **The server reads no credential the plugin did not ask for.** It read
  `ODOO_HTTP_BEARER` from its environment and never used it (SECURITY.md listed
  it as reserved). In the plugin that value could only come from the user's own
  environment, the pattern the directory holds for a reviewer ("Uses a credential
  from the user's machine"). It is gone, and a test fails if the server reads a
  credential-like variable that `plugin.json` does not pass from a `sensitive`
  option.
- **A context passed positionally, on Odoo 10 to 12.** Those series also take a
  call's context from the positional argument that follows the method's own
  parameters, and the policy read a context only by name, so a `default_<field>`
  key with a list or object value could reach Odoo 10 to 12 that way through
  `odoo_execute`. The context rules now apply to such an argument: at Layer A on
  every series, before the series is known, and in the guarded session on 10 to
  12. For a method the policy knows, an object after its parameters is the
  context and meets every context rule; for any other method, the
  `default_<field>` keys of every positional object meet them, while a values
  object such as `{"default_code": "A-1"}` still runs. Profile `full` is
  unchanged. Refusals keep rule `context`, name the key, never its value, and say
  to pass the context by name. Not closed: on Odoo 10 to 12, the other keys of an
  object passed positionally to a method outside the policy's table are not held
  to the context allowlist (known limit 10 in `docs/policy.md`, planned for
  1.5.2). `scripts/sandbox_smoke.py` checks the refusal on every live series.
- **Release workflow.** The draft guard ran with the workflow's read-only token,
  and GitHub lists draft releases only to a token with push access, so it never
  saw a draft: a new `preflight` job, the only one with `contents: write`, runs
  nothing but that query, and `verify` waits for it. The moving image tags
  (`<major.minor>`, `latest`) are computed from the published releases and now
  stop the run when that list cannot be read, instead of tagging from an empty
  list.
- `docs/design/json2-online-lite.md` no longer shows an inline install-and-run
  command, which the directory listed as "Contains a download-and-run command".

### Added

- **Local diagnostics.** The MCP server writes small, metadata-only records to
  `server.jsonl` in `ODOO_DIAG_DIR` (the plugin passes
  `${CLAUDE_PLUGIN_DATA}/diagnostics`; unset or `off` writes none): `start`
  (plugin, Python and OS versions, transport preference, read-only mode, policy
  profile and digest or E-code, which connection settings are present, the kind
  of credential, the audit mode, and the `CLAUDE_CODE_ENTRYPOINT` token),
  `connect` (the Odoo major version, edition, deployment and transport, or an
  error category with the HTTP status), `crash` (the exception class and the
  plugin's own frames) and `stop` (uptime, calls, errors by category). Every key
  is checked against an allowlist: no URL, host, database, login, key, password,
  policy file path, record data, argument or error message is ever written.
  Lines stay under 2 KB, each file rotates to `<name>.1` at 256 KiB, the folder
  is created owner-only and files are 0600, and a failure to write never reaches
  a tool call.
- **The support report.** `python3 server/run_stdio.py --diagnose [--diag-dir DIR]
  [--audit-dir DIR] [--json]` prints what a user can paste to support, under the
  header "odoo-tools support report (no keys, URLs, logins or record data)": the
  versions, the diagnostics folder (the home folder written as `~`), the last
  server and hook events re-checked against the allowlist, the last 7 days of
  audit counts by status and refusal rule, and the policy computed offline. It
  never contacts Odoo. `/odoo-tools:odoo-doctor` runs it on the plugin's own
  folders.
- **A new session-start hook, `hooks/session_start.py`, replaces
  `hooks/check_options.py`.** It reads no plugin option and no credential: only
  `CLAUDE_PLUGIN_DATA`, `CLAUDE_CODE_ENTRYPOINT`, the event's source and session
  id, the end of the server's `server.jsonl`, the container-mode marker, its
  daily timestamps and the plugin's own version. When the last 14 days record
  neither a successful connection nor a server start with every connection
  setting, it tells Claude on every session, surface first (Cowork and Claude
  chat never run the Odoo tools; the Code tab of Claude Desktop or Claude Code;
  where the options are set; the doctor; Transgenia), with one
  `odoo-tools session diagnostics:` line the doctor can report from any surface,
  and shows a shorter notice at most once a day; a start locked by the policy is
  named with its E-code. It writes one metadata line per session to
  `hook.jsonl`. The first hook's message for a computer without `python3` now
  says that in Cowork and Claude chat the Odoo tools do not run with or without
  Python.
- **Container mode marker.** `/odoo-tools:deploy-local` container mode creates
  `${CLAUDE_PLUGIN_DATA}/diagnostics/container-mode`, so the hook stays silent
  while the container server is the one in use.
- **Claude Desktop extension preview.** `scripts/build_mcpb.py` builds
  `odoo-tools-<version>.mcpb` from the same server and a manifest generated from
  `plugin.json`, and `.github/workflows/mcpb-preview.yml` validates it with the
  official MCPB tool at a pinned version, starts it with no network and uploads
  it as a workflow artifact for manual testing. The bundle never enters the
  plugin folder (the directory holds a plugin that ships one) and is not
  published yet; `docs/desktop-extension.md` describes it.
- **Product rules.** `docs/product-rules.md` states the rules for this plugin: it
  installs on every surface Anthropic allows and is never blocked on one; it is
  honest where its tools cannot run and leads to Transgenia; local is free and
  hosted is premium; credentials never travel through a conversation;
  diagnostics stay on the user's computer; the directory numbers are reviewed
  every month; and every change is checked against the manual at
  docs.transgenia.org, in Spanish, English and Chinese. `test_product_rules.py`
  checks what a test can. A `CLAUDE.md` and a pull request template carry them to
  contributors and to Claude Code sessions.
- **Evals.** `evals/` holds three `claude plugin eval` cases (Cowork, Claude chat,
  Claude Code with empty options); an eval run never starts the plugin's MCP
  server, so each case sees what a Cowork user sees.

### Changed

- `PRIVACY.md` describes the diagnostics files and the support report, the hook
  that reads no plugin option, and the desktop extension preview's storage.
  `SECURITY.md` explains each finding the directory lists for this plugin and
  where to verify it. `SUPPORT.md` puts the surface first and explains the
  support report. The README, `SUPPORT.md`, `SECURITY.md` and `PRIVACY.md` drop
  their em dashes (the README keeps the Claude Desktop label it quotes).

## [1.5.0] - 2026-10-23

Secure defaults: a permission policy on top of the Odoo user's own access rights,
checked before and while each tool calls Odoo, and a local audit trail. The
default tightens inside this minor release; to keep the 1.4 behaviour, set the
new option **Permission profile** to `full`. The tool count stays 28.

### Changed (secure defaults)

- **Permission policy.** The MCP server now applies a permission profile on top of the
  Odoo user's own access rights. The default, `standard`, reads, creates, updates and runs
  business methods, but does not delete, make Studio-style changes, send e-mail or SMS
  (internal notes are fine), change users, rights, modules, settings, bank accounts, fiscal
  sequences or chatter history, or read stored secrets (system parameters, mail-server,
  payment-provider and CFDI certificate credentials). Credential-like fields (passwords,
  tokens, keys) are refused in field lists, values, filters, grouping and sorting, and are
  removed from what reads return (the result names them in `policy_withheld_fields`).
  Tools the profile forbids are not listed. **To keep 1.4 behaviour, set Permission
  profile to `full`** (`ODOO_POLICY=full` in a container or a standalone run): API-key
  changes and module uninstall stay refused in every profile, and, to enforce that, `full`
  still refuses a call whose arguments the policy cannot read with certainty (pass them by
  name) or whose related models it cannot look up with `fields_get`. The other profiles are
  `readonly` and `builder` (adds fields, views and automations; for sandboxes and staging,
  since automations run code on the server). Details: `docs/policy.md`.
- Tools the profile forbids on every model are no longer listed: `standard` lists 25 of the
  28 (not `odoo_unlink`, `odoo_add_field` or `odoo_add_automation`). A hidden tool called by
  name explains why. Every refusal names the profile, the rule and what changes it. Most are
  decided from the call's arguments before any session exists, so nothing reaches Odoo.
- Every Odoo call a tool makes is checked again as it is sent, with its values and paths:
  the records a write changes through one2many and many2many commands (a line a write
  removes counts as a delete, and a link to users or groups as a change to them), the models
  a filter, a read specification, a groupby, an order or an export or import column reaches,
  and the parent of an attachment (a generic `ir.attachment` search must name the parent
  model and never sees files stored in fields; writing an attachment's `public` or
  `res_field` through a delegating child such as `product.document` is refused too). A
  contact that is a user's login keeps its e-mail, and the link field of a model that
  delegates to a closed one (`website.page` `view_id`) cannot be set. Such a refusal comes
  after sign-in and says that Odoo did not run the call. A call outside a tool's declared
  mapping is stopped as a bug.
- **A context default must be a plain value.** Under `readonly`, `standard` and `builder`,
  a `default_<field>` context key whose value is a list or an object (x2many commands, a
  list of ids, nested values) is refused before anything is sent to Odoo, for every tool,
  method and model (rule `context`); the refusal names the key, never its value. Odoo
  applies a context default to every record created while the call runs, including the
  lines that x2many commands create and the records of other models that a business
  method, a wizard or an import creates (`action_confirm`, a validation wizard, `load`), so
  such a value can never be checked soundly against the one model a call names. Pass those
  values in the record's values, where they are checked, or use profile `full`. For
  example, create the MRP backorder wizard (`mrp.production.backorder`) with its lines in
  values, `{"mrp_production_ids": [(6, 0, [mo_id])], "mrp_production_backorder_line_ids":
  [(0, 0, {"mrp_production_id": mo_id, "to_backorder": true})]}`, instead of its action's
  `default_mrp_production_ids` and `default_mrp_production_backorder_line_ids` keys, and
  the stock backorder wizard with `pick_ids: [(4, id)]` instead of `default_pick_ids`. A
  plain default (`default_move_type: "out_invoice"`) still runs unless its field is
  withheld, and `full` is unchanged.
- Methods that return record data or filter it but are not search/read (`search_fetch`,
  `fetch`, `onchange`, `read_progress_bar`, `search_panel_select_range`,
  `search_panel_select_multi_range`, `copy_data`, the web `web_name_search`, the pivot
  readers `read_grouping_sets` and `formatted_read_grouping_sets`, and `filtered_domain`)
  are read, not opaque `call`s, so their domains, grouping sets, fields and specifications
  go through the withheld-field and comodel checks and their results are redacted.
  `read_progress_bar` also checks the field it buckets by (`progress_bar["field"]`, and any
  `sum_field`), a second grouping dimension. As a backstop, a method that stays a plain
  `call` (a business verb, or one no version lists) has its result redacted at any depth
  too, and its arguments are scanned with the model's field metadata before it is sent: a
  string that is a field path of the model is checked as a read of that path (a dotted leaf
  that hops into a sealed model, such as `mapped("provider_id.name")` into a payment
  provider, is refused), a Mapping whose keys are fields is checked as write values (a
  withheld key such as `signup_token`, and the models its x2many commands reach, are
  refused), and a domain-shaped argument goes through the read-path analysis. A string that
  is not a field of the model -- a message body, a subject, an attachment file name, a
  status word -- is left alone, so an internal note and a business verb with a plain word
  argument still run. The bulk import engine (`base_import.import`) and the language wizards are in the
  `customization` tier, reachable only through their tools, so `odoo_execute` cannot drive
  the importer's `load()` into a closed model.
- With Read-only mode on, the write tools are no longer listed (calling one still explains
  why).
- `odoo_report` now refuses before calling Odoo: it called the private method
  `ir.actions.report._render_qweb_pdf`, which Odoo refuses over RPC on every
  version, so it could never succeed. Use `odoo_record_documents` for the PDFs Odoo
  already stored (for example an invoice PDF made when it was sent or printed). The
  tool is deprecated and removed in 2.0.0. It says so even before a connection is
  configured, since it never asks for a session.
- `odoo_online_profile` reports a section the policy withholds in `unavailable` instead of
  failing.
- The write tools state `destructiveHint` in their annotations: false for `odoo_create`,
  `odoo_add_field` and `odoo_import_preview`, true for the others.
- Scope: a generic, declarative permission policy is part of the public core; approval
  workflows, localization engines and backups are not (README, CONTRIBUTING,
  `docs/architecture.md`).
- The skills and the `odoo` agent say which profile a task needs: Studio-style changes need
  `builder`, and the training's delete step archives under `standard`.

### Added

- Options **Permission profile** (`odoo_policy`: `readonly`, `standard`, `builder`, `full`;
  default `standard`) and **Permission policy file** (`odoo_policy_file`, optional: an
  absolute path to a JSON file with per-model rules, method lists, field rules and openings
  that need a reason and may expire; `docs/policy.md`). Both have defaults. An unknown
  profile or an invalid policy file locks every tool except `odoo_version`, which shows the
  error; the server never looks for a policy file in a default place.
- `docs/policy.md` (profiles, tiers, rules, the file format, every error and warning, the
  tool mapping), `docs/policy.schema.json` for editors, and four examples in
  `docs/policy-examples/` (`production-hardened`, `sales-team`, `read-only-analyst`,
  `sandbox-builder`), each loaded by CI. Their tables are generated from the policy's own
  data (`scripts/policy_docs.py`) and checked in CI.
- `python3 server/run_stdio.py --check-policy FILE [--profile P] [--explain
  MODEL:OP[:METHOD]] [--json]` checks a policy file offline as the server would load it
  (with Read-only mode off, which the digest covers) and explains decisions, for example
  `res.users write: REFUSED (tier:security)`; exit 0 valid, 1 invalid, 2 bad usage. It never
  contacts Odoo.
- **Audit log.** One JSON line per tool call, refusals included: the tool, the model
  and operation names, the layer and rule of a refusal, counts and timings; never
  values, domains, ids or secrets, and the Odoo login only on the line written at
  start. The plugin writes daily files to its data folder, owner-only, kept 90 days
  and hash-chained; `python3 server/run_stdio.py --verify-audit FILE` names the
  first edited, reordered or inserted line, or an incomplete final line (it cannot,
  from one file alone, catch whole trailing lines removed or a deleted day). The
  plugin also pins `ODOO_AUDIT_RETENTION_DAYS`; containers and standalone runs set
  `ODOO_AUDIT_DIR` (a folder, `stderr` or `off`) and `ODOO_AUDIT_RETENTION_DAYS`.
- `odoo_version` returns a `policy` block (profile, file, digest, hidden tools, openings,
  warnings, or the error that locked it) and warns (W10) when the Odoo user is an
  administrator. `odoo_access_check` returns `policy` next to Odoo's own answer, with a note
  when Odoo allows what the policy refuses. `odoo_list_models` leaves out the models the
  policy allows nothing on (`hidden_by_policy`). The server instructions gain one line with
  the profile, its digest and the hidden tools.
- The SessionStart hook also checks the two policy options (and reads no other new
  variable): when the server would start locked, it tells the user once a day and tells
  Claude why. It still never reads the API key or password option.
- The sandbox matrix (`sandbox-matrix.yml`, Odoo 10.0 to 19.0) also checks the permission
  policy against each live series (`scripts/sandbox_smoke.py`): the `policy` block of
  `odoo_version` against `--check-policy`; the `standard` refusals that need Odoo's own
  metadata (a company's or a contact's user links, a user's contact e-mail, credential-like
  fields in field lists, filters and full reads, `ir.attachment` pinned to `certificate.key`);
  the link field of each delegating model that is installed; `odoo_add_field` and
  `odoo_add_automation` under `builder` (`base.action.rule` on 10.0); and `--verify-audit`
  on the audit trail of the run. It prints which tier model names exist on each series. A
  check whose model or field a series lacks is skipped with its reason.
- Release workflow: a manual run can now be a **draft** (`release.yml`, input
  `draft`). It creates the tag, runs the tests and leaves a draft GitHub Release with
  the artifacts, but builds no container image and uploads nothing to PyPI.
  Publishing the draft runs those jobs. `docs/packaging.md` describes the steps, and
  `tests/test_release_workflow.py` checks that a draft run publishes nothing.

### Fixed

- Release workflow: a skipped `tag` job no longer skips the release. On a
  `release: published` event or a tag push the `tag` job does not run, and a job
  whose condition had no status function got an implicit `success()`, which is false
  when any job up its `needs` chain was skipped. Publishing the v1.4.1 draft on
  2026-10-21 therefore ran only `verify`; v1.4.1 was then published with a manual run.
  Every job after `verify` now starts with `!failure() && !cancelled()`, and
  `tests/test_release_workflow.py` fails if one loses it.
- Release workflow: `verify` checks the release state before any publishing job
  starts (a full run stops while the tag's release is still a draft, and a draft run
  stops if the tag already has a release), and the moving image tags `latest` and
  `X.Y` compare against published releases plus the tag being released, so a tag kept
  by an unpublished draft cannot hold them back.
- The call-class argument backstop no longer refuses ordinary chatter. It scans a
  business method's arguments with the model's field metadata, so only a string that is
  really a field of the model is checked: an internal note or a customer reply whose body,
  subject or attachment file name happens to read like a credential (`"Pass"`, a subject
  `"Password"`, `VAT.pdf`, `Boarding_Pass.pdf`) now runs, and `mail.activity` feedback does
  too. The same metadata resolves a dotted string or a domain-shaped argument through the
  tier and read checks, closing a read of a secrets-tier model through `mapped`, `filtered`,
  `sorted` or another value-returning `call` whose dotted leaf hops into it (for example
  `mapped("provider_id.name")` into a payment provider), including through a domain carrying
  a `(1, '=', 1)` true leaf. A Mapping handed to a module-specific `call` has its keys
  checked as write field names (and its x2many commands expanded), so a withheld field such
  as `signup_token` cannot be set through a bespoke verb when `odoo_write` refuses it.
- Assigning a user through two business relations runs under `standard`: task assignees
  (`project.task.user_ids`) and helpdesk team members (`helpdesk.team.member_ids`), the
  fixed `REFERENCE_LINKS` list in `policy/tiers.py`, count as a `read` of `res.users`.
  Every other many2many link to a write-withheld model is still a `write` of it, and so
  refused under `standard` (for example `res.users.groups_id` or `res.company.user_ids`,
  which carry rights). Project task assignment and helpdesk membership no longer need
  profile `full`.
- Odoo's stock and manufacturing validation wizards run under `standard`: the context keys
  they need to validate the records named (`button_validate_picking_ids`, `skip_backorder`,
  `picking_ids_not_to_backorder`, `skip_immediate`, `mo_ids_to_backorder`) are allowed, as
  are `warehouse` and `location` (stock on hand). None of the added keys suppress chatter
  tracking. A wizard created directly through `odoo_execute` takes its pickings or lines in
  values (`pick_ids: [(4, id)]`), not in a `default_` list (see Changed).
- Posting a customer invoice runs under `standard`: `validate_analytic`, the context key the
  invoice Confirm/Post button sends (16+) so `account.move._post` validates the analytic
  distribution, is allowed. `action_post` was already a business verb; only the context key
  refused the flagship CFDI flow, and no allowed key suppresses chatter tracking.
- The call-class backstop fails closed on a malformed x2many command list. A Mapping
  handed to a module-specific `call` whose x2many value is not a clean command list, such
  as a command tuple mixed with a bare id (`[(4, 4), 99]`), is refused with rule `shape`,
  exactly as the same list in `values` is, instead of being scanned as a plain nested
  value, so a `(4, id)` link into a sealed tier cannot slip past next to a bare id.
- The create-only structural default rules (delegation link, `ir.attachment` create) run
  only for a call that creates records, or may (create, `web_save`/`load` and
  business-method calls). A default fills nothing on a read, so a pinned `ir.attachment`
  search whose context names the record's parent (`default_res_model: res.partner.bank`,
  readable but not writable under `standard`) is no longer refused on the create rule, and
  neither is a read of a delegating child carrying its link-field default.
- The Odoo web client's `uid` context key is allowed. It carries the signed-in user's id on
  every call and is informational -- the acting user is the authenticated session, not
  `context['uid']` -- so `account.move.action_post` and `sale.order.action_confirm` replayed
  with the real web-client context run; it was the one key the allowlist still refused, and
  it suppresses no chatter tracking.
- A plain `default_<field>` context key cannot ride a nested create past the delegation-link
  (4.4) and `ir.attachment` create (4.5) rules. Odoo applies a context default to every
  record a call creates, including a line of another model an x2many command builds (a
  `product.document` created during a write on `product.template`), which no check against
  the call's top model can follow. So under `readonly`, `standard` and `builder`, a scalar
  `default_<field>` naming a structural field is refused by construction, at Layer A, on a
  call that can create a record: the link field of a delegation whose parent is a tier, a
  NEVER model or `ir.attachment` (`default_ir_attachment_id`, `default_view_id`, and the
  other `DELEGATES` links), and `default_public` or `default_res_field`. The refusal (rule
  `context`) names the key, never its value, and gives the remedy (pass the value in the
  record's values, or use profile `full`). The refused field names are derived from
  `DELEGATES` and the `ir.attachment` structural fields, so a new delegation row is covered
  automatically. `default_res_model` and `default_res_id` stay allowed, because activity
  scheduling and the mail composer pass them; a nested attachment can still be bound to a
  record through them, which is an accepted, documented limit (`docs/policy.md`). On a read a
  default fills nothing, so it is left alone (a pinned `ir.attachment` search whose context
  names the record's parent runs); a benign default (`default_move_type`) still runs, and
  `full` is unchanged.
- A context nested in `onchange`'s `fields_spec` (Odoo 17+, the web_read specification form,
  passed by name or positionally) is now collected, so a list default hidden inside it is
  refused with rule `context` like any other nested context; before, it was the one
  specification the collector skipped, contradicting `docs/policy.md`. `onchange` stays a
  write-nothing simulation (its values are not checked as writes), and the pre-17 flat
  `field_onchange` argument, which carries no nested context, still runs.
- An expired `call` method list is now ignored, not turned into a blanket refusal. A method
  list is an allowance, so expiry drops it exactly as it drops a `true` value: the operation
  falls through to the profile and only a `false` refusal survives. After a temporary
  opening such as `account.move: {"call": ["action_post", "message_post"], "expires": ...}`
  lapses, `action_post` and `action_confirm` keep working under `standard` (the opening's
  outbound `message_post` correctly reverts to internal notes only); before, every `call` on
  the model, business verbs included, was refused.
- A value-returning `call` whose string argument names a withheld field carried as a grouped
  term (`signup_token:count`, `name:sum(signup_token)`) is refused: the backstop strips the
  `:function`/`:granularity` aggregate suffix before deciding the field, as the enumerated
  grouping readers do, so the oracle is closed whichever form it takes.
- `onchange`, a write-nothing simulation, runs under `standard` again. Its values are the
  record's existing lines, encoded as x2many replace or clear commands
  (`[(6, false, ids)]`, a bare id list, `[(5,)]`); the call-class backstop no longer expands
  them as writes or unlinks of the comodel, so previewing the totals of a quotation or a
  contact form that already has lines is not refused. Its result is still redacted.
- An internal note with an attachment in Odoo's three-element `(name, content, info)` form
  runs even when the file name reads like a credential (`password_policy.pdf`,
  `Credentials_SAT.pdf`). A three-element list is a domain term, and so routed through
  domain analysis, only when its middle element is a recognised domain operator; an
  attachment tuple carries file content there, so it is not mistaken for a domain and its
  file name is not read as a field path.
- `read_progress_bar`'s result is no longer over-redacted. Its keys are the distinct values
  of the (already checked) grouping fields, not field names, so a kanban column or bucket
  whose value reads like a credential word (`Pass`, `Token`, a `pass` quality state) is kept
  instead of being dropped with a misleading `policy_withheld_fields`.
- The `ir.attachment` pin now covers every read-class model method that takes a top-level
  domain, not a hand-kept subset: `search_fetch`, `read_progress_bar` and the
  `search_panel_*` readers on `ir.attachment` are pinned to a readable parent and stopped
  from filtering on `res_field`, closing an id/count/`res_model` oracle over a sealed model
  (`certificate.key`, `payment.provider`). A `search_panel_*` reader carries no top-level
  domain and so is refused on `ir.attachment`.
- The `search_panel_*` readers and `read_progress_bar` accept the trailing options a series
  adds (`hierarchize`, `group_by`, `group_domain`, `sum_field: false`) instead of failing
  closed with rule `shape`, so mirroring a kanban or search panel through `odoo_execute`
  runs; the field and the domains over the model are still checked.
- `web_name_search` is read with the web module's own signature,
  `(name, specification, domain=None, operator, limit)` -- the specification is the second
  argument, not the domain -- so a positional call from the web client is no longer refused
  with rule `shape`.
- Harmless token relations and counts are no longer withheld. A field name ending in
  `token_id`, `token_ids` or `token_count` (so `token_id`, `suitable_payment_token_ids`,
  `payment_token_count`, alongside the existing `payment_token_id`/`payment_token_ids`/
  `token_count`) references the secrets-tier `payment.token` rather than a token value, so
  reading it is allowed; token VALUE fields (`access_token`, `refresh_token`) stay withheld.
- Sessions are cached by `url|db|login` plus a per-process HMAC over the whole
  connection identity and the secret (`Credentials.session_key()`), so the same url,
  db and login with another secret never reuses an authenticated session, and two
  credentials whose `url|db|login` strings collide only because a component contains
  `|` still key apart. `fingerprint()` is unchanged, and the secret is never part of a
  key or a log line.
- `odoo_connections` no longer returns the `user:pass@` of `ODOO_URL` (the basic-auth
  credential of a gateway in front of Odoo): it is stripped, as the transport, the
  guard's credential view and the redacted settings already strip it. It was returned
  verbatim under every profile, read-only included.
- A policy file whose entire content is the JSON value `null` now locks with E7, like
  any other non-object top level, instead of loading unlocked as the profile alone
  while `odoo_version` and the audit reported a file in force.
- The audit `start` line is written even when a path, database or login carries
  non-UTF-8 bytes (surrogate escapes), and a pre-existing daily file with looser
  permissions is tightened to `0600` before it is appended to.
- `odoo_add_automation` on Odoo 10 now fills `base.action.rule`'s required trigger field,
  which that version names `kind` (not `trigger`); the automation was created without it
  before. The value is the same one the tool already maps (`on_create`, `on_write`,
  `on_create_or_write`, `on_unlink`).

### Removed

- `ConnectionManager.from_headers`. It had no caller, and as written it fell back
  to the server's own secret when a request had no `Authorization` header, took
  the Odoo URL from a client header and passed the client's bearer through to Odoo.
  A remote HTTP mode will resolve sessions from an authenticated identity.

### Security

- In the local (stdio) mode the policy limits what Claude can do through these tools; it
  does not limit the holder of the API key, nor an agent with unrestricted shell access on
  the same machine (`SECURITY.md`, "Permission policy"). Use a dedicated, least-privilege
  Odoo user with an expiring API key.

## [1.4.1] - 2026-10-21

Documentation and diagnostics release: where the Odoo tools run, a notice when the
connection options are missing, and a stricter clean-room rule. The MCP server's
behaviour is unchanged (only its reported version moves to 1.4.1).

### Fixed
- **Documentation: the Odoo tools do not run in Cowork or Claude chat.** v1.4.0
  said the MCP server works in a local Cowork session. Anthropic's plugin support
  matrix (https://claude.com/docs/plugins/platform-support) says Cowork does not
  prompt for plugin options and ignores an MCP server that references an option
  without a default (this plugin's URL, database, login and credentials have
  none), and that chat ignores a plugin's local MCP server. A user who installed the plugin
  from Cowork saw **odoo — Runs in each session** with an empty panel and no way
  to enter the connection options. The README support table, `docs/install.md`,
  `SUPPORT.md`, the plugin description and the `odoo-mcp-tools` skill now say
  where the tools run; the README explains the empty panel and the route that
  works (Claude Code, including `claude plugin configure` for headless machines);
  and the guided route (`odoo-setup-mcp`, new Phase 0b) checks the surface, from
  its tool list and before any shell command, before it troubleshoots Python. No
  server code changed.
- `docs/third-party-ideas.md` listed the Odoo Apps `mcp_server` module, which
  `ivnvxd/mcp-server-odoo` requires in its standard mode, as MPL-2.0. The module is
  a proprietary third-party module under the Odoo Proprietary License (OPL-1);
  `ivnvxd/mcp-server-odoo` itself is MPL-2.0. Nothing from either was copied.

### Added
- **Missing-options notice at session start** (`hooks/check_options.py`, a second
  SessionStart hook). When the Odoo URL, database or login has no saved value it
  emits hook JSON: `systemMessage` for the user, on a new session and at most once
  a day (timestamp file in the plugin's data folder), and `additionalContext` for
  Claude on every SessionStart; with the container mode's
  `~/.odoo-tools/mcp/odoo.env` present only Claude is told. It checks the
  `CLAUDE_PLUGIN_OPTION_*` variables of those three non-sensitive options for
  presence only. It keeps the v1.2.0 rule that no hook reads the API key or
  password option (a directory finding), never prints, stores or sends a value,
  and always exits 0. `hooks.json` starts it in shell form only when `python3` is
  3.9 or newer, so a missing or old Python shows no error from this hook (the first
  hook explains a missing `python3`; an older one is caught by the guided route's
  Step 1A). That holds on macOS, Linux and Windows with Git Bash: without Git Bash,
  Windows runs shell-form hooks in PowerShell, where both hooks fail (README,
  Requirements). A shell-form hook cannot reference `${user_config.*}`, so the
  script reads the environment. It reads the event as bytes, so a Windows code page
  cannot garble a non-ASCII working directory, and a timestamp dated in the future
  (clock set back, restored backup) counts as due. Known limit: a non-interactive
  session (`claude -p`, the Agent SDK) started that day also uses up the daily
  notice. Tests: `tests/test_session_start_hook.py`, including a run with a
  recording `os.environ` that fails if the hook looks up a credential variable or
  scans the environment, and checks that no value reaches stdout, stderr or the
  timestamp file.
- `PRIVACY.md`: Claude Code also exports saved options to the plugin's hook
  processes (the hooks do not read the sensitive ones), and the hook's timestamp
  file is listed under local storage.
- `tests/test_docs_surfaces.py`: every `${user_config.KEY}` the server references
  is declared; the README does not promise the Odoo tools where the options cannot
  be entered; the guided route triages the surface before Python.
- `tests/test_license_hygiene.py`: no file in the repository, tracked or not (so a
  copied file is caught before it is committed), declares a license MIT cannot
  absorb: an Odoo manifest `license` such as OPL-1 or (L/A)GPL, the OPL-1 or AGPL
  title in a file that is not Markdown (a copied LICENSE or code header), or an
  SPDX expression with any id MIT cannot absorb (`MIT AND GPL-3.0-only` included).
  Mentions in Markdown documentation stay allowed, and
  five files that discuss these licenses on purpose are listed by name. Also MIT
  SPDX headers on our own Python code (including `server/run_stdio.py`), MIT in the
  three manifests, and the clean-room rule covering OPL-1 in `CONTRIBUTING.md` and
  `NOTICE`.

### Changed
- **One-step install.** The README, `docs/install.md`, `docs/packaging.md` and the
  skills now install with `/plugin install odoo-tools --marketplace
  Transgenia/MCP-Odoo-Tools-CE-EE-and-online` (Claude Code 2.1.275 or later, the
  line `claude plugin validate` advises), keeping the two-step commands for older
  versions.
- README, "Where it works": Cowork and Claude chat accept MCP connectors you add
  yourself (a remote server by `https` URL, added by an Owner in Organization
  settings > Connectors on Team and Enterprise, or under Customize > Connectors; or
  a desktop extension in the Claude desktop app); the plugin provides neither.
- "If the Odoo tools do not appear" and the guided route: synced plugins need a
  claude.ai sign-in in Claude Code 2.1.273 or later; `claude plugin configure`
  needs 2.1.285 or later and a restart, and its `unconfigured` list keeps the
  unused credential and the options with defaults on a working setup; the CLI
  fallback is offered for Cowork only (Claude chat has no safe place for the key);
  the container image is for Claude Code without Python. README Requirements: on
  Windows the session-start hooks need Git Bash.
- Clean-room rule (`CONTRIBUTING.md`, `NOTICE`): besides AGPL projects, no code from
  proprietary Odoo modules (OPL-1) or any license that does not allow
  redistribution under MIT; such projects may inform ideas from their public
  documentation only, and the plugin works with them only over the network.
- The container image pinned in `/odoo-tools:deploy-local` and `docs/install.md`
  is `ghcr.io/transgenia/odoo-mcp-tools:1.4.1`; `docs/packaging.md` now says to cut
  the release right after the merge, because the directory may publish the merge
  before the image exists.
- CI and the release workflow also lint `hooks/`, and the release zip ships
  `CONTRIBUTING.md`.

## [1.4.0] - 2026-09-29

### Added
- **Six Odoo Online tools** (`tools/online.py`, 28 tools in total). They work on
  any Odoo 10-19, over JSON-2, JSON-RPC and XML-RPC unless noted, and degrade
  per version:
  - `odoo_online_profile` (read): the series and line (`19.0`, `saas~19.2`),
    deployment with `deployment_confidence` (a `saas~` version proves Odoo
    Online, also on a custom domain; `*.odoo.com` alone may be Odoo.sh), the
    transport, `json2_available`, `doc_bearer`, `transport_notice`, when
    `/xmlrpc` and `/jsonrpc` disappear (Odoo 22; Odoo Online saas~21.1), the
    user and companies, 2FA, the user's API keys with `expires_in_hours` (names
    and dates only, never key material) and a hint when one expires within
    48 h, installed applications, imported data modules, Studio, and the Online
    limits (Custom plan, about 1 call/s, 5-200 e-mails/day, data modules only).
  - `odoo_api_catalog` (read): a model's methods with ordered parameter names
    and model-level/read-only flags, from Odoo's `/doc-bearer` on 19.0+ with an
    administrator's API key (ETag-cached, this model's exact names), else from
    the plugin's built-in table, filtered by series: the base definitions'
    names from saas~18.4 on (a model's override may rename a parameter, which
    the note says), and on 10.0 to saas~18.3 the flags only, with
    `parameters: null`, because names differ there (`name_search(args)`, the
    classic `web_read_group`, `default_get`/`write` overrides); `name_get` is
    listed up to 17.0. At most 100.
  - `odoo_access_check` (read): read/write/create/unlink for the signed-in user
    (`has_access` on 18+, record level with `ids`; `check_access_rights` on
    10-17) and `export_allowed` (`base.group_allow_export`, 16+).
  - `odoo_record_documents` (read): a record's attachments, its main attachment
    and an invoice's stored PDF (17+), which a plain attachment search hides;
    one file's content on request, only for an attachment of that record, up to
    `max_bytes` (default 1 MiB, at most 5 MiB). The way to get PDFs on 14+,
    where reports cannot be rendered over RPC.
  - `odoo_import_preview` (write, dry run; 16-19): Odoo's own importer with
    `dryrun=True`; returns the row errors and warnings and `would_import`,
    never the rolled-back ids, and removes its temporary wizard.
  - `odoo_import` (write): atomic `load()`; an `id` column upserts by external
    id. Both import tools take at most 500 rows, are refused in read-only mode,
    never run by themselves, and run on JSON-2 or JSON-RPC only (see below).
- `session.execute(..., transports=(...))` and `FallbackTransport.execute_kw(...,
  transports=...)`: a call limited to those transports is never sent or replayed
  over another one, and a `CompatError` says so when none is left. The import
  tools use it, so an import is never replayed over XML-RPC, whose marshaller
  cannot return the `None` values an import result carries (a saved import
  could otherwise be reported as a fault).
- `OdooSession.api_doc(model)`: `/doc-bearer` for tools, keeping the secret
  inside the session.
- **JSON-2 transport** (`transport/json2.py`): Odoo's new external API,
  `POST /json/2/<model>/<method>`, on saas~18.4 and 19.0+. It sends the API key
  as `Authorization: bearer`, the database as `X-Odoo-Database` and named
  arguments only (no cookies, no `Accept-Language`, no redirects). Positional
  arguments are named from a table of the base definitions of every method the
  plugin calls (`transport/json2_signatures.py`, keyed by series where the base
  names differ: `default_get`, `read_group`); other methods use
  `/doc-bearer/<model>.json` (19.0+, admin keys, cached with its `ETag`) or ask
  for named arguments. A model's override may use other names (saas~18.4:
  `write(values)` on `res.company`, `product.pricelist` and `mail.thread`
  models, `res.partner.default_get(default_fields)`; any addon on any series):
  Odoo then answers HTTP 422 from its `signature.bind` check before running the
  method (`Json2SignatureMismatch`), and the transport sends the call again with
  the signature from `/doc-bearer` or, when one argument was named, the name
  Odoo reports as missing, and remembers it per (database, model, method). When
  it cannot, `auto` sends that one call over JSON-RPC/XML-RPC (JSON-2 stays
  pinned) and `json2` asks for named `kwargs`. Names the caller gave in
  `kwargs` are never changed: the 422 is reported with a pointer to
  `odoo_api_catalog`.
  `create` with one dict still returns an id. Model and method names are checked
  before sending. The sign-in is `res.users.context_get` plus a read of the key
  owner's login, which must be `ODOO_LOGIN`.
- `ODOO_TRANSPORT_PREF=json2`, and a new `auto` policy based on the target's
  unclamped series, the credential kind and `user:pass@` in `ODOO_URL`:
  JSON-2 → JSON-RPC → XML-RPC on saas~18.4 / 19.0+ with an API key (JSON-2 is
  pinned after the first sign-in), JSON-RPC → XML-RPC as before elsewhere, and
  JSON-2 only from saas~21.1 (Odoo Online saas~21.1 and Odoo 22 remove the
  legacy endpoints; a password there is a `ConfigError` that says what to set).
  With `json2`, a server that does not answer JSON-2 gets "needs saas~18.4 /
  19.0 or newer, or a proxy blocks /json/2"; a host that cannot be reached at
  all (connection refused, DNS, TLS: `Json2Unreachable`) gets "check ODOO_URL
  and that this machine can reach it" instead.
- The version is detected without signing in and without a deprecated endpoint
  (`/web/webclient/version_info`, then `GET /json/version`, then
  `common.version`), so it leaves no warning in the Odoo 19 log, and it is
  fetched once per session.
- **Deprecation notice**: when the deprecated `/xmlrpc` or `/jsonrpc` is in use
  on Odoo 19+, the server logs one warning per session and `odoo_version` returns
  an additive `transport_notice` with the fix (create an API key, move gateway
  basic auth out of `ODOO_URL`, or set the transport back to `auto`).
  `/odoo-doctor` shows it.
- `odoo_execute` takes an optional top-level `ids` (the records of a record
  method): JSON-2 sends it as `ids`, the legacy transports as the first
  positional argument, so the same call works on every transport.
- `Credentials.secret_kind` (`api_key` or `password`), set from the settings;
  it is not part of the session fingerprint or of `repr()`.
- `compat/deltas.py` records method deltas (`METHOD_DELTAS`, with
  `resolve_method` and `method_available`): `formatted_read_group` from
  saas~18.4, classic `read_group` absent from saas~19.1, `check_access_rights`
  removed from saas~19.1, `has_access` from 18.0.
- An opt-in live test (`-m live`, `tests/test_json2_live.py`) compares the core
  read tools over JSON-2 and XML-RPC on a 19.0 sandbox (`odoo_version`,
  `odoo_fields_get`, `odoo_search`, `odoo_search_count`, `odoo_search_read`,
  `odoo_read`, `odoo_read_group`, `odoo_export_records_csv`, `odoo_list_models`,
  `odoo_module_info`, `odoo_translate_get` and two `odoo_execute` reads), checks a
  create/write/unlink round trip over JSON-2 against XML-RPC and Odoo's real
  signature-mismatch 422, and checks the transport choice on 18.0. Not compared:
  `odoo_report`, `odoo_export_records_json`, `odoo_connections`,
  `odoo_telemetry_preview` and the Online tools.
- `packages/`: an index of the packages related to odoo-tools, and a README for
  odoo-tools-lsp, Transgenia's language server for Odoo addons (proprietary, private
  preview; documentation only, no source in this repository).
- **Sandbox for Odoo Community 10.0 to 15.0** (was 16.0-19.0), for testing and
  migrations. Each series gets a PostgreSQL major it supports (10 for 10.0/11.0,
  12 for 12.0/13.0, 13 for 14.0/15.0, 16 for 16.0+); series up to 15.0 run as
  linux/amd64 (their official images are amd64-only; Docker Desktop emulates
  them, Docker Engine on ARM Linux needs binfmt/QEMU, which the script explains).
  The script warns that 10.0-16.0 no longer receive fixes from Odoo S.A. (it
  maintains the three latest series: 17.0, 18.0, 19.0).
- **Sandbox matrix workflow** (`sandbox-matrix.yml`): starts every series from
  10.0 to 19.0 with `deploy_local.py` and checks it through the plugin's own MCP
  server (`scripts/sandbox_smoke.py`: `odoo_version` + `odoo_search_read`). Runs
  on changes to the sandbox or the server, weekly, and on demand. The smoke test
  also checks the field entries of the cross-version table against the live
  instance, for every model it has.
- The image mirror also copies `odoo:10.0`-`15.0` and `postgres:10`, `12`, `13`.
- **Odoo Online series.** Version detection keeps the minor of a `saas~N.M`
  line (e.g. saas~18.1), which sits between two stable series
  (18.0 < saas~18.1 < … < 19.0). Field removals can now start on a saas line.

### Changed
- **`odoo_read_group` uses `formatted_read_group` from saas~18.4 on** (19.0
  deprecates the classic `read_group`, and Odoo Online saas~19.1 to saas~19.4
  do not have it), on every transport. The tool keeps its arguments and its
  classic output: the `<groupby>_count` / `__count` keys, `__domain`,
  `__context` for lazy grouping, date labels with `__range`, and `orderby`. A
  field without a default aggregator is listed in an additive `dropped_fields`
  instead of being silently ignored.
- `odoo_execute` says "(write operation)" and that read-only mode refuses it,
  and explains the `ids` + `kwargs` form.
- `READ_METHODS` (calls that may be retried on another transport) gains
  `formatted_read_group`, `web_read_group`, `context_get`, `has_access`,
  `has_groups` and `get_field_translations`.
- The MCP `instructions` list the two import tools among the write tools and
  point Odoo Online users to `odoo_online_profile`; the read-only refusal
  suggests read tools by name. Telemetry's `KNOWN_TOOLS` gains the six tools.
- Docs: a tool table in the README, Odoo Online routes in the guided route
  (`odoo-setup-mcp`: API keys on Online, verify, training exercise 8, daily
  use, deployment), the `odoo-mcp-tools` index skill, the `odoo` agent,
  `/odoo-doctor` (calls `odoo_online_profile`), `SECURITY.md` and
  `docs/compat-matrix.md` (an Odoo Online tools section).

### Fixed
- **Odoo Online detection used a substring of the URL** (code scanning
  alert): `https://example.com/?next=.odoo.com` counted as `*.odoo.com`.
  `detect_deployment` now compares the host name (`odoo.com` or a
  subdomain of it).
- **`odoo_read_group` on `formatted_read_group` (saas~18.4+) accepted a field
  spec with trailing text** (`amount:sum trailing`, `total:sum(amount)junk`,
  `amount:sum,tax:sum`) and silently dropped the rest, so a second aggregate
  or a typo vanished from the result. The whole spec must now be `field`,
  `field:agg` or `name:agg(field)`, else a `CompatError` before any call.
  The same check now runs on the classic `read_group` path from Odoo 17.0
  (the oldest series Odoo still supports), so 17.0-saas~18.3 refuse the same
  specs; 10-16 still pass the spec to Odoo as given.
- `docs/telemetry-schema.json` rejected payloads counting `odoo_telemetry_preview`
  or `odoo_read_group`, which the server already counts; its tool pattern now
  equals `KNOWN_TOOLS`, and a test keeps them equal.
- The `odoo` agent listed three tools twice.
- **HTTP 429 on `/jsonrpc` switched the session to XML-RPC** and replayed the
  call. A 429 is now `RateLimited` on every transport: reads wait for
  `Retry-After` (at most 30 s, 3 tries) and retry the same transport, writes are
  reported ("retry later"), and the transport is never switched.
- The sandbox talks to Odoo over XML-RPC (`/xmlrpc/2/common`, `/xmlrpc/2/db`)
  instead of `/jsonrpc`, which does not exist before Odoo 12.0.
- **`product.template.uom_po_id` was dropped from reads and exports on Odoo 17
  and 18**, where the field exists. It is gone only from saas~18.1 (Odoo
  Online) and 19.0.
- **`res.partner.company_type` was dropped on self-hosted Odoo 19.0**, where
  the field exists. It is gone only from saas~19.1 (Odoo Online). Both
  boundaries were checked against the public Odoo source of every stable and
  saas branch from 16.0 to saas-19.4, and `uom_po_id` on a live Odoo 18.0.
- `OdooSession.name_get` failed on Odoo 18+, where the `name_get` method no
  longer exists; it now reads `display_name`, which works on 10-19.
- The server reported the version of any older `odoo-mcp-tools` installed in
  the same Python instead of its own (seen as 1.1.0 while running 1.3.0).
  `odoo_mcp.__version__` is now the single runtime version and the release
  check keeps it equal to the manifests.
- **`odoo_version` reported success with a wrong API key or password** (edition
  "unknown" on Community; always on Enterprise, whose `+e` version string skips
  the module probe). The guided route and `/odoo-doctor` use it as the
  connection check, so a broken connection read as "already connected". It now
  signs in first, and the edition probe no longer swallows `AuthError`.
- `Credentials.secret` is left out of `repr()`, so a traceback, log line or
  debugger cannot show the API key or password.
- Docs, skill and agent no longer claim that `/jsonrpc` rejects API keys on
  Odoo 17+: Odoo handles both endpoints with the same `dispatch_rpc` (14-19)
  and a live Odoo 18.0 accepts an API key on both. The `auto` transport keeps
  its XML-RPC fallback for proxies that block or alter `/jsonrpc`. One place
  still says it: the verbatim telemetry consent statement in `/odoo-doctor`
  ("Odoo 17+ `/jsonrpc` API-key refusal handling"), left unchanged on purpose
  because a change to the consent wording needs the maintainers' review; the
  correction is pending that review.

### Notes
- Odoo 19 deprecates `/xmlrpc`, `/xmlrpc/2` and `/jsonrpc` and schedules their
  removal for Odoo 22 (they now live in the auto-installed `rpc` module); Odoo
  Online removes them in saas~21.1. With an API key the plugin now uses JSON-2
  there; a password keeps working on the legacy endpoints up to Odoo 21, with
  the notice above. The compat matrix and the cross-version skill say so.
- JSON-2 sends `@api.readonly` methods to a read-only cursor, which is a
  replica when the Odoo host sets `db_replica_host`: a read right after a write
  may lag there, and a client cannot force the primary.
- saas~18.4 was checked against the Odoo source only (no public image).

## [1.3.0] - 2026-09-27

Plug and play: one guided route, local infrastructure provided by Transgenia,
and the first published Release and package.

### Added
- **Guided route `/odoo-tools:odoo-setup-mcp` (start here).** Detects what is
  already set up, then walks the user through five phases: setup, verification,
  hands-on training (7 exercises, read-only first, writes only on a sandbox or
  test database), daily use (map of commands, skills and agents) and deployment
  to a team or production (least privilege, read-only by default, pilot,
  backups, updates). `/setup-odoo-tools` now opens the same route.
- **`/odoo-tools:deploy-local`** — local infrastructure, only when the user runs
  it and confirms (Docker required):
  - *Sandbox*: PostgreSQL 16 + Odoo **Community** 16.0, 17.0, 18.0 or 19.0 bound to
    `127.0.0.1`, with a database (demo data optional) ready for the plugin.
    `scripts/deploy_local.py` (standard library only) generates the passwords
    locally into `~/.odoo-tools/sandbox/.env` (owner-only), never prints them,
    and offers `status`, `down`, `logs` and `destroy --yes`. Transgenia cannot
    provide Odoo Enterprise or Odoo Online instances (Enterprise is licensed by
    Odoo S.A., Online is its SaaS); the plugin connects to the user's own.
  - *Container*: the MCP server as `ghcr.io/transgenia/odoo-mcp-tools`, for
    machines without Python 3.9+, connected to an existing Odoo.
- **Images served by Transgenia.** The release publishes the MCP server image to
  GHCR (`X.Y.Z`, `X.Y`, `latest`; amd64 + arm64). `mirror-images.yml` copies the
  official `odoo` (16.0-19.0) and `postgres:16` images to `ghcr.io/transgenia`
  and refreshes them weekly; the sandbox uses them and falls back to Docker Hub.
- **MCP server `instructions`**: sent at `initialize`, so every session knows the
  guided route, the safe-use rules (confirm before any write) and when to point
  the user to Transgenia.
- **Transgenia support channels** at the points where they help: setup blocked
  (`/odoo-doctor`, connection errors), end of training, end of the sandbox and
  deployment phases, `SUPPORT.md` and the README: **dev@transgenia.org** and
  WhatsApp **+52 55 8034 0405** (https://wa.me/525580340405). They are not
  appended to unrelated answers.

### Changed
- Connection errors (incomplete credentials, authentication, transport) now end
  with the setup entry point and the support channels.
- `release.yml`: checks that the tag matches `plugin.json`, `marketplace.json`,
  `pyproject.toml` and the CHANGELOG; builds from the tag on manual runs (it
  built from the default branch); uses only this version's CHANGELOG section as
  release notes (it used the whole file); the plugin zip now includes
  `scripts/`, `docker/` and `SUPPORT.md`.
- PyPI publishing and the image mirror now run inside `release.yml`
  (`publish.yml` removed): a Release created with `GITHUB_TOKEN` triggers no
  other workflow, so `publish.yml` would never have run. The PyPI trusted
  publisher must name workflow `release.yml` and environment `pypi`.
- CI lints `scripts/` too.
- `release.yml` can be started from Actions → Run workflow on `main`: it creates the tag when missing.
- README badges for Claude Code / Claude AI and Odoo ERP (10-19, CE/EE/Online); `claude*` and `odoo-*` keywords in the plugin and marketplace manifests.

## [1.2.0] - 2026-09-27

Directory-submission follow-up: fixes the findings the Claude plugin directory
reported on v1.1.0.

- **Package registry redirected** (blocking) — `UV_PROJECT_ENVIRONMENT` is gone
  from the MCP server environment.
- **Runs a pinned npx or uvx package** — no package launcher: the server runs
  from the source bundled in the plugin.
- **MCP server command wasn't read** — the command is now `python3` plus a file
  under `${CLAUDE_PLUGIN_ROOT}`.
- **Uses a credential from the user's machine** (2 findings) — the SessionStart
  hook no longer reads the API key option.
- **Contains a download-and-run command** (`security.yml`) — gitleaks is built
  with `go install` instead of downloaded with `curl` and executed.

### Changed
- **The MCP server runs with `python3` (3.9+) instead of `uv`.** `plugin.json`
  starts `python3 ${CLAUDE_PLUGIN_ROOT}/server/run_stdio.py`; nothing is
  installed or downloaded when the plugin starts. **Migration:** `uv` is no
  longer needed, but a Python 3.9+ `python3` must be on `PATH`. On Windows that
  means the Microsoft Store Python, or a `python3.exe` added next to a
  python.org `python.exe` (see the README "Requirements").
- MCP stdio protocol implemented on the Python standard library (was the `mcp`
  SDK + `anyio`): `initialize` with version negotiation (2025-06-18,
  2025-03-26, 2024-11-05), `ping`, `tools/list` (with `readOnlyHint`
  annotations), `tools/call` (tool failures as `isError` results; unknown tool
  → JSON-RPC `-32602`), `notifications/cancelled` and batches. Tool calls run
  in arrival order on one worker thread; stray `print()` output goes to stderr.
- JSON-RPC transport uses `urllib` instead of `httpx`. Both transports share a
  certificate-verifying TLS context (system trust store and `SSL_CERT_FILE`,
  plus `certifi` when it happens to be installed).
- No runtime dependencies (`mcp` and `httpx` dropped); `requires-python` is now
  `>=3.9` (was `>=3.11`). The `dev` extra adds `mcp` (Python 3.10+) only for an
  interop test.
- SessionStart hook reads no plugin option at all: it runs `python3 --version`
  and prints a warning only when `python3` is not runnable.
- Default `ODOO_TIMEOUT` raised from 30 to 120 s (Odoo's default
  `limit_time_real`), and exposed as the **Request timeout** plugin option.
- In `auto` transport mode a write (`create`, `write`, any non-read
  `execute_kw`) is replayed over XML-RPC only when the JSON-RPC request certainly
  never reached Odoo (connection/TLS failure, HTTP 3xx/4xx). After a timeout,
  HTTP 5xx or a garbled 2xx reply the error is raised instead ("may or may not
  have been applied"), because the call may already have committed.
  `version`, `authenticate` and read methods (`search_read`, `read`, ...) still
  fall back; once JSON-RPC fails where XML-RPC works, XML-RPC is pinned for the
  session. A forced `jsonrpc` preference is never switched to XML-RPC.
- JSON-RPC no longer follows HTTP redirects (a redirected POST used to become a
  body-less GET whose reply was taken as the result), asks for gzip, and maps
  `http.client` protocol errors to transport errors.
- `odoo-setup-cli` creates the `.env` owner-only with placeholders and tells the
  user to paste the secret themselves; Claude never handles it. Docker examples
  use `--env-file` / `env_file:` instead of host environment variables.
- The leak-guard's organisation-specific markers moved to the
  `LEAK_GUARD_PATTERNS` repository secret (the plugin folder is the repository
  root, so the workflow file ships to every installer).
- CI secret scan: gitleaks v8.18.4 built with `go install` at a fixed tag
  (modules verified against the Go checksum database) instead of a `curl`
  download of the release binary.
- CI tests Python 3.9, 3.11, 3.12 and 3.13.

### Added
- `server/run_stdio.py` entry point (standard library only): puts the bundled
  `src` first on `sys.path`, so another installed `odoo_mcp` cannot shadow the
  shipped code, and exits with a clear message on Python < 3.9.
- Tests for the stdio protocol, argument validation, hostile input, the entry
  point under `python -S`, the `urllib` transport (basic auth, redirects, gzip,
  cut replies), fallback replay rules, the Community deadlock, TLS bundle
  fallback, the XML-RPC timeout, and interop with the official MCP client
  (dev-only, skipped when `mcp` is not installed).

### Fixed
- **Five of the six skills never loaded**: `skills/SKILL.md` sat directly in
  `skills/`, so Claude Code treated the folder as one skill and ignored its
  subfolders (`/odoo-tools:odoo-setup-mcp` and others did not exist). Moved to
  `skills/odoo-mcp-tools/SKILL.md`; all 9 skills and commands now load.
- **Deadlock on Community instances**: `OdooSession.facts()` held a
  non-reentrant lock while the edition probe authenticated through the same
  lock, hanging `odoo_version` (and every tool after it) on a cold session
  whenever the version string has no `+e`. The lock is now reentrant.
- Tool arguments are validated against each tool's input schema again (the MCP
  SDK used to do it): wrong types, missing required or misnamed properties are
  refused with `Input validation error: ...` before anything reaches Odoo.
- A malformed message (invalid id, unhashable `requestId`, deeply nested JSON,
  lone surrogates) can no longer stop the server; unexpected failures answer
  JSON-RPC `-32603` instead of leaving the request unanswered. Batched tool
  calls now run on the worker thread like single ones.
- `ODOO_URL` with `user:pass@` (HTTP basic auth in front of Odoo): JSON-RPC now
  sends it as an `Authorization` header, and neither transport's errors nor the
  startup log echo the password.
- HTTPS on Python builds without a CA file of their own (python.org macOS
  installers before "Install Certificates"): the OS CA bundle is loaded.
- The XML-RPC transport now honours `ODOO_TIMEOUT`; before, an unresponsive
  Odoo could block an XML-RPC call indefinitely. XML-RPC protocol errors
  (HTTP 5xx from a proxy, malformed replies) are reported as transport errors.

### Removed
- `server/uv.lock` (nothing to lock without runtime dependencies).

## [1.1.0] - 2026-09-25

Directory-submission hardening (Claude plugin directory lints and policy holds).

### Changed
- **Credentials are now plugin options (`userConfig`)** instead of shell
  environment variables read from the user's machine. URL, database and login
  are regular options; the API key and password are `sensitive` (masked input,
  OS secure credential store). Set them in `/plugin` → **odoo-tools** →
  **Configure options**. **Migration:** users who exported `ODOO_*` in their
  shell profile must enter the values once in the plugin options; the
  standalone server (Docker / `python -m odoo_mcp`) still reads `ODOO_*` env.
- The MCP server now runs the bundled source with dependencies pinned by the new
  `server/uv.lock` (`uv run --frozen`, venv under `${CLAUDE_PLUGIN_DATA}`),
  instead of an unpinned `uvx --from` resolution.
- SessionStart hook reads `CLAUDE_PLUGIN_OPTION_*` instead of `ODOO_*` env.
- New optional **Read-only mode** plugin option (maps to `ODOO_READONLY`).

### Added
- `PRIVACY.md` and a README "Privacy" section listing every service contacted.
- `.claude-plugin/icon.svg` and `displayName` ("Odoo Tools").
- Config treats unresolved `${...}` placeholders as unset, so an empty optional
  plugin option can never be used as a literal URL or credential.

### Fixed
- `plugin.json` no longer re-lists `hooks/hooks.json` (it is always loaded;
  listing it caused a duplicate-hooks load error).
- `marketplace.json` entry version now matches `plugin.json`.
- The release zip now ships `server/` (the MCP server the manifest launches)
  and `PRIVACY.md`.
- CI secret scan: replaced `gitleaks/gitleaks-action@v2` (requires a paid
  `GITLEAKS_LICENSE` for organization repos, so the job failed before scanning)
  with the free gitleaks CLI v8.18.4, pinned by version and SHA-256.

## [1.0.0] - 2026-09-20

First public release — the **Standard** package (free, MIT, public).
See [`docs/packaging.md`](docs/packaging.md) for the tier plan
(Standard now; Enterprise/Teams later, in separate packages).

### Added
- `odoo_telemetry_preview` read-only tool (21 tools total): renders the exact
  opt-in telemetry payload for human review, backed by server-side counters.
  Telemetry stays default-off, exact-token (`ODOO_TELEMETRY=opt-in`), PII-free
  by allowlist, with no schedules or background sends.
- `odoo_read_group` (22 tools total): server-side GROUP BY aggregation via
  classic `read_group` (Odoo 10-19), through the compat layer.
- `ODOO_READONLY=1` kill-switch: refuses every non-read-only tool centrally
  before touching Odoo (demos, safe exploration).
- Release flow (`.github/workflows/release.yml`): tag `v*` builds and verifies
  the Standard artifacts (PyPI sdist/wheel + plugin zip) and creates the
  GitHub Release; the existing `publish.yml` then publishes to PyPI.
- `docs/telemetry-schema.json` + `docs/telemetry-report-template.md`
  (synthetic example only — real user data never lives in this repo).

### Fixed (Codex review followups, PRs #6/#7)
- v10 automations link via legacy `server_action_ids`; orphan-cleanup message
  now reports accurately when the compensating unlink fails.
- safe_eval guard allows subscript stores on plain locals (`STORE_SUBSCR` is
  safe server-side) while still rejecting attribute assignment and `del`.
- Schema-cache invalidation is race-safe via per-model generations.
- CLI accepts `ODOO_PASSWORD` for Odoo < 14 (incl. 10-12); setup skill updated.
- Telemetry hardening: exact `opt-in` token only, allowlisted transport labels,
  version derived from package metadata, claims scoped vs Metrics/OTLP.

## [0.1.0] - 2026-09-17

### Added
- Clean-room MIT MCP server (`server/`, package `odoo-mcp-tools`) with 20 generic
  Odoo tools (search/read/search_read/search_count/create/write/unlink/execute,
  fields_get/list_models/module_info, export JSON/CSV, translate get/set, report,
  version, connections).
- Studio-style low-code tools (CE & EE, no Studio app): `odoo_add_field` (manual
  `x_` custom fields) and `odoo_add_automation` (safe_eval-validated automated
  actions, version-introspective over `base.automation`). Skill
  `odoo-studio-style` + doc `docs/odoo-studio-parity.md` explain the parity and
  the safe_eval caveat (esp. Odoo online/SaaS).
- Transport layer: XML-RPC, JSON-RPC, and an auto-fallback that handles the
  Odoo 17+ `/jsonrpc` API-key rejection transparently.
- Cross-version compatibility layer (Odoo 10-19): version/edition/deployment
  detection + declarative delta map + name/field/capability resolution.
- In-process TTL schema cache; optional Prometheus metrics and OTLP tracing.
- Claude plugin packaging: `plugin.json`, self-hosted `marketplace.json`, agents
  (`odoo`, `odoo-migrator`), skills (setup-mcp, setup-cli, connect, crossversion),
  commands (doctor, export), SessionStart hook.
- CLI fallback and Odoo domain context reused from the MIT `odoo-agent` project.
- CI (ruff + pytest on py3.11/3.12, CLI build), opt-in live Odoo version matrix,
  PyPI publish workflow, Docker image.

[1.2.0]: https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/releases/tag/v1.2.0
[1.1.0]: https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/releases/tag/v1.1.0
[1.0.0]: https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/releases/tag/v1.0.0
[0.1.0]: https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/releases/tag/v0.1.0
