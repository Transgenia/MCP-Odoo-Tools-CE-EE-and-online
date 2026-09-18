import type { OdooClient } from "../odoo-client.js";

export async function getFieldsInfo(
  client: OdooClient,
  input: Record<string, unknown>
): Promise<string> {
  if (!input.model) {
    return JSON.stringify({ error: "El campo 'model' es requerido (ej: res.partner, sale.order)" });
  }

  try {
    const fields = await client.getFields(input.model as string);

    const simplified = Object.entries(fields).map(([name, info]) => {
      const fieldInfo = info as Record<string, unknown>;
      return {
        campo: name,
        tipo: fieldInfo.type,
        descripcion: fieldInfo.string,
      };
    });

    return JSON.stringify(simplified, null, 2);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return JSON.stringify({ error: `Error al obtener campos de ${input.model}: ${message}` });
  }
}
