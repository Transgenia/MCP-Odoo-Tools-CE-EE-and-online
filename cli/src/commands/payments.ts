import type { OdooClient, OdooDomain } from "../odoo-client.js";

export async function searchPayments(
  client: OdooClient,
  input: Record<string, unknown>
): Promise<string> {
  const domain: OdooDomain = [];

  // Odoo 18.2: payment states are draft, in_process, paid, cancelled
  if (input.state) {
    domain.push(["state", "=", input.state]);
  } else {
    // Default: confirmed payments (exclude draft and cancelled)
    domain.push(["state", "in", ["in_process", "paid"]]);
  }

  if (input.payment_type) {
    domain.push(["payment_type", "=", input.payment_type]); // "inbound" or "outbound"
  }
  if (input.partner_name) {
    domain.push(["partner_id.name", "ilike", input.partner_name as string]);
  }
  if (input.date_from) {
    domain.push(["date", ">=", input.date_from as string]);
  }
  if (input.date_to) {
    domain.push(["date", "<=", input.date_to as string]);
  }
  if (input.journal_id) {
    domain.push(["journal_id", "=", input.journal_id]);
  }

  const fields = [
    "partner_id", "payment_type", "amount", "currency_id",
    "date", "journal_id", "state", "payment_method_line_id",
  ];

  const limit = Math.min((input.limit as number) ?? 50, 100);
  const results = await client.searchRead("account.payment", domain, fields, limit);

  if (results.length === 0) {
    return "No se encontraron pagos con los filtros especificados.";
  }

  const typeLabels: Record<string, string> = {
    inbound: "Cobro",
    outbound: "Pago",
  };

  const stateLabels: Record<string, string> = {
    draft: "Borrador",
    in_process: "En proceso",
    paid: "Pagado",
    cancelled: "Cancelado",
  };

  const formatted = results.map((p: Record<string, unknown>) => ({
    id: p.id,
    cliente: Array.isArray(p.partner_id) ? p.partner_id[1] : "-",
    tipo: typeLabels[p.payment_type as string] || p.payment_type,
    monto: p.amount,
    moneda: Array.isArray(p.currency_id) ? p.currency_id[1] : "-",
    fecha: p.date,
    diario: Array.isArray(p.journal_id) ? p.journal_id[1] : "-",
    estado: stateLabels[p.state as string] || p.state,
  }));

  return JSON.stringify(formatted, null, 2);
}
