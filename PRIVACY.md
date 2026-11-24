# Privacy for Odoo Tools in the Claude directory

This edition contains instructions, reference notes and a listing icon. It has no server, local program, settings form, analytics or storage of its own. Installing the plugin does not grant access to an Odoo database.

## Live Odoo questions

When you request a lookup, Claude sends its tool arguments to the Odoo connector you have enabled. Depending on the question, these can include model names, field names and search filters. The connector queries its configured Odoo instance under your existing permissions. The returned data is available to Claude in your task. A connection check requests only server version information.

Your Claude provider, connector operator and Odoo administrator handle that data under their own terms and retention settings. The plugin specifies no destination for Odoo requests and sends no telemetry to Transgenia. If your organization uses a connector operated by Transgenia, that separate service handles the connector traffic under its own terms.

## Credentials and support

Use your connector's sign-in interface. Never paste API keys or passwords into a conversation. If you contact Transgenia, it receives what you choose to send. Do not send API keys, passwords, private URLs or customer data. The support email is dev@transgenia.org. [Transgenia privacy notice](https://transgenia.org/en/legal-privacy.html).
