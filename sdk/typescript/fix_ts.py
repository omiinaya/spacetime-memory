import os
import re

# Read files
client = open(os.path.expanduser("~/spacetime-memory/sdk/typescript/client.ts")).read()
mem0 = open(os.path.expanduser("~/spacetime-memory/sdk/typescript/mem0.ts")).read()

# Strip the test marker I just appended
mem0 = mem0.replace("// test marker", "")
client = client.replace("// test marker", "")

# ==================== CLIENT.TS FIXES ====================

old = '  private async _call(reducer: string, args: unknown[]): Promise<void> {'
new = '  async _call(reducer: string, args: unknown[]): Promise<any> {'
client = client.replace(old, new)
print("client: _call visibility/return")

old = '  private async _sqlExec('
new = '  async _sqlExec('
client = client.replace(old, new)
print("client: _sqlExec visibility")

old = '  private async _callWithResult(reducer: string, args: unknown[]): Promise<string> {'
new = '  async _callWithResult(reducer: string, args: unknown[]): Promise<string> {'
client = client.replace(old, new)
print("client: _callWithResult visibility")

old = '  private async _query('
new = '  async _query('
client = client.replace(old, new)
print("client: _query visibility")

# Add _tantivySearch before search() method
search_method_idx = client.find("  async search(")
tantivy_code = '''
  async _tantivySearch(workspaceId: string, query: string, limit: number = 20): Promise<any[]> {
    try {
      await this._call("tantivy_search", [workspaceId, query, limit]);
      const qhash = queryHash(query);
      const rows = await this._query("search_results", workspaceId, { query_hash: qhash });
      if (rows && rows.length) {
        return rows.map((r: any) => r.result).filter(Boolean);
      }
    } catch {
      // tantivy search failed
    }
    return [];
  }

'''
client = client[:search_method_idx] + tantivy_code + client[search_method_idx:]
print("client: added _tantivySearch")

# ==================== MEM0.TS FIXES ====================

old = '  private _client: Client;\n  private _userIdToWs: Map<string, string> = new Map();'
new = '  _client: Client;\n  _userIdToWs: Map<string, string> = new Map();'
mem0 = mem0.replace(old, new)
print("mem0: Memory._client/_userIdToWs public")

old = '  private async _ws(userId?: string): Promise<string> {'
new = '  async _ws(userId?: string): Promise<string> {'
mem0 = mem0.replace(old, new)
print("mem0: Memory._ws public")

old = '  private _ws(userId?: string): string {\n    return this.memory._ws(userId);\n  }'
new = '  async _ws(userId?: string): Promise<string> {\n    return this.memory._ws(userId);\n  }'
mem0 = mem0.replace(old, new)
print("mem0: GraphStore._ws async")

old = '    const wsId = this._ws(userId);\n    const meta = { ...metadata };'
new = '    const wsId = await this._ws(userId);\n    const meta = { ...metadata };'
mem0 = mem0.replace(old, new)
print("mem0: GraphStore.add await _ws")

old = '      const semanticRows = await this.memory._client.search({\n        workspaceId: wsId,\n        query: cleaned,\n        limit: 5,\n        semantic: true,\n      });'
new = '      const semanticRows = await this.memory._client.search(wsId, cleaned, { limit: 5, semantic: true });'
mem0 = mem0.replace(old, new)
print("mem0: search() positional")

old = '        const existingName = existing.label || "";'
new = '        const existingName = (existing.label as string) || "";'
mem0 = mem0.replace(old, new)
print("mem0: existing.label cast")

old = ('          node_type: existing.node_type || entityType,\n'
       '          entity_type: existing.node_type || entityType,\n'
       '          summary: existing.summary || "",\n'
       '          metadata_json: existing.metadata_json || JSON.stringify(meta),\n'
       '          created_at: existing.created_at || 0,')
new = ('          node_type: (existing.node_type as string) || entityType,\n'
       '          entity_type: (existing.node_type as string) || entityType,\n'
       '          summary: (existing.summary as string) || "",\n'
       '          metadata_json: (existing.metadata_json as string) || JSON.stringify(meta),\n'
       '          created_at: (existing.created_at as number) || 0,')
mem0 = mem0.replace(old, new)
print("mem0: existing.* casts")

old = ('      const rows = await this.memory._client._query(\n'
       '        "entity_link",\n'
       '        { entity_name: text },\n'
       '        wsId,\n'
       '      );')
new = ('      const rows = await this.memory._client._query(\n'
       '        "entity_link",\n'
       '        wsId,\n'
       '        { entity_name: text },\n'
       '      );')
mem0 = mem0.replace(old, new)
print("mem0: _query order _addExact")

# Fix GraphStore.search - await _ws
old_sig = ('async search(query: string, options: GraphSearchOptions = {}): Promise<GraphEntity[]> {\n'
           '    const { userId, limit = 10 } = options;\n'
           '    const wsId = this._ws(userId);')
new_sig = ('async search(query: string, options: GraphSearchOptions = {}): Promise<GraphEntity[]> {\n'
           '    const { userId, limit = 10 } = options;\n'
           '    const wsId = await this._ws(userId);')
mem0 = mem0.replace(old_sig, new_sig)
print("mem0: GraphStore.search await _ws")

old = ('          const rows = await this.memory._client._query("kg_node", { id: nid }, wsId);\n'
       '          if (rows.length) {\n'
       '            const n = rows[0];\n'
       '            results.push({\n'
       '              id: n.id || "",\n'
       '              label: n.label || "",\n'
       '              node_type: n.node_type || "entity",\n'
       '              entity_type: n.node_type || "entity",\n'
       '              summary: n.summary || "",\n'
       '              metadata_json: n.metadata_json || "{}",\n'
       '              created_at: n.created_at || 0,')
new = ('          const rows = await this.memory._client._query("kg_node", wsId, { id: nid });\n'
       '          if (rows.length) {\n'
       '            const n = rows[0];\n'
       '            results.push({\n'
       '              id: (n.id as string) || "",\n'
       '              label: (n.label as string) || "",\n'
       '              node_type: (n.node_type as string) || "entity",\n'
       '              entity_type: (n.node_type as string) || "entity",\n'
       '              summary: (n.summary as string) || "",\n'
       '              metadata_json: (n.metadata_json as string) || "{}",\n'
       '              created_at: (n.created_at as number) || 0,')
mem0 = mem0.replace(old, new)
print("mem0: _query order + casts (1st)")

old = ('            const rows = await this.memory._client._query("kg_node", { id: nid }, wsId);\n'
       '            if (rows.length) {\n'
       '              const n = rows[0];\n'
       '              results.push({\n'
       '                id: n.id || "",\n'
       '                label: n.label || "",\n'
       '                node_type: n.node_type || "entity",\n'
       '                entity_type: n.node_type || "entity",\n'
       '                summary: n.summary || "",\n'
       '                metadata_json: n.metadata_json || "{}",\n'
       '                created_at: n.created_at || 0,')
new = ('            const rows = await this.memory._client._query("kg_node", wsId, { id: nid });\n'
       '            if (rows.length) {\n'
       '              const n = rows[0];\n'
       '              results.push({\n'
       '                id: (n.id as string) || "",\n'
       '                label: (n.label as string) || "",\n'
       '                node_type: (n.node_type as string) || "entity",\n'
       '                entity_type: (n.node_type as string) || "entity",\n'
       '                summary: (n.summary as string) || "",\n'
       '                metadata_json: (n.metadata_json as string) || "{}",\n'
       '                created_at: (n.created_at as number) || 0,')
mem0 = mem0.replace(old, new)
print("mem0: _query order + casts (tantivy)")

# Fix GraphStore.getAll - await _ws
old_sig2 = ('async getAll(options: GraphGetAllOptions = {}): Promise<GraphEntity[]> {\n'
            '    const { userId, limit = 100 } = options;\n'
            '    const wsId = this._ws(userId);')
new_sig2 = ('async getAll(options: GraphGetAllOptions = {}): Promise<GraphEntity[]> {\n'
            '    const { userId, limit = 100 } = options;\n'
            '    const wsId = await this._ws(userId);')
mem0 = mem0.replace(old_sig2, new_sig2)
print("mem0: GraphStore.getAll await _ws")

old = '      const rows = await this.memory._client._query("entity_link", {}, wsId);'
new = '      const rows = await this.memory._client._query("entity_link", wsId, {});'
mem0 = mem0.replace(old, new)
print("mem0: _query order getAll")

old = '      const matched = rows.filter((r) => (r.entity_name || "").toLowerCase().includes(q));'
new = '      const matched = rows.filter((r) => ((r.entity_name as string) || "").toLowerCase().includes(q));'
mem0 = mem0.replace(old, new)
print("mem0: entity_name cast")

# Write files
open(os.path.expanduser("~/spacetime-memory/sdk/typescript/client.ts"), "w").write(client)
open(os.path.expanduser("~/spacetime-memory/sdk/typescript/mem0.ts"), "w").write(mem0)
print("\nBOTH WRITTEN OK")
