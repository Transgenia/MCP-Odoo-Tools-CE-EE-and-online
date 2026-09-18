import type { OdooClient, OdooDomain } from "../odoo-client.js";

interface ContactsInput {
  name?: string;
  email?: string;
  is_customer?: boolean;
  is_supplier?: boolean;
  limit?: number;
}

export async function searchContacts(
  client: OdooClient,
  input: Record<string, unknown>
): Promise<string> {
  const opts = input as unknown as ContactsInput;
  const domain: OdooDomain = [];

  if (opts.name) {
    domain.push(["name", "ilike", opts.name]);
  }
  if (opts.email) {
    domain.push(["email", "ilike", opts.email]);
  }
  if (opts.is_customer) {
    domain.push(["customer_rank", ">", 0]);
  }
  if (opts.is_supplier) {
    domain.push(["supplier_rank", ">", 0]);
  }

  const fields = [
    "name",
    "email",
    "phone",
    "street",
    "city",
    "country_id",
    "customer_rank",
    "supplier_rank",
  ];

  const limit = Math.min(opts.limit ?? 50, 100);
  const contacts = await client.searchRead("res.partner", domain, fields, limit);

  if (contacts.length === 0) {
    return "No se encontraron contactos con los filtros especificados.";
  }

  const formatted = contacts.map((c: Record<string, unknown>) => ({
    id: c.id,
    nombre: c.name,
    email: c.email || "-",
    telefono: c.phone || "-",
    ciudad: c.city || "-",
    pais: Array.isArray(c.country_id) ? c.country_id[1] : "-",
    es_cliente: (c.customer_rank as number) > 0,
    es_proveedor: (c.supplier_rank as number) > 0,
  }));

  return JSON.stringify(formatted, null, 2);
}
