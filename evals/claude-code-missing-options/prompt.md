---
description: A Claude Code user whose server never started, because the connection options are empty.
tags: [surface]
max_turns: 8
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: Sends the user to the plugin's options (Odoo URL, database, login, API key) in /plugin, then a restart; does not blame Cowork; never asks for the key in the chat.
---

I'm using Claude Code in my terminal. I installed the odoo-tools plugin, but the odoo_version tool is not available and /mcp does not list an odoo server. How do I fix it?
