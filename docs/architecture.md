# Architecture

```
Claude (MCP client)
      │  stdio (JSON-RPC MCP)
      ▼
odoo_mcp.server  ──lists/dispatches──▶  registry (ToolRegistry, Access per tool)
      │   policy/check.py: Layer A,          │
      │   before any session                 ▼
      │                              tools/ (crud, meta, export, i18n, report, studio, online)
      │                                     │  resolve_model / resolve_fields
      │                                     ▼
      │                              compat/ (detect → deltas → resolve)
      │                                     │  ctx.session
      ▼                                     ▼
tenancy.ConnectionManager ──▶ policy/guard.GuardedSession (Layer B: every Odoo call)
   (per-tenant)                             │
                                            ▼
                              session.OdooSession ──▶ transport/
                              (auth, facts, cache)     fallback → json2 | jsonrpc | xmlrpc
                                                              │
                                                              ▼
                                                        Odoo instance
audit.py: one line per tool call (refusals included), local files or stderr
```

## Layers

- **transport/** — `Json2Transport` (`urllib`, `POST /json/2/<model>/<method>`
  with a bearer API key; positional arguments named from
  `json2_signatures.py`, or from `/doc-bearer` for other methods, and
  corrected once when Odoo's bind check refuses a model override's names),
  `JsonRpcTransport` (`urllib`), `XmlRpcTransport` (`xmlrpc.client`), and
  `FallbackTransport`, which picks the order from the unclamped series, the
  credential kind and `user:pass@` in the URL (auto: JSON-2 → JSON-RPC → XML-RPC
  on saas~18.4 / 19.0+ with an API key, JSON-RPC → XML-RPC elsewhere; JSON-2 only
  from saas~21.1), detects the version without a login or a deprecated endpoint,
  pins the transport that answers after a failure (and JSON-2 after its first
  sign-in) and warns once. A write (any call that is not a read method) moves to
  the next transport only when the request certainly never reached Odoo; after
  a timeout, HTTP 5xx or garbled reply the error is raised instead. HTTP 429 is
  `RateLimited`: reads wait for `Retry-After` on the same transport, writes are
  reported. On Odoo 19+ with a legacy transport it exposes `transport_notice`.
  All share a certificate-verifying TLS context (`base.tls_context()`) and
  honour `ODOO_TIMEOUT`.
- **session.py** — `OdooSession` holds credentials, lazily authenticates (uid),
  caches version/edition/deployment facts, and wraps schema reads through the
  TTL `SchemaCache`. `ConnectionManager` (tenancy.py) maps a session key
  (`Credentials.session_key()`: `url|db|login`, the credential kind and a
  per-process HMAC of the secret, never the secret itself) to a session.
- **compat/** — `detect.probe()` builds `EnvFacts`; `deltas.py` is the
  declarative delta map; `resolve.py` turns a requested model/field/capability
  into what exists on the target. Every tool calls `resolve_*` before the ORM.
- **tools/** — thin handlers registered on the shared `registry`. Write tools are
  flagged `read_only=False`: `ODOO_READONLY=1` hides them and refuses them in
  `server.py` before any session exists. Each tool also declares what it touches
  (`access=`), for the permission policy below. The public core has a
  declarative permission policy; approval workflows stay out (they belong to a
  private governance layer). `tools/online.py` holds the Odoo
  Online tools. Its two import tools pass `transports=("json2", "jsonrpc")` to
  `session.execute`, and the fallback never sends or replays such a call over
  XML-RPC, whose marshaller cannot return the `None` values an import result
  carries. `session.api_doc(model)` serves `/doc-bearer` without handing the
  secret to a tool.
- **policy/**: the permission policy ([`policy.md`](policy.md)): the tier data
  (`tiers.py`), method classes and argument shapes (`classify.py`), profiles,
  rules and `Policy.decide()` (`model.py`), the loader of the options and the
  file with its E-codes and warnings (`loader.py`), Layer A (`check.py`), the
  guarded session of Layer B (`guard.py`), the texts the agent sees
  (`texts.py`) and `--check-policy` (`cli.py`). Everything except the guard is
  pure: no Odoo call and no I/O except reading the policy file once at start.
- **audit.py**: one hash-chained JSON line per tool call, refusals included,
  with names and counts only, to daily owner-only files (`ODOO_AUDIT_DIR`), to
  stderr, or nowhere (`off`). `--verify-audit FILE` checks a file's chain.
- **observability.py** — optional Prometheus metrics and OTLP tracing, both
  off by default and no-ops when the extras are absent.
- **server.py / __main__.py / run_stdio.py** — the MCP stdio protocol,
  implemented on the Python standard library (no MCP SDK): newline-delimited
  JSON-RPC 2.0 with `initialize` (protocol version negotiation), `ping`,
  `tools/list` (`readOnlyHint` annotations from each tool's `read_only` flag),
  `tools/call`, `notifications/cancelled` and batches. `run_stdio.py` is what
  the plugin runs (bundled `src` first on `sys.path`); `odoo-mcp` /
  `python -m odoo_mcp` are the installed entry points, and also run the
  offline checks `--check-policy FILE` and `--verify-audit FILE`. Tool calls run in arrival
  order on **one worker thread**, so the reader keeps answering `ping` and
  honouring cancellations while Odoo works, and sessions/transports never see
  concurrent use. Tool failures come back as `isError` results; an unknown tool
  is a JSON-RPC `-32602` error. Logs go to stderr; stdout is the MCP channel
  only (stray `print()` output is redirected to stderr).

## Order of checks on a tool call

1. `check_readonly` (unchanged): with `ODOO_READONLY=1` a write tool is refused,
   whatever its arguments.
2. `Policy.check_tool`: a locked policy, a tool without a mapping, a disabled
   tool, or one the profile forbids on every model is refused. These are the
   tools `tools/list` hides.
3. The arguments are validated against the tool's input schema.
4. Layer A (`Policy.check`): the declared touches, the name checks, NEVER, the
   withheld field names, the `ir.attachment` pin, the internal-note rule and the
   context keys, all from the arguments. A refusal here never signs in and is not
   counted as a tool call.
5. The handler runs with `GuardedSession` (Layer B): each Odoo call is checked
   again on the actual model and method, with its values and paths (x2many
   commands, field paths, attachments, identity, delegation links), against the
   tool's declared touches or one of its internal calls and their predicates,
   before the transport is touched. Read results lose withheld fields
   (`policy_withheld_fields`).
6. The audit writes one line for the call, whatever the outcome.

## Transports & modes

- **stdio (default):** single-tenant, credentials from environment. This is the
  mode the plugin's `mcpServers` entry uses.
- **HTTP (roadmap, not built):** a remote mode where the server keeps the Odoo
  credential and resolves a session from an authenticated identity. It needs
  its own design. The header-based `tenancy.from_headers` (client-chosen
  `X-Odoo-Url/Db/Login` and a `Bearer` passed through to Odoo, with a fallback
  to the server's own secret) had no caller and was removed in 1.5.0;
  `ODOO_MULTITENANT` and `ODOO_HTTP_BEARER` stay parsed, with no behaviour.

## Design tenets

- One tool surface across versions — callers use modern names.
- Fail with remediation — `CompatError` explains what to change; unavailable
  fields degrade to warnings, not hard failures.
- Zero runtime dependencies — the plugin runs the shipped source with `python3`;
  optional deps (cache/metrics/otel) are used when present and never block
  startup.
- No secrets in logs or on disk.
