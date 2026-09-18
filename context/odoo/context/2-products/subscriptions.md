# Suscripciones

## CLI relevante
- `subscriptions` - Buscar suscripciones en sale.order
- `products` - Ver productos/planes disponibles

## Modelo: sale.order (con is_subscription=true)

### Opciones de busqueda

| Opcion | Tipo | Descripcion |
|--------|------|-------------|
| `active` | boolean | Solo suscripciones activas (3_progress) |
| `partner_name` | string | Buscar por cliente |
| `state` | string | "3_progress" (activa), "5_renewed" (renovada), "6_churn" (baja) |
| `plan_id` | number | ID del plan de suscripcion |
| `currency` | string | "ARS", "USD", etc. |
| `date_from` / `date_to` | string | Filtro por start_date |
| `limit` | number | Maximo 100 |

### Campos retornados

- `id`, `cliente`, `cliente_id`, `estado`, `plan`
- `mrr` (recurring_monthly), `moneda`
- `inicio`, `fin`, `total`

## Campo recurring_monthly

Odoo calcula automaticamente el MRR mensualizado segun el plan:
- Plan mensual: monto tal cual
- Plan semestral: monto / 6
- Plan anual: monto / 12

## Descubrir planes disponibles

Cada instancia de Odoo tiene sus propios planes. Para descubrirlos:
```bash
# Ver campos del modelo de planes
cli.js fields '{"model":"sale.subscription.plan"}'

# Listar planes existentes
cli.js search '{"model":"sale.subscription.plan","fields":"name,billing_period,billing_period_unit"}'
```

## Queries de ejemplo

```bash
# Todas las suscripciones activas
cli.js subscriptions '{"active":true}'

# Suscripciones de un cliente
cli.js subscriptions '{"partner_name":"nombre"}'

# Suscripciones en USD
cli.js subscriptions '{"active":true,"currency":"USD"}'

# Bajas recientes
cli.js subscriptions '{"state":"6_churn"}'

# Renovadas
cli.js subscriptions '{"state":"5_renewed"}'

# Filtrar por plan especifico (usar ID descubierto con search)
cli.js subscriptions '{"active":true,"plan_id":1}'
```
