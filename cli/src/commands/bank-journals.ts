import type { OdooClient, OdooDomain } from "../odoo-client.js";

export async function searchBankJournals(
  client: OdooClient,
  input: Record<string, unknown>
): Promise<string> {
  const domain: OdooDomain = [["type", "=", "bank"]];

  if (input.name) {
    domain.push(["name", "ilike", input.name as string]);
  }
  if (input.code) {
    domain.push(["code", "ilike", input.code as string]);
  }
  if (input.currency_id) {
    domain.push(["currency_id", "=", input.currency_id]);
  }

  const fields = [
    "name", "code", "default_account_id", "suspense_account_id",
    "currency_id", "company_id", "bank_account_id",
  ];

  const limit = Math.min((input.limit as number) ?? 50, 100);
  const results = await client.searchRead("account.journal", domain, fields, limit);

  if (results.length === 0) {
    return "No se encontraron diarios bancarios.";
  }

  const formatted = results.map((j: Record<string, unknown>) => ({
    id: j.id,
    nombre: j.name,
    codigo: j.code,
    cuenta_principal: Array.isArray(j.default_account_id) ? { id: j.default_account_id[0], nombre: j.default_account_id[1] } : null,
    cuenta_suspense: Array.isArray(j.suspense_account_id) ? { id: j.suspense_account_id[0], nombre: j.suspense_account_id[1] } : null,
    moneda: Array.isArray(j.currency_id) ? j.currency_id[1] : "ARS (default)",
    empresa: Array.isArray(j.company_id) ? j.company_id[1] : "-",
  }));

  return JSON.stringify(formatted, null, 2);
}
