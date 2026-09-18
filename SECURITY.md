# Security policy

## Credentials

- Odoo credentials are read from the environment (`ODOO_URL`, `ODOO_DB`,
  `ODOO_LOGIN`, `ODOO_API_KEY`/`ODOO_PASSWORD`) or, in multi-tenant HTTP mode,
  from per-request headers (`X-Odoo-Url/Db/Login` + `Bearer`).
- Secrets are never persisted to disk by this project and never written to logs.
  The tenant cache key is `url|db|login` — the secret is not part of it.
- The `Settings` object **redacts credentials in `repr()`/`str()`** so accidental
  logging cannot leak them (enforced by `tests/test_security_redaction.py`).
- Prefer **API keys** (Odoo ≥ 14) over passwords. Use least-privilege Odoo users.

## Automated checks (CI)

- **`.github/workflows/security.yml`** runs on every push/PR:
  - **gitleaks** — scans history and diffs for committed secrets.
  - **leak-guard** — greps the tree for forbidden internal/tenant markers
    (client data, infra hosts, fiscal IDs, hardcoded credentials) and fails the
    build if any appear. This repo is vendor-neutral: it must contain only the
    generic tooling plus the public author/brand and services offer.
- **`.gitignore`** excludes `.env`, `*.env`, virtualenvs and build output so
  local credentials cannot be committed by accident.

## Transport

- Use HTTPS Odoo URLs. XML-RPC and JSON-RPC both run over the URL you provide.
- The server logs to stderr only; stdout is reserved for the MCP channel.

## Reporting a vulnerability

Email **dev@transgenia.org** with details and reproduction steps. Please do not
open public issues for security reports. We aim to acknowledge within 5 business
days.
