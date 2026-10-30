# CLAUDE.md

This repository is the odoo-tools plugin by Transgenia. Its root is the plugin
folder that the Claude plugin directory scans and that users install. When you
change it:

- Follow [`docs/product-rules.md`](docs/product-rules.md). A change that breaks a
  rule needs the product owner's approval first.
- Follow [`CONTRIBUTING.md`](CONTRIBUTING.md): MIT, clean-room, standard library
  only in `server/src`, Python 3.9.
- Check every change against the manual at docs.transgenia.org (rule 8): update it
  in Spanish, English and Chinese in the same release, and say in the pull request
  what changes there, or why nothing does.
- Write public text with plain ASCII punctuation: no em or en dashes, no emojis.
- Never ask for an Odoo API key or password in a conversation. No hook reads plugin
  options or credentials, and the MCP server reads only the credentials that
  `.claude-plugin/plugin.json` passes from a `sensitive` option.
- Before you push, from `server/`: `ruff check src tests ../scripts ../hooks` and
  `pytest -q -m "not live"`; from the root: `python3 scripts/policy_docs.py --check`.
- Release steps: [`docs/packaging.md`](docs/packaging.md).
