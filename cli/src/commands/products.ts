import type { OdooClient, OdooDomain } from "../odoo-client.js";

interface ProductsInput {
  name?: string;
  code?: string;
  category?: string;
  type?: string;
  limit?: number;
}

export async function searchProducts(
  client: OdooClient,
  input: Record<string, unknown>
): Promise<string> {
  const opts = input as unknown as ProductsInput;
  const domain: OdooDomain = [["active", "=", true]];

  if (opts.name) {
    domain.push(["name", "ilike", opts.name]);
  }
  if (opts.code) {
    domain.push(["default_code", "ilike", opts.code]);
  }
  if (opts.category) {
    domain.push(["categ_id.name", "ilike", opts.category]);
  }
  if (opts.type) {
    domain.push(["detailed_type", "=", opts.type]);
  }

  const fields = [
    "name",
    "default_code",
    "list_price",
    "standard_price",
    "categ_id",
    "detailed_type",
    "qty_available",
    "virtual_available",
    "uom_id",
  ];

  const limit = Math.min(opts.limit ?? 50, 100);
  const products = await client.searchRead("product.product", domain, fields, limit);

  if (products.length === 0) {
    return "No se encontraron productos con los filtros especificados.";
  }

  const typeLabels: Record<string, string> = {
    product: "Almacenable",
    service: "Servicio",
    consu: "Consumible",
  };

  const formatted = products.map((p: Record<string, unknown>) => ({
    id: p.id,
    nombre: p.name,
    codigo: p.default_code || "-",
    categoria: Array.isArray(p.categ_id) ? p.categ_id[1] : "-",
    tipo: typeLabels[p.detailed_type as string] || p.detailed_type,
    precio_venta: p.list_price,
    costo: p.standard_price,
    stock_disponible: p.qty_available,
    stock_virtual: p.virtual_available,
    unidad: Array.isArray(p.uom_id) ? p.uom_id[1] : "-",
  }));

  return JSON.stringify(formatted, null, 2);
}
