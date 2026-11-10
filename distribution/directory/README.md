# Odoo Tools Guide

This edition of Odoo Tools contains no code and has no connection to Odoo. It adds no tool for Claude to read or change your Odoo, in any app. It does give Claude reference knowledge about Odoo 10 to 19 (what changed between versions) and tells you how to get help connecting Claude to your Odoo. Nothing is wrong with your Claude account, your Odoo or your computer.

It is published by [Transgenia](https://transgenia.org). It is an independent tool: it is not affiliated with or endorsed by Odoo S.A. or by Anthropic. If your Claude app already has another Odoo connector, keep using it: this plugin does not replace or change it.

## What is in this plugin

- Skill `odoo-start-here`: says what this edition is, what it is not, and how to get help.
- Skill `odoo-version-reference`: reference notes on what changed in Odoo between versions 10 and 19 (models, fields, API endpoints, Odoo Online lines).
- Command `/odoo-tools-guide:odoo-help`: shows the scope of this edition and the ways forward.

All of it is plain text (Markdown and JSON) and one image. It needs no Python, no Node and no Docker, and it has no settings to fill in.

## Example prompts

- "On Odoo 16 or later, which field replaces analytic_account_id on account.move.line?"
- "My Odoo Online database is on saas~19.2 and read_group fails. Why, and what do I use instead?"
- "Can I still connect to Odoo 19 with XML-RPC and a password? What replaces it?"

## What it does not do

- It does not run programs, hooks or servers on your computer.
- It does not connect to Odoo, to Transgenia or to any other service.
- It does not send, fetch or store anything. The skills and the command are instructions for Claude written in this folder, and none of them tells Claude to fetch instructions from anywhere else.
- It does not ask for, accept or keep Odoo API keys or passwords.

## Ways forward

In this order:

1. The full local edition connects Claude to your Odoo with a program that runs on your own computer, in Claude Code (terminal, VS Code, JetBrains, or a local session of the Code tab of Claude Desktop). It does not run in Claude chat or in Cowork. It is a separate plugin published by Transgenia on GitHub and is not included in this plugin. Anthropic's directory review does not cover a plugin you add from GitHub: add it only if you trust its publisher. The instructions are in the manual: https://docs.transgenia.org/odoo-tools/
2. Assisted setup by Transgenia, a service that you contract through its official channels only: dev@transgenia.org and WhatsApp +52 55 8034 0405 (https://wa.me/525580340405).

## Credentials

Never paste an Odoo API key or password into a conversation with Claude, an e-mail or a message. Transgenia never asks for them either. If you pasted an API key by mistake, delete that key in Odoo (Preferences > Account Security) and create a new one. If you pasted a password, change it in Odoo now.

## Privacy, support and license

- Privacy: [PRIVACY.md](PRIVACY.md). Support: [SUPPORT.md](SUPPORT.md).
- MIT license: [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md). "Odoo" is a trademark of Odoo S.A.; this is an independent tool, not affiliated with or endorsed by Odoo S.A.
