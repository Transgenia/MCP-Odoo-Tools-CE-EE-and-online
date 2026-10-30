# Support

**odoo-tools** is built and maintained by [Transgenia](https://transgenia.org)
(Centrum Transgenia SAS).

## Start here

In Claude Code, run **`/odoo-tools:odoo-setup-mcp`**: the guided route for setup,
verification, hands-on training, daily use and deployment. No Odoo to practise
with? **`/odoo-tools:deploy-local`** starts a local sandbox. **`/odoo-doctor`**
checks an existing connection.

Using Cowork or claude.ai chat? The Odoo tools do not run there: the plugin's skills
and commands load, but those apps do not start its MCP server and have no form for
the connection options. Nothing is wrong with your account, your Odoo or your
Python. If Claude or the app shows this plugin's server as `not_started` with the
reason `user_config_unsupported`, that is this case, not a bug, and no update
changes it. Open a local session of the **Code** tab of Claude Desktop (or Claude
Code in a terminal, VS Code or JetBrains): the plugin you installed on your Claude
account appears there as a synced plugin when you sign in with the same account. A
cloud session of the Code tab does not work either, for another reason: your
connection options stay on your computer. Or ask Transgenia for assisted setup
(below). See [Where it works](README.md#where-it-works).

## If something fails: the support report

Run **`/odoo-tools:odoo-doctor`**. It checks first whether the Odoo tools run where
you are, then the connection, and it ends with a **support report** you can send
to Transgenia. The report holds no API keys, passwords, URLs, logins or record
data.

- In Claude Code the doctor builds it with
  `python3 <plugin folder>/server/run_stdio.py --diagnose`, which only reads the
  plugin's local diagnostics and audit files and contacts nothing.
- In Cowork, Claude's commands run in a virtual machine, not on your computer,
  so the doctor writes the report from the line the plugin's session-start hook
  leaves for Claude (Cowork runs the plugin's hooks on your computer itself).
- In Claude chat the plugin's hooks do not run, so the report names the surface
  only.

The files behind it stay on your computer, in the `diagnostics` folder of the
plugin's data folder. In Claude Code that is
`~/.claude/plugins/data/<plugin id>/diagnostics/` (on Windows,
`%USERPROFILE%\.claude\plugins\data\<plugin id>\diagnostics\`); in Cowork the
doctor tells you the folder, as the session-start hook reported it. The files hold
metadata only (what started, which surface, which kind of error), never values,
and the plugin never sends them anywhere. Attach them to your e-mail if support
asks.

## Contact Transgenia (official channels only)

Maintenance, support, training for your team, customizations, Odoo migrations
and assisted deployment:

- Email: **dev@transgenia.org**
- WhatsApp: **+52 55 8034 0405**, https://wa.me/525580340405
- Web: https://transgenia.org

Transgenia will never ask you for your Odoo API key or password in a chat or by
email. Security vulnerabilities: follow [`SECURITY.md`](SECURITY.md).

## Bugs and feature requests

Open an issue in this repository with the plugin version, the Odoo version and
edition, and the support report of `/odoo-tools:odoo-doctor` (it contains no
credentials).
