# Evals

Cases for `claude plugin eval` (Claude Code 2.1.269 or later). None of them starts
the plugin's MCP server: an eval run never starts it unless asked and no case has a
mock, so every case runs with the Odoo tools missing, as they are in Cowork and
Claude chat. They check what the plugin says then (docs/product-rules.md, rules 2
and 3), which is what the Cowork incident of 2026-10-28 got wrong.

Run them from the repository root; they call the model with your credentials:

```bash
claude plugin eval . --ablation none --runs 1 --trust-plugin --no-publish --max-cost-usd 5
```

Run them from a terminal on your computer. In a cloud session the plugin's
session-start hook records that session's entrypoint (`remote_desktop`), and the
doctor reads it as a cloud session, so the cases about Cowork no longer play out
as in Cowork. There, set the entrypoint a terminal would have:

```bash
CLAUDE_CODE_ENTRYPOINT=cli claude plugin eval . --ablation none --runs 1 --trust-plugin --no-publish --max-cost-usd 5
```
