# Architecture

```
Claude (MCP client)
      │  stdio (JSON-RPC MCP)
      ▼
odoo_mcp.server  ──lists/dispatches──▶  registry (ToolRegistry)
      │                                     │
      │                                     ▼
      │                              tools/ (crud, meta, export, i18n, report, studio, online)
      │                                     │  resolve_model / resolve_fields
      │                                     ▼
      │                              compat/ (detect → deltas → resolve)
      ▼                                     │
tenancy.ConnectionManager ──▶ session.OdooSession ──▶ transport/
   (per-tenant)                 (auth, facts, cache)     fallback → json2 | jsonrpc | xmlrpc
                                                              │
                                                              ▼
                                                        Odoo instance
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
  TTL `SchemaCache`. `ConnectionManager` (tenancy.py) maps a tenant fingerprint
  (`url|db|login`, never the secret) to a session.
- **compat/** — `detect.probe()` builds `EnvFacts`; `deltas.py` is the
  declarative delta map; `resolve.py` turns a requested model/field/capability
  into what exists on the target. Every tool calls `resolve_*` before the ORM.
- **tools/** — thin handlers registered on the shared `registry`. Write tools are
  flagged `read_only=False`: `ODOO_READONLY=1` refuses them in `server.py`
  before any session exists; the public core has no other approval gate (that
  belongs to a private governance layer). `tools/online.py` holds the Odoo
  Online tools. Its two import tools pass `transports=("json2", "jsonrpc")` to
  `session.execute`, and the fallback never sends or replays such a call over
  XML-RPC, whose marshaller cannot return the `None` values an import result
  carries. `session.api_doc(model)` serves `/doc-bearer` without handing the
  secret to a tool.
- **observability.py** — optional Prometheus metrics and OTLP tracing, both
  off by default and no-ops when the extras are absent.
- **server.py / __main__.py / run_stdio.py** — the MCP stdio protocol,
  implemented on the Python standard library (no MCP SDK): newline-delimited
  JSON-RPC 2.0 with `initialize` (protocol version negotiation), `ping`,
  `tools/list` (`readOnlyHint` annotations from each tool's `read_only` flag),
  `tools/call`, `notifications/cancelled` and batches. `run_stdio.py` is what
  the plugin runs (bundled `src` first on `sys.path`); `odoo-mcp` /
  `python -m odoo_mcp` are the installed entry points. Tool calls run in arrival
  order on **one worker thread**, so the reader keeps answering `ping` and
  honouring cancellations while Odoo works, and sessions/transports never see
  concurrent use. Tool failures come back as `isError` results; an unknown tool
  is a JSON-RPC `-32602` error. Logs go to stderr; stdout is the MCP channel
  only (stray `print()` output is redirected to stderr).

## Transports & modes

- **stdio (default):** single-tenant, credentials from environment. This is the
  mode the plugin's `mcpServers` entry uses.
- **HTTP (docker, optional/roadmap):** multi-tenant via `X-Odoo-Url/Db/Login`
  headers + `Bearer` secret, resolved by `tenancy.from_headers`.

## Design tenets

- One tool surface across versions — callers use modern names.
- Fail with remediation — `CompatError` explains what to change; unavailable
  fields degrade to warnings, not hard failures.
- Zero runtime dependencies — the plugin runs the shipped source with `python3`;
  optional deps (cache/metrics/otel) are used when present and never block
  startup.
- No secrets in logs or on disk.
