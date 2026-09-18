import type { OdooClient, OdooDomain } from "../odoo-client.js";

interface StockInput {
  product_name?: string;
  product_code?: string;
  location_name?: string;
  limit?: number;
}

export async function getStock(
  client: OdooClient,
  input: Record<string, unknown>
): Promise<string> {
  const opts = input as unknown as StockInput;
  // Solo ubicaciones internas (almacenes reales)
  const domain: OdooDomain = [["location_id.usage", "=", "internal"]];

  if (opts.product_name) {
    domain.push(["product_id.name", "ilike", opts.product_name]);
  }
  if (opts.product_code) {
    domain.push(["product_id.default_code", "ilike", opts.product_code]);
  }
  if (opts.location_name) {
    domain.push(["location_id.complete_name", "ilike", opts.location_name]);
  }

  const fields = [
    "product_id",
    "location_id",
    "quantity",
    "reserved_quantity",
    "lot_id",
  ];

  const limit = Math.min(opts.limit ?? 50, 100);
  const quants = await client.searchRead("stock.quant", domain, fields, limit);

  if (quants.length === 0) {
    return "No se encontro stock con los filtros especificados.";
  }

  const formatted = quants.map((q: Record<string, unknown>) => ({
    id: q.id,
    producto: Array.isArray(q.product_id) ? q.product_id[1] : "-",
    ubicacion: Array.isArray(q.location_id) ? q.location_id[1] : "-",
    cantidad: q.quantity,
    reservado: q.reserved_quantity,
    disponible: (q.quantity as number) - (q.reserved_quantity as number),
    lote: Array.isArray(q.lot_id) ? q.lot_id[1] : null,
  }));

  return JSON.stringify(formatted, null, 2);
}
