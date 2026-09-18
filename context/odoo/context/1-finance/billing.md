# Facturacion y Metricas Financieras

## CLI relevante
- `invoices` - Buscar facturas y notas de credito
- `payments` - Pagos recibidos/realizados
- `subscriptions` - Suscripciones y MRR
- `account-lines` - Movimientos contables
- `bank-journals` - Diarios bancarios
- `bank-statements` - Extractos bancarios
- `chart-of-accounts` - Plan de cuentas

## Modelo: account.move (Facturas)

### Opciones de busqueda

| Opcion | Tipo | Descripcion |
|--------|------|-------------|
| `partner_name` | string | Busqueda por cliente/proveedor |
| `state` | string | "draft", "posted", "cancel" |
| `move_type` | string | "out_invoice", "in_invoice", "out_refund", "in_refund" |
| `date_from` / `date_to` | string | Filtro por invoice_date (YYYY-MM-DD) |
| `amount_min` / `amount_max` | number | Filtro por monto total |
| `payment_state` | string | "not_paid", "in_payment", "paid", "partial", "reversed" |
| `limit` | number | Maximo 100 |

### Tipos de factura
- `out_invoice` - Factura a cliente
- `in_invoice` - Factura de proveedor
- `out_refund` - Nota de credito a cliente
- `in_refund` - Nota de credito de proveedor

## Modelo: account.payment (Pagos)

### Opciones de busqueda

| Opcion | Tipo | Descripcion |
|--------|------|-------------|
| `payment_type` | string | "inbound" (cobro) o "outbound" (pago) |
| `partner_name` | string | Busqueda por cliente/proveedor |
| `state` | string | "draft", "in_process", "paid", "cancelled" |
| `date_from` / `date_to` | string | Filtro por fecha |
| `journal_id` | number | Filtro por diario |
| `limit` | number | Maximo 100 |

Nota: En Odoo 18, los estados de pago son `in_process` y `paid` (no `posted`).

## Metricas financieras comunes

### MRR (Monthly Recurring Revenue)
```
MRR = SUM(recurring_monthly) de suscripciones activas
```

### ARR (Annual Recurring Revenue)
```
ARR = MRR x 12
```

### DSO (Days Sales Outstanding)
```
DSO = (Cuentas por cobrar / Ventas del periodo) x Dias del periodo
```

### Net Cash Flow
```
Net Cash Flow = Total cobrado (inbound) - Total pagado (outbound)
```

## Queries de ejemplo

```bash
# Facturas del mes validadas
cli.js invoices '{"move_type":"out_invoice","state":"posted","date_from":"2026-01-01","date_to":"2026-01-31"}'

# Notas de credito
cli.js invoices '{"move_type":"out_refund","state":"posted","date_from":"2026-01-01"}'

# Facturas impagas
cli.js invoices '{"state":"posted","payment_state":"not_paid"}'

# Cobros del mes
cli.js payments '{"payment_type":"inbound","date_from":"2026-01-01","date_to":"2026-01-31"}'

# Pagos del mes
cli.js payments '{"payment_type":"outbound","date_from":"2026-01-01","date_to":"2026-01-31"}'

# Movimientos de una cuenta contable
cli.js account-lines '{"account_id":100,"date_from":"2026-01-01"}'

# Ver diarios bancarios
cli.js bank-journals '{}'

# Plan de cuentas
cli.js chart-of-accounts '{}'
```

## Saldos bancarios

Para calcular el saldo de una cuenta bancaria de forma confiable:
1. Obtener el diario bancario con `bank-journals`
2. Sumar el campo `balance` de `account-lines` filtrando por la cuenta principal del diario
3. NO usar campos calculados como `current_balance` (pueden fallar en multi-empresa)

```bash
# Saldo de una cuenta
cli.js account-lines '{"account_id":<id_cuenta>,"date_to":"2026-01-31"}'
# Sumar el campo "balance" de todos los resultados (paginar si hay mas de 100)
```
