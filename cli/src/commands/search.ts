import type { OdooClient } from "../odoo-client.js";

export async function rawSearch(
  client: OdooClient,
  input: Record<string, unknown>
): Promise<string> {
  if (!input.model) {
    return JSON.stringify({ error: "El campo 'model' es requerido (ej: res.partner, sale.order)" });
  }

  let domain: unknown[];
  try {
    const domainStr = (input.domain as string) ?? "[]";
    domain = JSON.parse(domainStr);
    if (!Array.isArray(domain)) {
      throw new Error("Domain must be an array");
    }
  } catch {
    return JSON.stringify({ error: 'El domain debe ser un array JSON valido. Ejemplo: [["state","=","posted"]]' });
  }

  const fields = input.fields
    ? (input.fields as string).split(",").map((f) => f.trim())
    : ["id", "name", "display_name"];

  const limit = Math.min((input.limit as number) ?? 20, 100);

  try {
    const results = await client.searchRead(
      input.model as string,
      domain as Array<string | [string, string, unknown]>,
      fields,
      limit
    );

    if (results.length === 0) {
      return `No se encontraron registros en ${input.model} con los filtros especificados.`;
    }

    return JSON.stringify(results, null, 2);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return JSON.stringify({ error: `Error al buscar en ${input.model}: ${message}` });
  }
}
