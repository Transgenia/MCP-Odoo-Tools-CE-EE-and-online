import type { OdooClient, OdooDomain } from "../odoo-client.js";

export async function searchAccountLines(
  client: OdooClient,
  input: Record<string, unknown>
): Promise<string> {
  const domain: OdooDomain = [["parent_state", "=", "posted"]];

  if (input.account_id) {
    if (Array.isArray(input.account_id)) {
      domain.push(["account_id", "in", input.account_id]);
    } else {
      domain.push(["account_id", "=", input.account_id]);
    }
  }
  if (input.partner_id) {
    domain.push(["partner_id", "=", input.partner_id]);
  }
  if (input.date_from) {
    domain.push(["date", ">=", input.date_from as string]);
  }
  if (input.date_to) {
    domain.push(["date", "<=", input.date_to as string]);
  }
  if (input.has_analytic) {
    // Odoo 18: analytic_distribution is a JSON field, not a many2one
    domain.push(["analytic_distribution", "!=", false]);
  }

  const fields = [
    "account_id", "partner_id", "name", "debit", "credit",
    "balance", "amount_currency", "currency_id", "date",
    "analytic_distribution", "move_id",
  ];

  const limit = Math.min((input.limit as number) ?? 100, 100);
  const results = await client.searchRead("account.move.line", domain, fields, limit);

  if (results.length === 0) {
    return "No se encontraron lineas contables con los filtros especificados.";
  }

  const formatted = results.map((l: Record<string, unknown>) => ({
    id: l.id,
    cuenta: Array.isArray(l.account_id) ? l.account_id[1] : "-",
    cuenta_id: Array.isArray(l.account_id) ? l.account_id[0] : null,
    cliente: Array.isArray(l.partner_id) ? l.partner_id[1] : "-",
    descripcion: l.name || "-",
    debe: l.debit,
    haber: l.credit,
    balance: l.balance,
    monto_moneda: l.amount_currency,
    moneda: Array.isArray(l.currency_id) ? l.currency_id[1] : "-",
    fecha: l.date,
    analitica: l.analytic_distribution || null,
    asiento: Array.isArray(l.move_id) ? l.move_id[1] : "-",
  }));

  return JSON.stringify(formatted, null, 2);
}
