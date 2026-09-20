#!/usr/bin/env node
import { config } from "dotenv";
import { fileURLToPath } from "url";
import { dirname, join } from "path";
import { OdooClient } from "./odoo-client.js";

// Load .env from the CLI tool directory
const __dirname = dirname(fileURLToPath(import.meta.url));
config({ path: join(__dirname, "..", ".env") });

// Validate config. Credential: API key (Odoo >= 14) or account password
// (Odoo < 14, incl. the <= 12 lines the note below points at the CLI for).
const required = ["ODOO_URL", "ODOO_DB", "ODOO_USER"];
for (const key of required) {
  if (!process.env[key]) {
    console.error(JSON.stringify({ error: `Variable de entorno ${key} no configurada` }));
    process.exit(1);
  }
}
if (!process.env.ODOO_API_KEY && !process.env.ODOO_PASSWORD) {
  console.error(
    JSON.stringify({ error: "Variable de entorno ODOO_API_KEY u ODOO_PASSWORD no configurada (API key en Odoo >= 14, password en Odoo < 14)" })
  );
  process.exit(1);
}

const client = new OdooClient({
  url: process.env.ODOO_URL!,
  db: process.env.ODOO_DB!,
  username: process.env.ODOO_USER!,
  password: (process.env.ODOO_API_KEY || process.env.ODOO_PASSWORD)!,
});

// Import all commands
import { searchContacts } from "./commands/contacts.js";
import { searchInvoices } from "./commands/invoices.js";
import { searchProducts } from "./commands/products.js";
import { getStock } from "./commands/stock.js";
import { searchSubscriptions } from "./commands/subscriptions.js";
import { searchPayments } from "./commands/payments.js";
import { searchAccountLines } from "./commands/account-lines.js";
import { searchBankJournals } from "./commands/bank-journals.js";
import { searchBankStatements } from "./commands/bank-statements.js";
import { getChartOfAccounts } from "./commands/chart-of-accounts.js";
import { rawSearch } from "./commands/search.js";
import { getFieldsInfo } from "./commands/fields.js";
import { writeRecord } from "./commands/write.js";

const commands: Record<string, (client: OdooClient, input: Record<string, unknown>) => Promise<string>> = {
  contacts: searchContacts,
  invoices: searchInvoices,
  products: searchProducts,
  stock: getStock,
  subscriptions: searchSubscriptions,
  payments: searchPayments,
  "account-lines": searchAccountLines,
  "bank-journals": searchBankJournals,
  "bank-statements": searchBankStatements,
  "chart-of-accounts": getChartOfAccounts,
  search: rawSearch,
  fields: getFieldsInfo,
  write: writeRecord,
};

async function main() {
  const [command, optionsJson] = process.argv.slice(2);

  if (!command || command === "help") {
    console.log(JSON.stringify({
      usage: "odoo-cli <command> '<json_options>'",
      commands: Object.keys(commands),
    }, null, 2));
    process.exit(0);
  }

  const handler = commands[command];
  if (!handler) {
    console.error(JSON.stringify({ error: `Comando desconocido: ${command}`, available: Object.keys(commands) }));
    process.exit(1);
  }

  let options: Record<string, unknown> = {};
  if (optionsJson) {
    try {
      options = JSON.parse(optionsJson);
    } catch {
      console.error(JSON.stringify({ error: "Las opciones deben ser JSON válido" }));
      process.exit(1);
    }
  }

  try {
    const result = await handler(client, options);
    console.log(result);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(JSON.stringify({ error: message }));
    process.exit(1);
  }
}

main();
