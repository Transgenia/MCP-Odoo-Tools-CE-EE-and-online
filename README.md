# Odoo Tools for Cowork

Ask Claude a question about your Odoo database using the Odoo connector your organization has already authorized. For example, ask how many confirmed sales orders match a date range or which fields are available on a model. The directory edition provides instructions and a version reference. Your selected connector provides the live data and enforces access.

## Check the connection

1. Open a Cowork task in the Claude organization that owns the connection. Under Customize > Connectors, check that the intended Odoo connector is connected and available to this task.
2. Run `/odoo-tools:odoo-doctor`. If several Odoo connections are visible, select the one you intend. The command asks that connector for the server version. It does not open business records.
3. Ask your question. For example: "Using that Odoo connection, count confirmed sales orders for last month." Claude uses the read operations your connector offers and identifies any limitation that affects its answer.

Use `/odoo-tools:odoo-help` for setup help. Without a connected Odoo tool you can still ask about the version differences covered in this plugin.

## Moving from the older directory version

The previous directory version started its own server in Claude Code. This edition uses the organization's existing connection in Cowork or another Claude app that exposes it. It does not import old local settings, start a server, install software, or supply the local deployment and CLI commands. The connector may expose different operations or permissions. The local edition for Claude Code is maintained separately. See the [manual](https://docs.transgenia.org/odoo-tools/).

## Privacy and support

Odoo queries and results pass through Claude and the connector you select. Sign in through that connector's own interface. Never put an API key or password in a conversation or support message. For help, contact dev@transgenia.org or WhatsApp +52 55 8034 0405. [Privacy](PRIVACY.md) and [support](SUPPORT.md).

Published by Transgenia under the [MIT license](LICENSE). Odoo is a trademark of Odoo S.A.
