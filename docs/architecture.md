# Architecture

```
Claude (MCP client)
      │  stdio (JSON-RPC MCP)
      ▼
odoo_mcp.server  ──lists/dispatches──▶  registry (ToolRegistry)
      │                                     │
      │                                     ▼
      │                              tools/ (crud, meta, export, i18n, report)
      │                                     │  resolve_model / resolve_fields
      │                                     ▼
      │                              compat/ (detect → deltas → resolve)
      ▼                                     │
tenancy.ConnectionManager ──▶ session.OdooSession ──▶ transport/
   (per-tenant)                 (auth, facts, cache)     fallback → jsonrpc | xmlrpc
                                                              │
                                                              ▼
                                                        Odoo instance
```

## Layers

- **transport/** — `XmlRpcTransport` (`xmlrpc.client`), `JsonRpcTransport`
  (`urllib`), and `FallbackTransport` (auto: JSON-RPC first, transparent
  XML-RPC fallback on API-key rejection or transport error; pins XML-RPC after
  the first fallback and warns once). A write (any `execute_kw` that is not a
  read method) is replayed over XML-RPC only when the JSON-RPC request certainly
  never reached Odoo; after a timeout, HTTP 5xx or garbled reply the error is
  raised instead. Both share a certificate-verifying TLS
  context (`base.tls_context()`) and honour `ODOO_TIMEOUT`.
- **session.py** — `OdooSession` holds credentials, lazily authenticates (uid),
  caches version/edition/deployment facts, and wraps schema reads through the
  TTL `SchemaCache`. `ConnectionManager` (tenancy.py) maps a tenant fingerprint
  (`url|db|login`, never the secret) to a session.
- **compat/** — `detect.probe()` builds `EnvFacts`; `deltas.py` is the
  declarative delta map; `resolve.py` turns a requested model/field/capability
  into what exists on the target. Every tool calls `resolve_*` before the ORM.
- **tools/** — thin handlers registered on the shared `registry`. Write tools are
  flagged `read_only=False` for future policy hooks; the public core does not
  enforce approval gates (that belongs to a private governance layer).
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
