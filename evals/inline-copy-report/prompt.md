---
description: A Windows user of the Claude desktop app writes in Arabic and pastes the 1.6.0 support report of a copy in odoo-tools-inline, with Python 3.15.1 and no server event (the case of 2026-11-08).
tags: [surface]
max_turns: 8
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: Replies in Arabic; reads the data folder odoo-tools-inline as a copy the desktop app loaded, not an install; does not blame Python 3.15; offers Claude Code on the computer (a local session of the Code tab with the plugin installed for the user, or a terminal) and Transgenia's assisted setup.
---

السلام عليكم
اريد تشغيل اضافة اودو علي كلود دسك توب ولم انجح في ذلك. حاولت كثيرا

odoo-tools support report (no keys, URLs, logins or record data)
plugin: 1.6.0
python: 3.15.1
os: Windows 11 AMD64
diagnostics folder: C:/Users/user/.claude/plugins/data/odoo-tools-inline/diagnostics (exists)
last 5 server events (server.jsonl):
  none
last 3 hook events (hook.jsonl):
  {"v":1,"ts":"2026-11-08T11:29:03Z","event":"session_start","source":"resume","plugin":"1.6.0","os":{"system":"Windows","release":"11","machine":"AMD64"},"python":"3.15.1","entrypoint":"claude-desktop","server_last":"none","container":false}
  {"v":1,"ts":"2026-11-08T11:43:33Z","event":"session_start","source":"startup","plugin":"1.6.0","os":{"system":"Windows","release":"11","machine":"AMD64"},"python":"3.15.1","entrypoint":"claude-desktop","server_last":"none","container":false}
audit: missing
policy computed offline from this command's environment (the plugin's options may differ; never contacts Odoo): profile standard, digest 21524d1933f3, locked no, policy file no, read-only no
