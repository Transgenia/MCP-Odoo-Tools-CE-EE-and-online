# Voluntary telemetry report (template — fill manually, never auto-sent)

> This template is for operators who explicitly opted in (`ODOO_TELEMETRY=opt-in`),
> ran `/odoo-doctor`, reviewed the exact payload on screen, and **choose** to share
> it for continuous improvement of the plugin. Nothing here is collected
> automatically. Do NOT add URLs, DB names, logins, secrets, emails, phones,
> company names, record contents, module lists, or billing figures — any report
> containing those will be deleted, not processed.

```json
{
  "plugin_version": "0.1.0",
  "odoo_version_major": 17,
  "odoo_edition": "community",
  "odoo_deployment": "onprem",
  "transport": "auto",
  "tool_calls_total": 4,
  "tool_calls_by_tool": { "odoo_version": 1, "odoo_search_read": 3 }
}
```

How to share: paste the block from `/odoo-doctor` into an email to
**dev@transgenia.org** with subject `opt-in telemetry`, or open a discussion
attaching this file. To stop participating: `unset ODOO_TELEMETRY` and restart.
