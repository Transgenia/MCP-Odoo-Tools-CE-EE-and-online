---
type: llm
---

PASS if the reply says that a `/plugin` command is typed inside a Claude Code session, not in PowerShell; gives the terminal form `claude plugin install odoo-tools --marketplace Transgenia/MCP-Odoo-Tools-CE-EE-and-online` (with or without `--scope user`); and for `claude` not being recognized, says to open a new PowerShell window (the PATH changed when Claude Code was installed) or to run it by its full path, such as `%USERPROFILE%\.local\bin\claude.exe`.
FAIL if it tells the user to type `/plugin ...` or `claude /plugin ...` in PowerShell, or if it asks for an API key or password in the chat.
