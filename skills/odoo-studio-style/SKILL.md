---
name: odoo-studio-style
description: Do Odoo Studio-style low-code changes (custom fields, views, automations) over RPC — on Community or Enterprise, without the Studio app. Use when the user wants to add a field, tweak a view, or automate a simple action.
---

# Studio-style low-code changes (CE & EE)

Odoo **Studio** is an Enterprise-only visual editor. The customizations it makes
— custom fields, views, automated actions — are ordinary Odoo records stored in
the **database**. This plugin can create those same records over RPC, so you get
the common Studio outcomes on **Community too**, without the license.

Be honest about the boundary: this covers **small, low-code** changes (a field,
a view tweak, a simple automation). It is **not** a substitute for serious module
development (packaged code, migrations, tests, complex business logic).

## Where changes live
In the **instance/DB**, exactly like Studio — not as module code in a repo. They
survive upgrades as manual customizations. (If you need code-in-a-repo, that is
module development, which is out of scope for this plugin.)

## 1. Add a custom field
Use the `odoo_add_field` tool. It creates a `state='manual'` field and forces the
required `x_` name prefix.
```
odoo_add_field {
  "model": "res.partner",
  "name": "loyalty_points",         // becomes x_loyalty_points
  "label": "Loyalty Points",
  "field_type": "integer"
}
```
Relational example:
```
odoo_add_field { "model": "res.partner", "name": "account_manager",
  "label": "Account Manager", "field_type": "many2one", "relation": "res.users" }
```
Selection example: pass `selection` as `[["a","A"],["b","B"]]`.
After creating a field, add it to a form/tree view (see step 2) so users can see it.

## 2. Tweak a view (inherited)
There is no dedicated tool; use `odoo_create` on `ir.ui.view` with an inherited
arch so you never overwrite the base view. First find the view to extend:
```
odoo_search_read { "model": "ir.ui.view", "domain": [["model","=","res.partner"],["type","=","form"]],
  "fields": ["name","xml_id"], "limit": 5 }
```
Then create an inherited view:
```
odoo_create { "model": "ir.ui.view", "values": {
  "name": "res.partner.form.x_loyalty",
  "model": "res.partner",
  "inherit_id": <base_view_id>,
  "arch_db": "<xpath expr=\"//field[@name='email']\" position=\"after\"><field name=\"x_loyalty_points\"/></xpath>"
}}
```
Prefer `xpath ... position="after|before|inside|replace"` over full-view rewrites.

## 3. Add an automation
Use `odoo_add_automation`. The python runs under Odoo **safe_eval**; the tool
validates it before sending, which matters most on **Odoo online/SaaS** where
arbitrary python is refused server-side.
```
odoo_add_automation {
  "model": "crm.lead",
  "name": "Tag hot leads",
  "trigger": "on_create_or_write",
  "code": "for rec in records:\n    if rec.probability and rec.probability > 80:\n        rec.write({'priority': '3'})"
}
```
safe_eval rules (enforced by the tool): **no** `import`/`def`/`class`/`return`/
`with`, no underscore/dunder access, **no attribute or subscript assignment**
(Odoo forbids `STORE_ATTR`: `rec.field = value` fails server-side). Available names include `env`, `model`,
`record`/`records`, `datetime`, `dateutil`, `time`, `UserError`. To return an
action, assign `action = {...}` as the last statement (never `return`).

## Enterprise vs Community
- Fields/views/automations created here work on **both** editions.
- On **Enterprise**, they won't appear inside the Studio editor UI (they aren't
  tagged as `web_studio` customizations), but they behave identically at runtime.
- Enterprise-only *models* (e.g. `documents.document`) still can't be targeted on
  Community — the compat layer raises a clear error.

## Verify (Definition of done)
Read the record back and confirm the effect:
- field: `odoo_fields_get { "model": "<model>" }` shows the new `x_` field.
- view: open the form in Odoo (or read the inherited `ir.ui.view`).
- automation: trigger it on one record and read the changed field.
