# Catálogo de Productos

## CLI relevante
- `products` - Buscar productos
- `fields` - Ver campos del modelo product.product

## Modelo: product.product

### Opciones de búsqueda

| Opción | Tipo | Descripción |
|--------|------|-------------|
| `name` | string | Búsqueda parcial por nombre |
| `code` | string | Búsqueda por código/SKU |
| `category` | string | Búsqueda por categoría |
| `type` | string | "product" (almacenable), "service", "consu" (consumible) |
| `limit` | number | Máximo 100 |

### Campos retornados

- `id`, `nombre`, `codigo`, `categoria`, `tipo`
- `precio_venta` (list_price), `costo` (standard_price)
- `stock_disponible`, `stock_virtual`, `unidad`

## Queries

```bash
# Todos los productos
cli.js products '{}'

# Buscar por nombre
cli.js products '{"name":"Plan"}'

# Solo servicios
cli.js products '{"type":"service"}'

# Por categoría
cli.js products '{"category":"Suscripción"}'

# Ver campos disponibles
cli.js fields '{"model":"product.product"}'
```
