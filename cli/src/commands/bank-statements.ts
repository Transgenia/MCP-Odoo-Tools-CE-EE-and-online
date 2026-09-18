import type { OdooClient, OdooDomain } from "../odoo-client.js";

export async function searchBankStatements(
  client: OdooClient,
  input: Record<string, unknown>
): Promise<string> {
  const domain: OdooDomain = [];

  if (input.unreconciled) {
    domain.push(["is_reconciled", "=", false]);
  }
  if (input.journal_id) {
    if (Array.isArray(input.journal_id)) {
      domain.push(["journal_id", "in", input.journal_id]);
    } else {
      domain.push(["journal_id", "=", input.journal_id]);
    }
  }
  if (input.date_from) {
    domain.push(["date", ">=", input.date_from as string]);
  }
  if (input.date_to) {
    domain.push(["date", "<=", input.date_to as string]);
  }

  const fields = [
    "journal_id", "amount", "currency_id", "date",
    "payment_ref", "partner_id", "is_reconciled",
  ];

  const limit = Math.min((input.limit as number) ?? 50, 100);
  const results = await client.searchRead("account.bank.statement.line", domain, fields, limit);

  if (results.length === 0) {
    return "No se encontraron extractos bancarios con los filtros especificados.";
  }

  const formatted = results.map((s: Record<string, unknown>) => ({
    id: s.id,
    diario: Array.isArray(s.journal_id) ? s.journal_id[1] : "-",
    monto: s.amount,
    moneda: Array.isArray(s.currency_id) ? s.currency_id[1] : "-",
    fecha: s.date,
    referencia: s.payment_ref || "-",
    cliente: Array.isArray(s.partner_id) ? s.partner_id[1] : "-",
    conciliado: s.is_reconciled,
  }));

  return JSON.stringify(formatted, null, 2);
}
