import type { OdooClient } from "../odoo-client.js";

export async function writeRecord(
  client: OdooClient,
  input: Record<string, unknown>
): Promise<string> {
  if (!input.model) {
    return JSON.stringify({ error: "El campo 'model' es requerido (ej: res.users, res.partner, sale.order)" });
  }
  if (!input.ids) {
    return JSON.stringify({ error: "El campo 'ids' es requerido (ej: \"1,2,3\")" });
  }

  const ids = (input.ids as string)
    .split(",")
    .map((id) => parseInt(id.trim(), 10))
    .filter((id) => !isNaN(id));

  if (ids.length === 0) {
    return JSON.stringify({ error: "Debe proporcionar al menos un ID valido." });
  }

  if (!input.values) {
    return JSON.stringify({ error: "El campo 'values' es requerido (ej: '{\"name\":\"Nuevo nombre\"}')" });
  }

  let values: Record<string, unknown>;
  try {
    values = typeof input.values === "string" ? JSON.parse(input.values) : input.values as Record<string, unknown>;
    if (typeof values !== "object" || Array.isArray(values) || values === null) {
      throw new Error("Values must be an object");
    }
  } catch {
    return JSON.stringify({ error: 'Los values deben ser un objeto JSON valido. Ejemplo: {"name":"Nuevo nombre"}' });
  }

  try {
    const result = await client.write(input.model as string, ids, values);
    if (result) {
      return JSON.stringify({ success: true, message: `Registros actualizados exitosamente (IDs: ${ids.join(", ")}) en ${input.model}.` });
    }
    return JSON.stringify({ success: false, message: `La operacion no retorno exito. Verificar que los IDs existan en ${input.model}.` });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return JSON.stringify({ error: `Error al escribir en ${input.model}: ${message}` });
  }
}
