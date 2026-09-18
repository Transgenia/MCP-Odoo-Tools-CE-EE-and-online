# SPDX-License-Identifier: MIT
# Clean-room MIT Odoo MCP server. Runs the stdio server; attach with `docker run -i`.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY server/ /app/server/
RUN pip install --no-cache-dir "/app/server[cache]"

# Non-root
RUN useradd -m mcp
USER mcp

# stdio MCP server: run interactively, e.g.
#   docker run -i --rm -e ODOO_URL -e ODOO_DB -e ODOO_LOGIN -e ODOO_API_KEY odoo-mcp-tools
ENTRYPOINT ["odoo-mcp"]
