import { Client, ClientOptions } from "./client";

export interface HonchoConfig {
  host?: string; port?: number|string; db?: string; appName?: string;
}

export interface SessionResponse { id: string; peer_id: string; location: string; created_at: string; }
export interface MessageResponse { id: string; session_id: string; content: string; role: string; created_at: string; }
export interface SyncPage<T> { items: T[]; has_more: boolean; total?: number; }

export class Peer {
  constructor(private _client: Client, private _ws: string, public id: string, public name: string) {}

  async message(sessionId: string, content: string, role: string = "user"): Promise<MessageResponse> {
    await this._client.store(this._ws, content, { memoryType: "honcho_peer_"+this.id });
    return { id: "msg_"+Date.now(), session_id: sessionId, content, role, created_at: new Date().toISOString() };
  }

  async chat(sessionId: string, content: string): Promise<MessageResponse> {
    return this.message(sessionId, content, "user");
  }

  async sessions(limit: number = 100): Promise<SyncPage<SessionResponse>> {
    const rows = await this._client._call("get_user_memories", ["honcho_peer_"+this.id, this._ws]);
    return { items: (rows||[]).map((r:any) => ({ id: r.id, peer_id: this.id, location: "", created_at: r.created_at?new Date(Number(r.created_at)*1000).toISOString():new Date().toISOString() })), has_more: false };
  }
}

export class Honcho {
  _client: Client; _wsCache: Map<string,string> = new Map();

  constructor(config: HonchoConfig = {}) {
    this._client = new Client({ host: config.host, port: config.port, database: config.db } as ClientOptions);
  }

  async _resolveApp(appName: string): Promise<string> {
    const cached = this._wsCache.get(appName);
    if (cached) return cached;
    const ws = appName.replace(/[^a-zA-Z0-9_-]/g, "_");
    this._wsCache.set(appName, ws);
    return ws;
  }

  close(): void {}

  async createPeer(name: string): Promise<Peer> {
    const ws = await this._resolveApp("default");
    return new Peer(this._client, ws, "peer_"+Date.now(), name);
  }

  async getPeer(peerId: string): Promise<Peer|null> {
    const ws = await this._resolveApp("default");
    return new Peer(this._client, ws, peerId, "");
  }

  async createSession(peerId: string, location?: string): Promise<SessionResponse> {
    return { id: "session_"+Date.now(), peer_id: peerId, location: location||"default", created_at: new Date().toISOString() };
  }

  async getSession(sessionId: string): Promise<SessionResponse|null> { return null; }

  async listSessions(peerId: string, limit?: number): Promise<SyncPage<SessionResponse>> {
    return { items: [], has_more: false };
  }

  async createMessage(sessionId: string, content: string, role?: string): Promise<MessageResponse> {
    const ws = await this._resolveApp("default");
    await this._client.store(ws, content, { memoryType: "honcho" });
    return { id: "msg_"+Date.now(), session_id: sessionId, content, role: role||"user", created_at: new Date().toISOString() };
  }

  async getMessages(sessionId: string, limit?: number): Promise<MessageResponse[]> {
    const ws = await this._resolveApp("default");
    const rows = await this._client._call("get_user_memories", ["honcho", ws]);
    return (rows||[]).map((r:any) => ({ id: r.id, session_id: sessionId, content: r.content||r.summary||"", role: "user", created_at: r.created_at?new Date(Number(r.created_at)*1000).toISOString():new Date().toISOString() }));
  }

  async search(query: string, limit?: number): Promise<MessageResponse[]> {
    const ws = await this._resolveApp("default");
    const results = await this._client.search(ws, query, { limit: limit||10, semantic: true });
    return results.map((r:any) => ({ id: r.id||"", session_id: "", content: r.content||"", role: "user", created_at: new Date().toISOString() }));
  }
}
