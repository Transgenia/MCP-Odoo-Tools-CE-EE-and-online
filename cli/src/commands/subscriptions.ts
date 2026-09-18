import type { OdooClient, OdooDomain } from "../odoo-client.js";

interface SubscriptionsInput {
  active?: boolean;
  partner_name?: string;
  state?: string; // "3_progress", "5_renewed", "6_churn"
  plan_id?: number; // 1=Mensual, 2=Anual, 18=Semestral
  currency?: string; // "ARS" or "USD"
  date_from?: string;
  date_to?: string;
  limit?: number;
}

export async function searchSubscriptions(
  client: OdooClient,
  input: Record<string, unknown>
): Promise<string> {
  const opts = input as unknown as SubscriptionsInput;
  const domain: OdooDomain = [["is_subscription", "=", true]];

  if (opts.active) {
    domain.push(["subscription_state", "=", "3_progress"]);
  }
  if (opts.state) {
    domain.push(["subscription_state", "=", opts.state]);
  }
  if (opts.partner_name) {
    domain.push(["partner_id.name", "ilike", opts.partner_name]);
  }
  if (opts.plan_id) {
    domain.push(["plan_id", "=", opts.plan_id]);
  }
  if (opts.date_from) {
    domain.push(["start_date", ">=", opts.date_from]);
  }
  if (opts.date_to) {
    domain.push(["start_date", "<=", opts.date_to]);
  }

  const fields = [
    "partner_id", "subscription_state", "plan_id",
    "recurring_monthly", "currency_id", "start_date",
    "end_date", "amount_total",
  ];

  const limit = Math.min((opts.limit as number) ?? 100, 100);
  const results = await client.searchRead("sale.order", domain, fields, limit);

  if (results.length === 0) {
    return "No se encontraron suscripciones con los filtros especificados.";
  }

  const stateLabels: Record<string, string> = {
    "3_progress": "Activa",
    "5_renewed": "Renovada",
    "6_churn": "Baja",
  };

  const formatted = results.map((s: Record<string, unknown>) => ({
    id: s.id,
    cliente: Array.isArray(s.partner_id) ? s.partner_id[1] : "-",
    cliente_id: Array.isArray(s.partner_id) ? s.partner_id[0] : null,
    estado: stateLabels[s.subscription_state as string] || s.subscription_state,
    plan: Array.isArray(s.plan_id) ? s.plan_id[1] : "-",
    mrr: s.recurring_monthly,
    moneda: Array.isArray(s.currency_id) ? s.currency_id[1] : "-",
    inicio: s.start_date || "-",
    fin: s.end_date || "Activa",
    total: s.amount_total,
  }));

  // If currency filter, post-filter
  if (opts.currency) {
    const filtered = formatted.filter(s => s.moneda === opts.currency);
    return JSON.stringify(filtered, null, 2);
  }

  return JSON.stringify(formatted, null, 2);
}
