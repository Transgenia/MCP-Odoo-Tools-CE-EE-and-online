---
name: odoo-mcp-tools
description: Entry point for the MCP-Odoo-Tools plugin — connects Claude Code and Cowork to any Odoo instance (Community, Enterprise, or online, versions 10 through 19) for querying data, exporting records, cross-version compatibility, and low-code customization without Odoo Studio. Start here to pick the specific skill for your task.
license: MIT
metadata:
  author: Transgenia
  homepage: https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online
---

# Odoo MCP Tools — start here

This is the index for the `odoo-tools` plugin (repo: `Transgenia/MCP-Odoo-Tools-CE-EE-and-online`). It bundles an MCP server, a CLI fallback, and five task-specific skills that cover Odoo 10-19, Community and Enterprise, self-hosted and online.

## When to activate

Use this skill whenever the user wants an AI agent to read, write, export, or customize data in an Odoo ERP instance, or asks which Odoo-related skill in this plugin to use.

## Install

```
/plugin marketplace add Transgenia/MCP-Odoo-Tools-CE-EE-and-online
/plugin install odoo-tools
```

Then run `/odoo-tools:odoo-setup-mcp` (or `odoo-setup-cli` if you can't run the MCP server) to connect it to a real instance.

## Pick the right skill

| You need to... | Use |
| --- | --- |
| Connect to a new Odoo instance and detect its version/edition/deployment before doing anything else | `odoo-connect` |
| Understand how model/field names are resolved across Odoo 10-19 (e.g. `account.invoice` → `account.move`) | `odoo-crossversion` |
| Configure the MCP server (primary surface, full tool set) | `odoo-setup-mcp` |
| Configure the TypeScript CLI fallback (no Python/`uv` available, or scripted batch access) | `odoo-setup-cli` |
| Add a custom field, an inherited view, or an automated action the way Odoo Studio would — without installing Studio or writing a module | `odoo-studio-style` |

Always run `odoo-connect` first against a new instance. The compatibility layer uses what it detects (version, edition, transport) to resolve model and field names, so the other skills rarely need version-specific branching.

## What this is not

This plugin talks to Odoo's existing data model and configuration surface. It does not replace real module development for anything beyond small, low-code changes (see `odoo-studio-style` for exactly where that line is drawn), and it does not vendor Odoo-side logic — it authenticates with credentials you provide and respects Odoo's own access rights and record rules.

## Support

Built and maintained by [Transgenia](https://transgenia.org), a Registered Anthropic partner. For implementation help beyond the open-source core, contact dev@transgenia.org.
