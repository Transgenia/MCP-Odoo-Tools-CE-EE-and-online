# Contactos y Clientes

## CLI relevante
- `contacts` - Buscar contactos, clientes, proveedores

## Modelo: res.partner

### Opciones de busqueda

| Opcion | Tipo | Descripcion |
|--------|------|-------------|
| `name` | string | Busqueda parcial por nombre |
| `email` | string | Busqueda parcial por email |
| `is_customer` | boolean | Solo clientes (customer_rank > 0) |
| `is_supplier` | boolean | Solo proveedores (supplier_rank > 0) |
| `limit` | number | Maximo 100 |

### Campos retornados

- `id`, `nombre`, `email`, `telefono`
- `ciudad`, `pais`
- `es_cliente`, `es_proveedor`

## Tips de busqueda

- Nombre/apellido parcial funciona mejor que nombre completo
- Ejemplos: "garcia", "martinez", "JUAN"
- Si no encuentra, probar variantes del nombre
- Usar `search` con domain custom para filtros avanzados

## Campos custom (x_studio_*)

Muchas instancias de Odoo tienen campos personalizados creados con Odoo Studio. Estos campos empiezan con `x_studio_`. Para descubrirlos:

```bash
# Ver todos los campos de res.partner
cli.js fields '{"model":"res.partner"}'
# Buscar los que empiezan con x_studio en los resultados
```

## Queries de ejemplo

```bash
# Buscar cliente por nombre
cli.js contacts '{"name":"Juan","is_customer":true}'

# Buscar por email
cli.js contacts '{"email":"@gmail.com"}'

# Solo proveedores
cli.js contacts '{"is_supplier":true}'

# Busqueda avanzada con campos extra
cli.js search '{"model":"res.partner","domain":"[[\"customer_rank\",\">\",0]]","fields":"name,email,phone,total_invoiced","limit":20}'
```
