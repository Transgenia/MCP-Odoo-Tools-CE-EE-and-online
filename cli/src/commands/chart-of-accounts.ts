import type { OdooClient, OdooDomain } from "../odoo-client.js";

export async function getChartOfAccounts(
  client: OdooClient,
  input: Record<string, unknown>
): Promise<string> {
  const domain: OdooDomain = [];

  if (input.code) {
    domain.push(["code", "ilike", input.code as string]);
  }
  if (input.name) {
    domain.push(["name", "ilike", input.name as string]);
  }
  if (input.account_type) {
    domain.push(["account_type", "=", input.account_type as string]);
  }
  if (input.company_id) {
    domain.push(["company_ids", "in", [input.company_id]]);
  }

  const fields = [
    "name", "code", "account_type", "reconcile",
    "company_ids", "current_balance",
  ];

  const limit = Math.min((input.limit as number) ?? 100, 100);
  const results = await client.searchRead("account.account", domain, fields, limit);

  if (results.length === 0) {
    return "No se encontraron cuentas contables con los filtros especificados.";
  }

  const formatted = results.map((a: Record<string, unknown>) => ({
    id: a.id,
    codigo: a.code,
    nombre: a.name,
    tipo: a.account_type,
    conciliable: a.reconcile,
    saldo: a.current_balance,
  }));

  return JSON.stringify(formatted, null, 2);
}
