import { Client, ClientOptions } from "./client";

export interface HindsightConfig {
  baseUrl?: string; apiKey?: string; host?: string; port?: number|string; db?: string;
}

export interface RetainResponse { id: string; content: string; bank_id: string; timestamp: string; }
export interface RecallResult { id: string; content: string; score: number; }
export interface RecallResponse { results: RecallResult[]; }
export interface ReflectResponse { reflection: string; facts?: string[]; directives?: string[]; mental_models?: string[]; }
export interface FileRetainResponse { id: string; filename: string; bank_id: string; }
export interface CreateBankResponse { id: string; }
export interface CreateMentalModelResponse { id: string; }
export interface CreateDirectiveResponse { id: string; }

export class HindsightDocumentsAPI {
  constructor(private _h: Hindsight) {}
  async list(bankId: string): Promise<any[]> {
    const ws = await this._h._resolveBank(bankId);
    const rows = await this._h._client.listNotes(ws);
    return rows || [];
  }
  async get(bankId: string, documentId: string): Promise<any> {
    const ws = await this._h._resolveBank(bankId);
    const rows = await this._h._client._call("sql", ["SELECT * FROM document WHERE id='"+documentId+"'"]);
    return rows?.length ? rows[0] : null;
  }
  async delete(bankId: string, documentId: string): Promise<void> {
    try { await this._h._client.deleteNote(documentId); } catch {}
  }
}

export class HindsightEntitiesAPI {
  constructor(private _h: Hindsight) {}
  async list(bankId: string): Promise<any[]> {
    const ws = await this._h._resolveBank(bankId);
    const rows = await this._h._client._call("sql", ["SELECT * FROM kg_node WHERE workspace_id='"+ws+"' LIMIT 100"]);
    return rows || [];
  }
  async get(bankId: string, entityId: string): Promise<any> {
    const rows = await this._h._client._call("sql", ["SELECT * FROM kg_node WHERE id='"+entityId+"'"]);
    return rows?.length ? rows[0] : null;
  }
  async delete(bankId: string, entityId: string): Promise<void> {
    try { await this._h._client._call("deactivate_node", [entityId]); } catch {}
  }
}

export class HindsightOperationsAPI {
  constructor(private _h: Hindsight) {}
  async list(bankId: string): Promise<any[]> {
    const ws = await this._h._resolveBank(bankId);
    const rows = await this._h._client._call("sql", ["SELECT * FROM change_event WHERE workspace_id='"+ws+"' LIMIT 100"]);
    return rows || [];
  }
}

export class HindsightMonitoringAPI {
  constructor(private _h: Hindsight) {}
  async health(): Promise<Record<string,any>> {
    try {
      const resp = await fetch((this._h as any)._baseUrl+"/health");
      if (resp.ok) return { status: "healthy", timestamp: new Date().toISOString() };
    } catch {}
    return { status: "unreachable" };
  }
}

export class HindsightFilesShell {
  constructor(private _h: Hindsight) {}
  async upload(bankId: string, filePath: string): Promise<FileRetainResponse> {
    const ws = await this._h._resolveBank(bankId);
    // file system not available in browser/deno - store path as metadata
    await this._h._client.store(ws, "file: "+filePath, { memoryType: "hindsight_file" });
    return { id: "file_"+Date.now(), filename: filePath, bank_id: bankId };
  }
}

export class Hindsight {
  _client: Client; _wsCache: Map<string,string> = new Map();
  documents: HindsightDocumentsAPI;
  entities: HindsightEntitiesAPI;
  operations: HindsightOperationsAPI;
  monitoring: HindsightMonitoringAPI;
  files: HindsightFilesShell;

  constructor(config: HindsightConfig = {}) {
    (this as any)._baseUrl = config.baseUrl || "http://127.0.0.1:9090";
    this._client = new Client({ host: config.host, port: config.port, database: config.db } as ClientOptions);
    this.documents = new HindsightDocumentsAPI(this);
    this.entities = new HindsightEntitiesAPI(this);
    this.operations = new HindsightOperationsAPI(this);
    this.monitoring = new HindsightMonitoringAPI(this);
    this.files = new HindsightFilesShell(this);
  }

  async _resolveBank(bankId: string): Promise<string> {
    const cached = this._wsCache.get(bankId);
    if (cached) return cached;
    const ws = bankId.replace(/[^a-zA-Z0-9_-]/g, "_");
    this._wsCache.set(bankId, ws);
    return ws;
  }

  close(): void {}

  async retain(bankId: string, content: string, options?: { timestamp?: string; context?: Record<string,unknown> }): Promise<RetainResponse> {
    const ws = await this._resolveBank(bankId);
    const meta = { ...(options?.context||{}), timestamp: options?.timestamp||new Date().toISOString() };
    await this._client.store(ws, content, { memoryType: "hindsight" });
    return { id: "mem_"+Date.now(), content, bank_id: bankId, timestamp: meta.timestamp };
  }

  async retainBatch(bankId: string, items: Array<{ content: string }>): Promise<RetainResponse[]> {
    const results: RetainResponse[] = [];
    for (const item of items) results.push(await this.retain(bankId, item.content));
    return results;
  }

  async retainFiles(bankId: string, filePaths: string[]): Promise<FileRetainResponse[]> {
    const results: FileRetainResponse[] = [];
    for (const fp of filePaths) results.push(await this.files.upload(bankId, fp));
    return results;
  }

  async recall(bankId: string, query: string, options?: { types?: string[]; limit?: number }): Promise<RecallResponse> {
    const ws = await this._resolveBank(bankId);
    const limit = options?.limit || 10;
    let results = await this._client.search(ws, query, { limit, semantic: true });
    if (options?.types?.length) {
      results = results.filter((r:any) => options.types!.includes(r.memory_type || ""));
    }
    return { results: results.map((r:any) => ({ id: r.id||"", content: r.content||r.summary||"", score: r.score||0 })) };
  }

  async reflect(bankId: string, query: string, _options?: Record<string,unknown>): Promise<ReflectResponse> {
    const ws = await this._resolveBank(bankId);
    const memories = await this._client.search(ws, query, { limit: 5, semantic: true });
    const context = memories.map((r:any) => r.content||r.summary||"").join("\n");
    return { reflection: "Reflected on: "+query+"\nContext: "+context.substring(0,500), facts: [], directives: [], mental_models: [] };
  }

  async createBank(name: string, config?: Record<string,unknown>): Promise<CreateBankResponse> {
    const ws = await this._resolveBank(name);
    const existing = await this._client._call("sql", ["SELECT id FROM workspace WHERE name='"+ws+"'"]);
    if (!existing?.length) {
      await this._client._call("create_workspace", [ws]);
    }
    if (config) {
      await this._client.createNote(ws, "bank_config", JSON.stringify(config));
    }
    return { id: ws };
  }

  async listMemories(bankId: string, options?: { limit?: number }): Promise<{ units: any[]; total: number }> {
    const ws = await this._resolveBank(bankId);
    const rows = await this._client.listMemories(ws, { limit: options?.limit || 100 });
    return { units: rows || [], total: (rows||[]).length };
  }
}
