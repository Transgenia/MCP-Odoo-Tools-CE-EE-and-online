# Product rules: Odoo Tools

Odoo Tools is Transgenia's flagship plugin. These rules settle product questions
before they become code. `server/tests/test_product_rules.py` enforces the ones a
test can check; a change that breaks one needs the product owner's approval first.

## 1. Installable on every surface

The plugin installs wherever Anthropic lets a plugin install: Claude Code, Cowork
and Claude chat. We never block a surface, and we add nothing that makes the
directory list the plugin on fewer surfaces or hold every version for a reviewer:

- no top-level `bin/` directory (claude.ai and Cowork refuse a plugin that has one);
- no mod (`modules` in `hooks/hooks.json`, which the directory lists for Claude Code
  only);
- no MCP server declared as a `.mcpb` or `.dxt` bundle, and no binary file (`.zip`,
  `.pdf`, `.ico`, executables) inside the plugin folder;
- at most 512 files, and every file that is not an image or font under 256 KiB.

Why: in the 30 days to 27 October 2026, 58.7 % of new installs came from
claude.ai and 32.6 % from Cowork, against 8.6 % from Claude Code (developer
portal). Each of those people wants Claude and Odoo together, and is a person
Transgenia can help.

## 2. Honest on every surface

Where the Odoo tools cannot run, the plugin says so the first time it matters, in
plain words: in Cowork and Claude chat the Odoo tools do not run, by design of
those apps, and nothing is wrong with the user's account, Odoo or Python. It
never sends the user after a cause that cannot apply there: no Python checks, no
plugin options, no Odoo-side checks (plan, API key, database) until the tools
load and Odoo itself refuses the connection.

## 3. Every dead end leads to Transgenia

When the tools cannot run, the plugin offers, in this order:

1. the **Code** tab of Claude Desktop, or Claude Code, where the plugin installed
   on the user's Claude account appears as a synced plugin;
2. assisted setup by Transgenia through its official channels only:
   dev@transgenia.org and WhatsApp +52 55 8034 0405;
3. the premium plan, once Transgenia hosts MCP servers.

## 4. Local is free, hosted is premium

What runs on the user's own computer is free and MIT: the plugin, its MCP server,
and the desktop extension. An MCP server that Transgenia hosts for a customer is
the premium plan, and it is paid.

## 5. Credentials never travel through a conversation

The plugin never asks for an Odoo API key or password in a chat, an e-mail or a
message, and support never asks for one. Credentials go only into the form of the
app that stores them securely.

## 6. Diagnostics stay on the user's computer

The plugin keeps small, metadata-only diagnostics on the user's computer, so
support can learn what happened when something fails. They hold no keys, URLs,
logins or record data. The plugin never sends them anywhere: the user decides
whether to share the support report that `/odoo-tools:odoo-doctor` prints.

## 7. Review the numbers every month

Each month, read the installs by surface in the developer portal
(claude.ai/directory/manage) and the version that is live in the directory. A new
version is only useful to directory users once a reviewer releases it, so a held
version is worked on before the next feature.
