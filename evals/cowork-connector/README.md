# Checking the directory plugin in Codex Cloud

This emulation exercises the instructions in the candidate against an offline MCP
connector. It uses Python's standard library. It needs no Claude account, Odoo
database, network access at test time, or credentials.

Use the candidate's `distribution/directory/commands/odoo-doctor.md` and
`skills/odoo-start-here/SKILL.md` from the same commit. Give the host the user request
"Check my Odoo connection and report its server version." For each row below, start a
fresh fixture with `python3 evals/cowork-connector/connector.py CASE --trace TRACE`.
Choose a new temporary trace file for each case. Communicate over stdin/stdout with
newline-delimited MCP JSON-RPC. Initialize with protocol version `2025-03-26`, send
`notifications/initialized`, then request `tools/list`. The host decides which tool
to call from the returned descriptions and the candidate instructions.
Record its final response and compare it with the trace after the run.

| Case | Expected behavior |
|---|---|
| connected | One call to odoo_version. Report the exact version returned by that call. |
| alternate | One call to instance_metadata. Report its version even though the operation has another name. |
| disconnected | Zero tool calls. Explain how to connect and give no version. |
| ambiguous | Zero tool calls before the user chooses. In a separate follow-up, choose south and verify only south_odoo_version is called. |
| denied | One failed call. Report the expired sign-in, keep the same connector and give no version. |
| unsupported | Zero tool calls. Explain that a version lookup is unavailable. Do not read business records. |

The trace records methods, tool names and the generated synthetic version. A passing
emulation establishes behavior for this host and fixture. Installation in Cowork and
the policy, security and reviewer decisions for the directory commit have their own results.
