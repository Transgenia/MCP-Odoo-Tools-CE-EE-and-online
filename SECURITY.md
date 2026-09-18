# Security policy

## Credentials

- Odoo credentials are read from the environment (`ODOO_URL`, `ODOO_DB`,
  `ODOO_LOGIN`, `ODOO_API_KEY`/`ODOO_PASSWORD`) or, in multi-tenant HTTP mode,
  from per-request headers (`X-Odoo-Url/Db/Login` + `Bearer`).
- Secrets are never persisted to disk by this project and never written to logs.
  The tenant cache key is `url|db|login` — the secret is not part of it.
- Prefer **API keys** (Odoo ≥ 14) over passwords. Use least-privilege Odoo users.

## Transport

- Use HTTPS Odoo URLs. XML-RPC and JSON-RPC both run over the URL you provide.
- The server logs to stderr only; stdout is reserved for the MCP channel.

## Reporting a vulnerability

Email **dev@transgenia.org** with details and reproduction steps. Please do not
open public issues for security reports. We aim to acknowledge within 5 business
days.
