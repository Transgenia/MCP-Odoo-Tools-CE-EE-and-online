# Security policy

## Credentials

- Odoo credentials are read from the server's environment (`ODOO_URL`,
  `ODOO_DB`, `ODOO_LOGIN`, `ODOO_API_KEY`/`ODOO_PASSWORD`), which Claude Code
  fills from the plugin options. The server never takes an Odoo URL or secret
  from a client request: the header-based multi-tenant path was removed in
  1.5.0, and `ODOO_MULTITENANT` is parsed but reserved. The server reads no
  other credential: `ODOO_HTTP_BEARER`, which it read from its environment but
  never used, was removed in 1.5.1.
- The **MCP server** does not persist secrets to disk and never writes them to
  logs. Sessions are keyed by `url|db|login` plus a per-process HMAC of the
  secret; the secret itself is never part of a key or a log line.
- **Exception, the CLI fallback:** `/odoo-tools:odoo-setup-cli` writes a local `.env`
  containing your credentials under `~/.claude/tools/odoo-cli`. If you use that
  surface, restrict its permissions (e.g. `chmod 600`), keep it out of version
  control, and delete it when you stop using the CLI.
- **Data path when used via an AI agent:** tool results (the Odoo records you
  query) are returned to your MCP client and sent to your model provider (e.g.
  Anthropic, for Claude) for processing, as with any MCP tool. Transgenia does not
  proxy or store your data, but it is not withheld from the model: query with a
  least-privilege user and avoid pulling fields the agent does not need.
- The `Settings` object **redacts credentials in `repr()`/`str()`** so accidental
  logging cannot leak them (enforced by `tests/test_security_redaction.py`).
- Prefer **API keys** (Odoo ≥ 14) over passwords. Use least-privilege Odoo users.

## Supply chain

- **Zero runtime dependencies.** The MCP stdio protocol and both Odoo
  transports are implemented on the Python standard library.
- **Nothing is installed or downloaded when the plugin starts.** Claude Code
  runs `python3 ${CLAUDE_PLUGIN_ROOT}/server/run_stdio.py`: no package launcher,
  no lockfile install, no code fetched at run time.
- **Readable source only.** What runs is the plain Python under `server/` as
  shipped in the plugin; nothing compiled, packed or minified. `run_stdio.py`
  puts the bundled `server/src` first on `sys.path`, so another `odoo_mcp`
  package installed on the machine cannot shadow it.
- The optional extras (`cachetools`, `prometheus-client`, OpenTelemetry) are
  used only if you install them yourself; the server degrades gracefully
  without them and the plugin never installs them.
- The optional CLI fallback is the one exception: `/odoo-tools:odoo-setup-cli`
  runs `npm install` against the npm registry, only when you invoke it.

## What the plugin directory's checks report

The Claude plugin directory lists these findings for this plugin. Each one, and
where to verify it:

- **Uses a credential from the user's machine** (`.claude-plugin/plugin.json`,
  `server/src/odoo_mcp/config.py`). The MCP server reads two credentials, the
  Odoo API key and the Odoo password, from the environment that
  `.claude-plugin/plugin.json` fills from the `sensitive` options `odoo_api_key`
  and `odoo_password` (`${user_config.KEY}`). It sends them only to the Odoo URL
  the user configured, the service they belong to: the three transports in
  `server/src/odoo_mcp/transport/` connect to that URL only and refuse
  redirects. `server/tests/test_product_rules.py` fails if the server reads any
  other credential from its environment.
- **`scripts/deploy_local.py`** generates random passwords
  (`secrets.token_urlsafe`) for the local Docker sandbox of
  `/odoo-tools:deploy-local`, keeps them in an owner-only `.env` in the sandbox
  folder, and uses them only with that sandbox's containers on 127.0.0.1. They are
  not the user's credentials.
- **Tests** (`server/tests/`) set fake canary credentials to prove that no log
  line, audit line, diagnostics record, support report or hook output ever
  contains a credential. The plugin never runs them.
- **Uses hooks.** One SessionStart hook, `hooks/session_start.py`, which reads
  the plugin's data folder and `CLAUDE_CODE_ENTRYPOINT` only, never a plugin
  option or a credential (`server/tests/test_product_rules.py`), and always
  exits 0.
- **Runs a local program for an MCP server.** `python3
  ${CLAUDE_PLUGIN_ROOT}/server/run_stdio.py`: standard library only, nothing
  installed or downloaded (Supply chain, above).
- **Contains a download-and-run command.** Only in documentation and in CI
  workflows, which never run on the user's computer: the desktop extension
  preview validates its manifest with the official MCPB command line tool at a
  pinned version.

## Automated checks (CI)

- **`.github/workflows/security.yml`** runs on every push/PR:
  - **gitleaks** scans history and diffs for committed secrets. The CLI is
    built with `go install` at a fixed tag (v8.18.4), with modules verified
    against the Go checksum database; no binary is downloaded and executed.
  - **leak-guard** greps the tree for forbidden internal/tenant markers
    (client data, infra hosts, fiscal IDs, hardcoded credentials) and fails the
    build if any appear. This repo is vendor-neutral: it must contain only the
    generic tooling plus the public author/brand and services offer. The
    organisation-specific markers are read from the `LEAK_GUARD_PATTERNS`
    repository secret rather than written in the workflow, because the plugin
    folder is the repository root and ships to every installer; matches on
    those markers are reported by file name only.
- **`.gitignore`** excludes `.env`, `*.env`, virtualenvs and build output so
  local credentials cannot be committed by accident.

## Opt-in telemetry (disabled by default)

- **Default: off.** Nothing is collected or sent unless the operator sets
  `ODOO_TELEMETRY=opt-in` explicitly. Unset/any other value = disabled.
  There is **no scheduler, no cron/4am job, no boot/startup hook, no background
  thread and no network send** in the telemetry path. Sharing happens only when
  a human runs `/odoo-doctor`, reads the exact payload on screen, and decides
  to paste it somewhere.
- **What is sent (allowlist only):** `plugin_version`, `odoo_version_major`
  (10-19), `odoo_edition` (`community`/`enterprise`/`unknown`),
  `odoo_deployment` (`onprem`/`saas`/`unknown`), `transport` label,
  `tool_calls_total` and `tool_calls_by_tool` (counters keyed by generic tool
  name only, e.g. `odoo_search_read`). Enforced in code by
  `server/src/odoo_mcp/telemetry.py` (`ALLOWED_KEYS`, `assert_no_pii`) and
  covered by `server/tests/test_telemetry_optin.py`.
- **Purpose:** continuous improvement of the plugin only (which versions and
  transports are actually used, which generic tools get exercised) so compat
  fixes and docs target real usage instead of guesses.
- **Frequency:** only on explicit manual run; there is no periodic send. Each
  share is a deliberate, visible operator action.
- **NEVER sent, even under opt-in:** URL, DB name, login/email, secrets, phone,
  company/customer names, record contents, domains/ids/values, module lists,
  revenues/billing, file paths, hostnames. The payload builder rejects unknown
  tool keys and anything resembling an email/URL/secret.
- **How to enable:** `export ODOO_TELEMETRY=opt-in` (same process env as the
  other `ODOO_*` vars), then run `/odoo-doctor` and review the payload block.
- **How to disable:** `unset ODOO_TELEMETRY` (or any value other than `opt-in`)
  and restart the server. Disabling is immediate; no residual timers exist.
- **Scope note:** these guarantees cover the manually shared telemetry payload.
  The pre-existing observability surface (`ODOO_METRICS`, `ODOO_OTEL_ENDPOINT`)
  is a separate explicit opt-in: when enabled it runs a local Prometheus
  endpoint and/or background OTLP span export as documented in `README.md`.
  With both unset (the default), the server performs no background export of
  any kind.

## Transport

- Use HTTPS Odoo URLs. JSON-2, JSON-RPC and XML-RPC all run over the URL you
  provide; a plain `http://` URL is sent unencrypted.
- **JSON-2** (Odoo saas~18.4 / 19.0+) sends the API key as
  `Authorization: bearer` on each request, never on a redirect (redirects are
  refused), sends no cookies, and never shows Odoo's server traceback (the
  `debug` field of an error) in a tool result. It accepts API keys only, so a
  password configuration keeps the legacy endpoints.
- **TLS is always verified.** All transports share one certificate-verifying
  context (hostname checked) built from the system trust store, honouring
  `SSL_CERT_FILE`, plus the `certifi` bundle when that package is already
  installed. There is no option to turn verification off. If your Python has no
  usable trust store, point `SSL_CERT_FILE` at a CA bundle.
- **Basic auth in front of Odoo.** `ODOO_URL` may carry `user:pass@`; JSON-RPC
  sends it as an `Authorization` header (never on a redirect, which is refused
  anyway) and no error, log line or tool result echoes the password (the
  `odoo_connections` tool strips the `user:pass@` from the URL it reports). JSON-2 needs that same
  header for its API key, so such a URL stays on the legacy endpoints (and
  cannot work from Odoo 22 / Odoo Online saas~21.1, where they are removed). Note that **Odoo URL**
  is not a `sensitive` plugin option: a password embedded there is stored in the
  plugin settings, not in the OS credential store.
- **Timeouts.** Every JSON-2, JSON-RPC and XML-RPC request is bounded by `ODOO_TIMEOUT`
  (seconds, default 120, Odoo's own default request limit; plugin option
  **Request timeout**), so an unresponsive Odoo cannot hang the server
  (XML-RPC ignored the timeout before 1.2.0).
- The server logs to stderr only; stdout is reserved for the MCP channel, and
  stray `print()` output is redirected to stderr.
- **Audit trail (1.5.0).** Every tool call, refusals included, leaves one JSON line:
  the tool, the model and operation names it touched (`op:model[:method]`), the
  layer and rule of a refusal, counts, the duration, the exception class name of an
  error and the policy digest. It never holds argument values, domains, field
  values, ids, file contents, the URL, tokens, keys, passwords or error message
  texts; a name that fails the policy's name check is written as `?`. The Odoo
  database and login appear only on the `start` line written when the server
  starts. The plugin writes daily files (`odoo-tools-audit-YYYY-MM-DD.jsonl`) to
  its data folder (`ODOO_AUDIT_DIR`), owner-only (0700 folder, 0600 files, never
  through a symlink), kept 90 days (`ODOO_AUDIT_RETENTION_DAYS`, 0 keeps them).
  Without a folder the lines go to the `odoo_mcp.audit` logger on stderr;
  `ODOO_AUDIT_DIR=off` writes none. Each line carries a hash of the previous one,
  and `python3 server/run_stdio.py --verify-audit FILE` names the first line that
  was edited, reordered or inserted, or an incomplete final line. It cannot, from
  one file alone, detect whole trailing lines removed from a day or a deleted day
  file (the surviving prefix still chains). Locally this is evidence, not
  prevention anyway: whoever can write the folder can rewrite the files. A
  failure to write never breaks a tool call.

## Permission policy (1.5.0)

In the local (stdio) mode the permission policy limits what Claude can do
**through the odoo-tools MCP tools**. It protects against mistakes and against
instructions hidden in data Claude reads. It does not limit the person who holds
the API key, and it is not a sandbox for an agent that has unrestricted shell
access on the same machine. The boundary that holds against everyone is the Odoo
user itself: give the agent a dedicated, least-privilege Odoo user (not an
administrator) and an API key with an expiry. In a future remote mode, where the
server keeps the Odoo credential, the same policy becomes real enforcement.

- **What it is.** A ceiling on top of Odoo's access rights, record rules and
  field groups, set by the plugin options **Permission profile** (`readonly`,
  `standard` by default, `builder`, `full`) and an optional **Permission policy
  file** read once at start from an explicit absolute path (never from a default
  location). It never grants what Odoo refuses and is never weaker than
  Read-only mode. `full` keeps the 1.4 behaviour; reference:
  [`docs/policy.md`](docs/policy.md).
- **What `standard` closes.** Stored secrets (system parameters, mail-server,
  LDAP and payment-provider credentials, IAP and bank-sync tokens, CFDI
  certificates and keys, the outgoing mail queue) cannot be read; users, groups,
  access rules, modules, bank accounts, partner merges, chatter history and
  fiscal sequences are read-only; models that send e-mail, SMS, letters or share
  links, and the outbound methods (`message_post` except internal notes,
  `message_subscribe`, `send_mail`, ...), are closed; server actions,
  automations, views and other `ir.*` records are read-only; deletes are
  refused; credential-like fields are withheld from reads and refused in
  arguments. `full` still refuses creating, changing or revoking API keys and
  uninstalling modules, and, to enforce that, a call whose arguments or related
  models the policy cannot check.
- **Two layers.** The declared accesses of each tool are decided from its
  arguments before any session exists (nothing reaches Odoo). Then every Odoo call
  the tool makes goes through a guarded session that checks it again with its
  values and paths (x2many commands, domain and export paths, the parent of an
  attachment, a user's contact e-mail) before it is sent, and stops as a bug any
  call the tool did not declare. A tool without a permission mapping cannot be
  registered, listed or called.
- **An invalid policy locks the server**: only `odoo_version` works, and it
  explains the error without contacting Odoo.
- **Seatbelt, not sandbox.** In stdio an agent with an unrestricted shell can
  read the server's environment, edit the policy file or the plugin options, or
  call Odoo directly. Claude Code `permissions.deny` rules on the policy folder,
  Bash approval prompts and the instructions line (a policy refusal is final)
  make that harder, not impossible. `odoo_version` warns when the Odoo user is an
  administrator, since Odoo then narrows nothing.
- **Known limits** (documented in `docs/policy.md`): side effects inside
  business methods (a confirmation e-mail, existing automations) are Odoo's;
  strings returned by methods (a portal URL with a token) are not redacted;
  pointer models other than `ir.attachment` matter only once a file refuses
  business reads; related fields with harmless names can carry withheld data;
  many2one links are not checked as touches; published content is an outbound
  channel by effect; counts and aggregates allow inference; `builder` equals
  `full` for confidentiality, because automations run code on the server; on
  Odoo 10 to 12, the keys other than `default_<field>` of an object passed
  positionally to a business method outside the policy's table are not held to
  the context allowlist (planned for 1.5.2).

## Read-only mode

- Set `ODOO_READONLY=1` for demos or safe exploration: the server no longer
  lists the non-read-only tools (`odoo_create/write/unlink/execute`,
  `odoo_translate_set`, both Studio tools, and both import tools:
  `odoo_import_preview` too, because its rolled-back dry run can still consume
  sequence numbers and fire webhooks), and refuses them with a clear error before
  touching Odoo when one is called by name. Reads, exports,
  `odoo_telemetry_preview` and the read-only Online tools (`odoo_online_profile`,
  `odoo_api_catalog`, `odoo_access_check`, `odoo_record_documents`) keep
  working. No permission profile or policy file can bring a write back while it
  is on. Unset + restart to re-enable writes. (The CLI fallback has no
  equivalent gate, nor a permission policy: its `write` command always attempts
  the RPC. Use a least-privilege Odoo user there.)
- `odoo_online_profile` lists the user's API keys by name, scope and dates
  only: Odoo keeps no key material in a readable field, and the plugin never
  mints, rotates or revokes keys. `odoo_record_documents` returns a file only
  for an attachment of the record asked for, and only up to `max_bytes` (at
  most 5 MiB).

## Reporting a vulnerability

Email **dev@transgenia.org** with details and reproduction steps. Please do not
open public issues for security reports. We aim to acknowledge within 5 business
days.
