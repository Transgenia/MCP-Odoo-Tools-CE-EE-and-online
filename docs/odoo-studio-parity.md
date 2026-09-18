# vs Odoo Studio — what this plugin does (and doesn't)

A common question: *"Is this like Odoo Studio? Does it write code into a repo, or
into the instance/DB?"* Short answer: it makes **Studio-style low-code changes**
directly in the **instance/DB**, on **Community or Enterprise**, without the
(Enterprise-only) Studio app — and it does **not** generate module code in a repo.

## Where changes live

| | Odoo Studio | This plugin (RPC) | Module development |
|---|---|---|---|
| Edition | Enterprise only | Community **and** Enterprise | Any |
| Storage | Instance/DB records | Instance/DB records | Code files in a repo/module |
| Field | UI editor | `odoo_add_field` (manual `x_` field) | Python field on a model |
| View | UI editor | `odoo_create` on `ir.ui.view` (inherited xpath) | XML in the module |
| Automation | UI editor | `odoo_add_automation` (safe_eval server action) | `ir.actions.server` / real code |
| Editable later in Studio UI | Yes | No (runs identically, just not Studio-tagged) | No |

So the parity is real for the **common low-code cases** — add a field, tweak a
view, automate a small action — which is exactly what most "just add this one
thing" requests are.

## What this plugin is NOT

It does not replace serious module development: packaged addons, migrations,
automated tests, complex business logic, or anything that belongs in version
control. For that, build a module. This plugin is for the small stuff, fast.

## The safe_eval caveat (especially Odoo online/SaaS)

Automations run server-side under Odoo's **safe_eval**: no `import`, `def`,
`class`, `return`, `with`, or underscore/dunder access — and **no attribute or
subscript assignment** (`STORE_ATTR` is blacklisted: `rec.field = value` fails
server-side; use `records.write({'field': value})`). On **Odoo online/SaaS**
this is strictly enforced. `odoo_add_automation` validates your python **before**
sending it and refuses forbidden constructs with a clear remediation, so you find
out locally instead of via a server error.

Available names in that context include `env`, `model`, `record`/`records`,
`datetime`, `dateutil`, `time`, `UserError`. Return an action by assigning
`action = {...}` as the last statement.

## Try it

See the `odoo-studio-style` skill for step-by-step recipes (field, inherited
view, automation) with copy-paste examples.
