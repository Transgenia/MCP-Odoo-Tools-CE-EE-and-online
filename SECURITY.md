# Security policy

## Credentials

- Odoo credentials are read from the environment (`ODOO_URL`, `ODOO_DB`,
  `ODOO_LOGIN`, `ODOO_API_KEY`/`ODOO_PASSWORD`) or, in multi-tenant HTTP mode,
  from per-request headers (`X-Odoo-Url/Db/Login` + `Bearer`).
- The **MCP server** does not persist secrets to disk and never writes them to
  logs. The tenant cache key is `url|db|login` — the secret is not part of it.
- **Exception — CLI fallback:** `/odoo-tools:odoo-setup-cli` writes a local `.env`
  containing your credentials under `~/.claude/tools/odoo-cli`. If you use that
  surface, restrict its permissions (e.g. `chmod 600`), keep it out of version
  control, and delete it when you stop using the CLI.
- **Data path when used via an AI agent:** tool results (the Odoo records you
  query) are returned to your MCP client and sent to your model provider (e.g.
  Anthropic, for Claude) for processing, as with any MCP tool. Transgenia does not
  proxy or store your data, but it is not withheld from the model — query with a
  least-privilege user and avoid pulling fields the agent does not need.
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
