# Claude Desktop extension (preview)

This is a preview of the odoo-tools MCP server as a Claude Desktop extension: a
single `.mcpb` file (an MCP Bundle) that Claude Desktop for macOS and Windows
installs in one step. It is free and MIT licensed, like the plugin. It runs
locally: Claude Desktop starts, on your computer, the same MCP server with the
same permission policy as the odoo-tools plugin for Claude Code, and the server
talks only to the Odoo you configure. Nothing is sent to Transgenia.

The preview exists so that the extension can be tested by hand in Claude
Desktop, in chat and in Cowork, before it is published. It is not in any
directory and not attached to a release. It does not replace the plugin: in
Claude Code, keep using the plugin ([install.md](install.md)). Both can be
installed on the same computer, each with its own settings.

## Where the file comes from

The `.mcpb` file is never committed and is not part of the plugin. The root of
this repository is the plugin folder, and the Claude plugin directory holds for
review any plugin that declares its MCP server as a `.mcpb`, or that ships a
`.zip` or `.mcpb` file in that folder. So git ignores `*.mcpb` and `dist/`, and
nothing in `plugin.json` refers to the bundle.

The Desktop extension preview workflow (`.github/workflows/mcpb-preview.yml`)
builds the file on every pull request, and on demand from the Actions tab (Run
workflow). It validates the manifest with the official MCPB command line tool,
starts the bundled server with no network and no Odoo settings to check that it
answers and lists its tools, and uploads `odoo-tools-<version>.mcpb` as a
workflow artifact. The summary page of the run links the download and shows the
SHA-256 of the file.

To build it from a checkout instead (Python 3.9 or newer, nothing to install):

    python3 scripts/build_mcpb.py
    python3 scripts/build_mcpb.py --smoke dist/odoo-tools-<version>.mcpb

The first command writes `dist/odoo-tools-<version>.mcpb`. Its `manifest.json` is
generated from `.claude-plugin/plugin.json`, so the version and the settings
always match the plugin, and two builds of the same sources with the same Python
give the same bytes. The second command runs the bundled server the way Claude
Desktop would, with empty settings, and checks that it answers.

## Requirements

The extension does not bring its own Python. It needs Python 3.9 or newer on the
computer, started as `python3` on macOS and as `python` on Windows. The server
uses only the Python standard library, so it installs nothing and downloads
nothing.

On macOS, `/usr/bin/python3` comes with Apple's Command Line Tools. If
`python3 --version` in Terminal offers to install them, accept, or run
`xcode-select --install`. Claude Desktop may not find a Python installed with
Homebrew or pyenv, because an app opened from the Finder does not read your shell
profile.

On Windows, install Python 3.9 or newer from python.org with "Add python.exe to
PATH" selected, or from the Microsoft Store. If `python` only opens the Microsoft
Store, Python is not installed yet.

You also need an Odoo user for the server to act as (a least-privilege user is
best), and an API key of that user (Odoo 14 and later) or its password (Odoo 10
to 13).

## Install

Any of these opens the install dialog of Claude Desktop:

- double-click the `.mcpb` file;
- drag the file into the Claude Desktop window;
- in Claude Desktop, open Settings > Extensions and install it from there
  (Advanced settings, then Install Extension), choosing the file.

Then fill in the settings form. The Odoo URL, database and login are required,
and Claude Desktop does not start the server until all three are set. Add the API
key, or the password on Odoo 10 to 13. The other settings have defaults: the
`auto` transport, a 120 second timeout, read-only mode off, the `standard`
permission profile (see [policy.md](policy.md)) and no policy file.

The server writes its audit trail, one line per tool call kept for 90 days, to
`~/.odoo-tools/desktop/audit`, and its diagnostics folder is
`~/.odoo-tools/desktop/diagnostics`. Both are separate from the data folder of
the Claude Code plugin. To remove the extension, use Settings > Extensions in
Claude Desktop; the folders under `~/.odoo-tools/desktop` stay until you delete
them.

## Where it works

Only in Claude Desktop on macOS and Windows, because the server runs on your
computer. It does not work on claude.ai in a web browser or in the Claude mobile
apps, which cannot start a server on your computer.

## What to check in the manual test

Write down the Claude Desktop version, the operating system, the Python version
and the Odoo version and edition. Then check:

1. The install dialog shows Odoo Tools by Transgenia, its version and the
   settings form. Note any warning it shows: the preview is not signed.
2. The settings form masks the API key (and the password) while you type it and
   after you save, and the key does not appear in plain text in the settings files
   of Claude Desktop.
3. In a new Claude Desktop chat, the Odoo tools are listed, `odoo_version` among
   them, and asking which Odoo version you run calls `odoo_version` and answers.
4. In a Cowork task, whether the Odoo tools appear at all, and if they do,
   whether a read such as `odoo_version` works there.
5. Once the extension has started, `~/.odoo-tools/desktop/audit` holds a file
   for today, inside your home folder and not in a folder named `${HOME}`.
6. If you test with a password (Odoo 10 to 13), try one that contains a dollar
   sign once. The MCPB code that fills settings into the server's environment
   rewrites `$$`, `$&`, `` $` `` and `$'` inside a value, so such a password may
   reach Odoo altered. Odoo API keys never contain a dollar sign.

If the tools do not appear, the MCP logs of Claude Desktop say why (macOS:
`~/Library/Logs/Claude`, Windows: `%APPDATA%\Claude\logs`). Look for `python3` or
`python` not being found, or for "Python 3.9 or newer is required".
