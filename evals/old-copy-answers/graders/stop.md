---
type: llm
---

PASS if the reply says not to start writing yet, explains that an odoo_version answer without a `policy` block (and an options dialog without Permission profile) means an odoo-tools copy older than 1.5.0 answered, one without the permission policy and often a second copy, and tells the user to find and remove it: with /odoo-tools:odoo-doctor, the copies check (`--check-copies`), or `claude plugin list` and `claude plugin uninstall` in a terminal.
FAIL if it says the setup is fine or helps create sales orders, if it never connects the missing `policy` block to an older or second copy, or if it tells the user to type a `/plugin` command in PowerShell.
