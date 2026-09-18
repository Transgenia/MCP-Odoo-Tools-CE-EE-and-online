# Inventario y Stock

## CLI relevante
- `stock` - Consultar stock por producto/ubicación

## Modelo: stock.quant

Solo consulta ubicaciones internas (almacenes reales).

### Opciones de búsqueda

| Opción | Tipo | Descripción |
|--------|------|-------------|
| `product_name` | string | Búsqueda parcial por producto |
| `product_code` | string | Búsqueda por SKU |
| `location_name` | string | Búsqueda por ubicación |
| `limit` | number | Máximo 100 |

### Campos retornados

- `id`, `producto`, `ubicacion`
- `cantidad`, `reservado`, `disponible` (cantidad - reservado)
- `lote`

## Queries

```bash
# Todo el stock
cli.js stock '{}'

# Stock de un producto
cli.js stock '{"product_name":"nombre"}'

# Stock por ubicación
cli.js stock '{"location_name":"Almacén"}'
```
