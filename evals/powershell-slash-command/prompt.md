---
description: A Windows user who typed a /plugin command in PowerShell.
tags: [onboarding, surface]
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: Explains that /plugin commands are typed inside Claude Code, gives the terminal form (claude plugin install odoo-tools --marketplace ...), and covers `claude` not being recognized (a new PowerShell window, or the full path in %USERPROFILE%\.local\bin).
---

I typed "/plugin install odoo-tools --marketplace Transgenia/MCP-Odoo-Tools-CE-EE-and-online" in PowerShell and it says the term is not recognized. I also tried "claude" and it is not recognized either, even though I installed Claude Code a minute ago. What do I do?
