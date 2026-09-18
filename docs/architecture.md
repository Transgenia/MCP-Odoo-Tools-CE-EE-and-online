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

- **transport/** — `XmlRpcTransport`, `JsonRpcTransport`, and `FallbackTransport`
  (auto: JSON-RPC first, transparent XML-RPC fallback on API-key rejection or
  transport error; pins XML-RPC after the first fallback and warns once).
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
- **server.py / __main__.py** — MCP stdio wiring and the `odoo-mcp` entrypoint.
  Handlers run in a worker thread (`anyio.to_thread`) so blocking RPC never
  stalls the event loop. Logs go to stderr; stdout is the MCP channel only.

## Transports & modes

- **stdio (default):** single-tenant, credentials from environment. This is the
  mode the plugin's `mcpServers` entry uses.
- **HTTP (docker, optional/roadmap):** multi-tenant via `X-Odoo-Url/Db/Login`
  headers + `Bearer` secret, resolved by `tenancy.from_headers`.

## Design tenets

- One tool surface across versions — callers use modern names.
- Fail with remediation — `CompatError` explains what to change; unavailable
  fields degrade to warnings, not hard failures.
- Lean base install — optional deps (cache/metrics/otel) never block startup.
- No secrets in logs or on disk.
