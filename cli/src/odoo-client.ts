import xmlrpc from "xmlrpc";

export interface OdooConfig {
  url: string;
  db: string;
  username: string;
  password: string;
}

export type OdooDomain = Array<string | [string, string, unknown]>;

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "object" && error !== null && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return String(error);
}

export class OdooClient {
  private config: OdooConfig;
  private uid: number | null = null;
  private commonClient: xmlrpc.Client;
  private objectClient: xmlrpc.Client;

  constructor(config: OdooConfig) {
    this.config = config;

    const urlObj = new URL(config.url);
    const isSecure = urlObj.protocol === "https:";
    const port = urlObj.port
      ? parseInt(urlObj.port)
      : isSecure
        ? 443
        : 80;

    const clientOptions = {
      host: urlObj.hostname,
      port,
      path: "/xmlrpc/2/common",
    };

    const objectOptions = {
      host: urlObj.hostname,
      port,
      path: "/xmlrpc/2/object",
    };

    if (isSecure) {
      this.commonClient = xmlrpc.createSecureClient(clientOptions);
      this.objectClient = xmlrpc.createSecureClient(objectOptions);
    } else {
      this.commonClient = xmlrpc.createClient(clientOptions);
      this.objectClient = xmlrpc.createClient(objectOptions);
    }
  }

  async authenticate(): Promise<number> {
    return new Promise((resolve, reject) => {
      this.commonClient.methodCall(
        "authenticate",
        [this.config.db, this.config.username, this.config.password, {}],
        (error, value) => {
          if (error) {
            reject(new Error(`Authentication failed: ${getErrorMessage(error)}`));
            return;
          }
          if (!value || value === false) {
            reject(new Error("Authentication failed: Invalid credentials"));
            return;
          }
          this.uid = value as number;
          resolve(this.uid);
        }
      );
    });
  }

  async searchRead<T = Record<string, unknown>>(
    model: string,
    domain: OdooDomain,
    fields: string[],
    limit = 100,
    offset = 0
  ): Promise<T[]> {
    if (!this.uid) {
      await this.authenticate();
    }

    return new Promise((resolve, reject) => {
      this.objectClient.methodCall(
        "execute_kw",
        [
          this.config.db,
          this.uid,
          this.config.password,
          model,
          "search_read",
          [domain],
          { fields, limit, offset },
        ],
        (error, value) => {
          if (error) {
            reject(new Error(`Search failed: ${getErrorMessage(error)}`));
            return;
          }
          resolve(value as T[]);
        }
      );
    });
  }

  async write(
    model: string,
    ids: number[],
    values: Record<string, unknown>
  ): Promise<boolean> {
    if (!this.uid) {
      await this.authenticate();
    }

    return new Promise((resolve, reject) => {
      this.objectClient.methodCall(
        "execute_kw",
        [
          this.config.db,
          this.uid,
          this.config.password,
          model,
          "write",
          [ids, values],
        ],
        (error, value) => {
          if (error) {
            reject(new Error(`Write failed: ${getErrorMessage(error)}`));
            return;
          }
          resolve(value as boolean);
        }
      );
    });
  }

  async getFields(model: string): Promise<Record<string, unknown>> {
    if (!this.uid) {
      await this.authenticate();
    }

    return new Promise((resolve, reject) => {
      this.objectClient.methodCall(
        "execute_kw",
        [
          this.config.db,
          this.uid,
          this.config.password,
          model,
          "fields_get",
          [],
          { attributes: ["string", "type", "help"] },
        ],
        (error, value) => {
          if (error) {
            reject(new Error(`Fields get failed: ${getErrorMessage(error)}`));
            return;
          }
          resolve(value as Record<string, unknown>);
        }
      );
    });
  }
}
