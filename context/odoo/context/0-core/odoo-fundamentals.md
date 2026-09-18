# Odoo Fundamentals

Conocimiento base para operar con Odoo via CLI.

## CLI

Todos los comandos se ejecutan como:
```bash
node ~/.claude/tools/odoo-cli/dist/cli.js <comando> '<opciones_json>'
```

### Comandos disponibles

| Comando | Modelo Odoo | Descripción |
|---------|-------------|-------------|
| `contacts` | res.partner | Buscar contactos, clientes, proveedores |
| `invoices` | account.move | Facturas, notas de crédito |
| `products` | product.product | Catálogo de productos |
| `stock` | stock.quant | Inventario por ubicación |
| `subscriptions` | sale.order | Suscripciones (MRR, planes) |
| `payments` | account.payment | Pagos recibidos/realizados |
| `account-lines` | account.move.line | Líneas de asientos contables |
| `bank-journals` | account.journal | Diarios bancarios |
| `bank-statements` | account.bank.statement.line | Extractos bancarios |
| `chart-of-accounts` | account.account | Plan de cuentas |
| `search` | (cualquiera) | Búsqueda avanzada en cualquier modelo |
| `fields` | (cualquiera) | Ver campos de un modelo |
| `write` | (cualquiera) | Actualizar registros |

### Ejemplo
```bash
# Buscar contacto
node ~/.claude/tools/odoo-cli/dist/cli.js contacts '{"name":"Juan","limit":5}'

# Búsqueda avanzada
node ~/.claude/tools/odoo-cli/dist/cli.js search '{"model":"sale.order","domain":"[[\"state\",\"=\",\"sale\"]]","fields":"name,partner_id,amount_total","limit":10}'
```

## Paginación (CRÍTICO)

La API de Odoo retorna **máximo 100 resultados** por consulta.

### Estrategia de paginación por ID (OBLIGATORIA para datasets grandes)

```bash
# Primera consulta - obtiene IDs más altos (más recientes)
query1 = cli.js search '{"model":"sale.order","domain":"[...]","limit":100}'
# Anotar el ID mínimo obtenido (ej: 1870)

# Segunda consulta - obtiene IDs anteriores
query2 = cli.js search '{"model":"sale.order","domain":"[[\"id\",\"<\",1870],...]","limit":100}'

# Continuar hasta obtener menos de 100 resultados
```

**IMPORTANTE:**
- Siempre consolidar resultados de TODAS las consultas
- Eliminar duplicados por partner_id al contar clientes únicos
- Un cliente puede tener múltiples registros (mismo partner_id, diferentes IDs)

## Campos calculados no filtrables

Estos campos NO se pueden usar en filtros/domain:
- `subscription_count` - campo calculado
- `total_invoiced` - campo calculado
- `credit`, `debit` (en res.partner) - campos calculados

Solución: obtener registros y filtrar manualmente en los resultados.

## Odoo 18 - Problemas conocidos

### Multi-empresa vía API
- Campos calculados como `current_balance` (account.account) filtran por empresa del contexto API
- `current_statement_balance` y `kanban_dashboard` NO son confiables para multi-empresa
- **Solución:** Sumar `balance` de `account.move.line` directamente

### Búsqueda por nombre
- Nombre/apellido parcial funciona mejor que nombre completo
- Ejemplos: "garcia", "lopez", "JUAN CARLOS"
- Si no encuentra, probar variantes del nombre

## Tipos de datos Odoo

| Tipo | Ejemplo en JSON | Notas |
|------|-----------------|-------|
| Many2one | `[id, "nombre"]` | Array de 2 elementos |
| Boolean | `true/false` | |
| Date | `"2026-01-01"` | Formato YYYY-MM-DD |
| Float | `1500.50` | |
| Selection | `"posted"` | String con valor del enum |
| Many2many | `[[4,id]]` agregar, `[[3,id]]` quitar | Comandos Odoo para write |
