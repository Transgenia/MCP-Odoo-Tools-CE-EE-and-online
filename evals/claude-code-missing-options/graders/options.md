---
type: llm
---

PASS if the reply tells the user to fill the plugin's connection options (Odoo URL, database and login, plus an API key or password) through /plugin, Configure options or /plugin configure, and then to restart or reload, and it keeps the API key out of the chat (it says to enter it in the options form, not to paste it in the conversation).
FAIL if it asks the user to paste the API key or password into the chat, or if it says the Odoo tools cannot run in Claude Code.
