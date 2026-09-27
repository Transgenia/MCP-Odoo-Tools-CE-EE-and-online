# SPDX-License-Identifier: MIT
# Clean-room MIT Odoo MCP server. Runs the stdio server; attach with `docker run -i`.
FROM python:3.13-slim

LABEL org.opencontainers.image.source="https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online" \
      org.opencontainers.image.vendor="Transgenia" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY server/ /app/server/
RUN pip install --no-cache-dir "/app/server[cache]"

# Non-root
RUN useradd -m mcp
USER mcp

# stdio MCP server: run interactively, e.g.
#   docker run -i --rm --env-file ./odoo.env odoo-mcp-tools
# where odoo.env (chmod 600, never committed) sets ODOO_URL, ODOO_DB, ODOO_LOGIN
# and ODOO_API_KEY.
ENTRYPOINT ["odoo-mcp"]
