# odoo-tools-lsp (premium, private)

A language server for Odoo addons, versions 10.0 to 19.0 (Community, Enterprise and Odoo Online),
built by Transgenia. It runs inside Claude Code as a plugin (terminal sessions); LSP editors such as
VS Code or Neovim can start it through a generic language-client configuration (no editor extension is
published). Plugin language servers do not run in Claude Code cloud sessions, where a command-line check
is available instead.

**This folder contains no source code.** The language server is proprietary and is developed in a
private Transgenia repository. The MIT license of this repository covers this README only; the
language server is not part of this repository and is not MIT-licensed.

## What it does
- Version-aware diagnostics for Python, XML views and data, QWeb, JS, SCSS, CSV access rules and
  manifests, based on checks derived from the Odoo 10.0-19.0 sources. In Claude Code at most 10
  diagnostics per file reach the model; the command-line check lists all of them.
- Navigation for models, fields, XML ids and templates: definition, references, implementations
  (`_inherit` chains and overrides), symbols and call hierarchy; hover with version notes.
- Quick fixes for common migrations (for example attrs/states to Python expressions, tree to list,
  name_get to _compute_display_name), also available as a batch `fix` command.
- Live mode (planned, not enabled in the current preview): read-only field metadata from your Odoo
  instance through the MIT `odoo-mcp-tools` package published from [`server/`](../../server/).

## Relation to this repository
It reuses the public `odoo-mcp-tools` Python package (version detection, compatibility data and the
read-only Odoo connection). Using odoo-tools (this repository) never requires the language server.

## Configuration example
`.odoo-tools-lsp.json` at your project root: `{"odooVersion": "17.0"}`

## Status and access
Private preview for Transgenia clients. Contact Transgenia through its official channels:
**dev@transgenia.org** · WhatsApp **+52 55 8034 0405** (https://wa.me/525580340405).
