import type { OdooClient, OdooDomain } from "../odoo-client.js";

interface InvoicesInput {
  partner_name?: string;
  state?: string;
  move_type?: string;
  date_from?: string;
  date_to?: string;
  amount_min?: number;
  amount_max?: number;
  payment_state?: string;
  limit?: number;
}

export async function searchInvoices(
  client: OdooClient,
  input: Record<string, unknown>
): Promise<string> {
  const opts = input as unknown as InvoicesInput;
  const domain: OdooDomain = [];

  // Por defecto solo facturas (no asientos contables)
  if (opts.move_type) {
    domain.push(["move_type", "=", opts.move_type]);
  } else {
    domain.push(["move_type", "in", ["out_invoice", "in_invoice", "out_refund", "in_refund"]]);
  }

  if (opts.partner_name) {
    domain.push(["partner_id.name", "ilike", opts.partner_name]);
  }
  if (opts.state) {
    domain.push(["state", "=", opts.state]);
  }
  if (opts.date_from) {
    domain.push(["invoice_date", ">=", opts.date_from]);
  }
  if (opts.date_to) {
    domain.push(["invoice_date", "<=", opts.date_to]);
  }
  if (opts.amount_min !== undefined) {
    domain.push(["amount_total", ">=", opts.amount_min]);
  }
  if (opts.amount_max !== undefined) {
    domain.push(["amount_total", "<=", opts.amount_max]);
  }
  if (opts.payment_state) {
    domain.push(["payment_state", "=", opts.payment_state]);
  }

  const fields = [
    "name",
    "invoice_date",
    "invoice_date_due",
    "partner_id",
    "amount_total",
    "amount_residual",
    "state",
    "move_type",
    "currency_id",
    "payment_state",
  ];

  const limit = Math.min(opts.limit ?? 50, 100);
  const invoices = await client.searchRead("account.move", domain, fields, limit);

  if (invoices.length === 0) {
    return "No se encontraron facturas con los filtros especificados.";
  }

  const moveTypeLabels: Record<string, string> = {
    out_invoice: "Factura Cliente",
    in_invoice: "Factura Proveedor",
    out_refund: "Nota Credito Cliente",
    in_refund: "Nota Credito Proveedor",
  };

  const stateLabels: Record<string, string> = {
    draft: "Borrador",
    posted: "Validado",
    cancel: "Cancelado",
  };

  const paymentStateLabels: Record<string, string> = {
    not_paid: "No pagada",
    in_payment: "En proceso de pago",
    paid: "Pagada",
    partial: "Pago parcial",
    reversed: "Revertida",
  };

  const formatted = invoices.map((inv: Record<string, unknown>) => ({
    id: inv.id,
    numero: inv.name,
    fecha: inv.invoice_date || "-",
    vencimiento: inv.invoice_date_due || "-",
    cliente: Array.isArray(inv.partner_id) ? inv.partner_id[1] : "-",
    tipo: moveTypeLabels[inv.move_type as string] || inv.move_type,
    total: inv.amount_total,
    pendiente: inv.amount_residual,
    moneda: Array.isArray(inv.currency_id) ? inv.currency_id[1] : "-",
    estado: stateLabels[inv.state as string] || inv.state,
    estado_pago: paymentStateLabels[inv.payment_state as string] || inv.payment_state || "-",
  }));

  return JSON.stringify(formatted, null, 2);
}
