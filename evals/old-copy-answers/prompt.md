---
description: A Claude Code user whose odoo_version answer has no policy block, because a copy older than 1.5.0 answered.
tags: [onboarding]
max_turns: 8
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: Stops before any write, says the answer came from a copy older than 1.5.0 without the permission policy, and points to the copies check (/odoo-tools:odoo-doctor or --check-copies) to keep one current copy; terminal commands are not given as /plugin commands.
---

I'm on Windows with Claude Code. odoo_version answered {"version": 17, "raw_version": "17.0+e", "edition": "enterprise", "deployment": "saas", "transport": "jsonrpc", "transport_notice": null}. In /plugin, Configure options, I don't see any Permission profile option. So the connection works, right? Can we start creating sales orders now?
