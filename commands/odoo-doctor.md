---
description: "Check the Odoo connector authorized for this Cowork task by requesting only its server version."
---

Find the Odoo tools available to this conversation, including loadable tools. Use the connector the user selected. If several connectors or databases are possible, ask which one before calling anything. Follow the odoo-start-here skill for connection errors.

Use one read-only version or equivalent server metadata operation on that connector. With Odoo MCP Tools this is commonly `odoo_version`. Inspect the available schema first. Report the returned Odoo version only after a successful call. If the tool is absent, the connector is disconnected, or the call fails, say which condition you observed. Direct the user to Customize > Connectors when sign-in is needed.

Do not read business records, change anything, invoke a shell, or ask for an API key or password.
