/**
 * Compounder — knowledge compounder for spacetime-memory.
 *
 * Turns interactions into persistent knowledge by implementing the "LLM Wiki"
 * pattern from Karpathy: every query, store, and synthesis can generate new
 * wiki pages, update entity summaries, and grow the knowledge base
 * compoundingly, rather than each interaction being a stateless query against
 * raw memories.
 *
 * All methods degrade gracefully returning empty/null results when LLM
 * features are not configured.
 *
 * Usage:
 * ```typescript
 * import { Client, Compounder } from "spacetime-memory";
 * const client = new Client();
 * const cp = new Compounder(client);
 *
 * const result = await cp.storeAnswer(
 *   "What's the relationship between neural nets and evolution?",
 *   "Both are optimization processes...",
 *   { sourceMemoryIds: ["mem_123"] },
 * );
 * const links = await cp.suggestConnections("ws1");
 * const stats = await cp.crossLink("ws1");
 * const lint = await cp.lintWorkspace("ws1");
 * ```
 */

import { Client, SearchResult } from "./client";

// ---------------------------------------------------------------------------
// Result types
// ---------------------------------------------------------------------------

export interface CompounderCrossLinkResult {
  linksCreated: number;
  pairsChecked: number;
}

export interface LintResult {
  orphans: Array<{ id: string; label: string; nodeType: string }>;
  missingCrossrefs: Array<{
    entityId: string;
    entityType: string;
    mentionedLabel: string;
    targetNodeId: string;
  }>;
  noteOrphans: Array<{ id: string; title: string; reason: string }>;
  contradictions: Array<{
    idA: string;
    idB: string;
    contentA: string;
    contentB: string;
    explanation: string;
  }>;
  summary: {
    orphanCount: number;
    missingCrossrefCount: number;
    noteOrphanCount: number;
    contradictionCount: number;
    totalIssues: number;
  };
}

export interface SuggestConnectionResult {
  sourceId: string;
  targetId: string;
  sourceLabel: string;
  targetLabel: string;
  commonNeighbours: string[];
  commonCount: number;
}

export interface StoreAnswerOptions {
  workspaceId?: string;
  title?: string;
  sourceMemoryIds?: string[];
  embed?: boolean;
  skipDuplicates?: boolean;
  duplicateThreshold?: number;
}

export interface EntityPageResult {
  node: Record<string, unknown> | null;
  note: Record<string, unknown>;
}

export interface OverviewResult {
  note: Record<string, unknown>;
}

export interface IngestSourceResult {
  note: Record<string, unknown>;
  entities: Record<string, unknown>[];
  links: string[];
  contradictions: Array<{
    memoryId: string;
    existingContent: string;
    explanation: string;
  }>;
}

export interface StoreAnswerResultEx {
  note: Record<string, unknown>;
  entities: Array<{ id: string; label: string }>;
  links: string[];
  duplicateOf?: string;
  duplicateScore?: number;
}

export class Compounder {
  private _client: Client;

  constructor(client: Client) {
    this._client = client;
  }

  // -----------------------------------------------------------------------
  //  1. searchEntities
  // -----------------------------------------------------------------------

  /**
   * Search knowledge-graph entities by label, type, or semantic query.
   *
   * @param workspaceId  - Target workspace (default "default").
   * @param opts         - label, nodeType, semanticQuery, limit (20).
   */
  async searchEntities(
    workspaceId: string = "default",
    opts?: { label?: string; nodeType?: string; semanticQuery?: string; limit?: number },
  ): Promise<Record<string, unknown>[]> {
    const label = opts?.label;
    const nodeType = opts?.nodeType;
    const semanticQuery = opts?.semanticQuery;
    const limit = opts?.limit ?? 20;

    // Structured filter
    const filter: Record<string, string> = {};
    if (label) filter.label = label;
    if (nodeType) filter.node_type = nodeType;

    let filtered: Record<string, unknown>[] = [];
    if (Object.keys(filter).length > 0) {
      filtered = await (this._client as any)._query("kg_node", workspaceId, filter);
    }

    // Semantic search
    const semanticIds = new Set<string>();
    if (semanticQuery) {
      const hits = await this._client.search(workspaceId, semanticQuery, { limit, semantic: true });
      for (const r of hits) {
        if (r.entity_type === "node" && r.entity_id) semanticIds.add(r.entity_id);
      }
    }

    let semantic: Record<string, unknown>[] = [];
    if (semanticIds.size > 0) {
      const all = await (this._client as any)._query("kg_node", workspaceId, {});
      const map: Record<string, Record<string, unknown>> = {};
      for (const n of all) { const id = n.id as string; if (id) map[id] = n; }
      for (const id of semanticIds) if (map[id]) semantic.push(map[id]);
    }

    // Merge (semantic first, deduped)
    const seen = new Set<string>();
    const merged: Record<string, unknown>[] = [];
    for (const n of semantic) {
      const id = n.id as string;
      if (id && !seen.has(id)) { merged.push(n); seen.add(id); }
    }
    for (const n of filtered) {
      const id = n.id as string;
      if (id && !seen.has(id)) { merged.push(n); seen.add(id); }
    }
    return merged.slice(0, limit);
  }

  // -----------------------------------------------------------------------
  //  2. findNearDuplicates
  // -----------------------------------------------------------------------

  /**
   * Find semantically-similar memories above a score threshold (default 0.92).
   */
  async findNearDuplicates(
    content: string,
    workspaceId: string = "default",
    opts?: { threshold?: number; limit?: number },
  ): Promise<SearchResult[]> {
    const threshold = opts?.threshold ?? 0.92;
    if (!content.trim()) return [];
    const results = await this._client.search(workspaceId, content, {
      limit: opts?.limit ?? 5,
      semantic: true,
    });
    return results.filter((r) => (r.score ?? 0) >= threshold);
  }

  // -----------------------------------------------------------------------
  //  3. storeAnswer  —  persist a Q&A as a wiki page + KG entities
  // -----------------------------------------------------------------------

  async storeAnswer(
    query: string,
    answer: string,
    opts?: StoreAnswerOptions,
  ): Promise<StoreAnswerResultEx> {
    const wsId = opts?.workspaceId ?? "default";
    const title = opts?.title ?? this._generateTitle(query, answer);
    const embed = opts?.embed ?? true;
    const skipDupes = opts?.skipDuplicates ?? true;
    const dupThresh = opts?.duplicateThreshold ?? 0.92;

    if (!answer.trim()) return { note: {}, entities: [], links: [] };

    // Duplicate check
    if (skipDupes) {
      const dupes = await this.findNearDuplicates(answer, wsId, { threshold: dupThresh, limit: 3 });
      if (dupes.length > 0) {
        const best = dupes[0];
        return {
          note: best as unknown as Record<string, unknown>,
          entities: [],
          links: [],
          duplicateOf: best.entity_id ?? "",
          duplicateScore: best.score ?? 0,
        };
      }
    }

    // Create note
    const page = this._formatAnswerPage(query, answer, opts?.sourceMemoryIds);
    await this._client.createNote(wsId, title, page, { embed });

    const note = await this._resolveNote(wsId, title);
    const result: StoreAnswerResultEx = { note, entities: [], links: [] };
    const noteId = note?.id ?? "";

    // Extract entities via regex (capitalised multi-word phrases)
    const entityRe = /\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b/g;
    const seen = new Set<string>();
    const entities: string[] = [];
    for (const m of answer.match(entityRe) ?? []) {
      const c = m.trim();
      if (c.length < 3 || c.length > 60 || seen.has(c.toLowerCase())) continue;
      seen.add(c.toLowerCase());
      entities.push(c);
    }

    // Create KG nodes + link to note
    for (const label of entities.slice(0, 10)) {
      try {
        await (this._client as any)._call("create_node", [wsId, label, "concept", "", "{}"]);
        const rows = await (this._client as any)._sqlExec(
          `SELECT id FROM kg_node WHERE workspace_id = :ws AND label = :label`,
          { ws: wsId, label },
        );
        if (rows.length > 0) {
          const nodeId = rows[rows.length - 1].id as string;
          if (noteId) {
            await (this._client as any)._call("create_edge", [
              wsId, nodeId, noteId, "informed_by", 1.0, "INFERRED", "{}", "",
            ]);
          }
          result.entities.push({ id: nodeId, label });
        }
      } catch { /* best-effort */ }
    }

    // Link to source memories
    for (const sid of opts?.sourceMemoryIds ?? []) {
      if (!noteId) break;
      try {
        await (this._client as any)._call("create_edge", [
          wsId, noteId, sid, "informed_by", 0.8, "INFERRED", "{}", "",
        ]);
        result.links.push(sid);
      } catch { /* best-effort */ }
    }

    // Update index & log
    await this._updateIndex(wsId, title, note, query.slice(0, 100));
    await this._log(wsId, "store_answer", `'${title}' (${result.entities.length} entities)`);
    return result;
  }

  // -----------------------------------------------------------------------
  //  4. storeAnswers  —  batch Q&A
  // -----------------------------------------------------------------------

  async storeAnswers(
    qaPairs: [string, string][],
    workspaceId: string = "default",
    opts?: Omit<StoreAnswerOptions, "title">,
  ): Promise<StoreAnswerResultEx[]> {
    if (!qaPairs.length) return [];
    const results: StoreAnswerResultEx[] = [];
    for (const [q, a] of qaPairs) {
      try {
        results.push(
          await this.storeAnswer(q, a, {
            workspaceId,
            sourceMemoryIds: opts?.sourceMemoryIds,
            embed: opts?.embed ?? true,
            skipDuplicates: opts?.skipDuplicates ?? true,
            duplicateThreshold: opts?.duplicateThreshold ?? 0.92,
          }),
        );
      } catch {
        results.push({ note: {}, entities: [], links: [] });
      }
    }
    const ee = results.reduce((s, r) => s + r.entities.length, 0);
    const ll = results.reduce((s, r) => s + r.links.length, 0);
    await this._log(workspaceId, "store_answers", `${qaPairs.length} pairs (${ee} entities, ${ll} links)`);
    return results;
  }

  // -----------------------------------------------------------------------
  //  5. crossLink  —  connect semantically related memories
  // -----------------------------------------------------------------------

  async crossLink(
    workspaceId: string = "default",
    opts?: { limit?: number; similarityThreshold?: number },
  ): Promise<CompounderCrossLinkResult> {
    const limit = opts?.limit ?? 50;
    const threshold = opts?.similarityThreshold ?? 0.7;

    let memories: Record<string, unknown>[] =
      (await (this._client as any)._query("memory", workspaceId, {})) ?? [];
    if (!memories.length) return { linksCreated: 0, pairsChecked: 0 };

    memories = memories
      .sort((a: any, b: any) => (b.created_at ?? 0) - (a.created_at ?? 0))
      .slice(0, limit);

    let created = 0;
    let checked = 0;

    for (const mem of memories) {
      const mid = mem.id as string;
      const content = mem.content as string;
      if (!mid || !content || content.length < 20) continue;

      const similar = await this._client.search(workspaceId, content, { limit: 5, semantic: true });
      for (const m of similar) {
        const matchId = m.entity_id ?? "";
        if (!matchId || matchId === mid) continue;
        checked++;
        if (await this._linked(mid, matchId)) continue;
        if ((m.score ?? 0) >= threshold) {
          try {
            await (this._client as any)._call("create_edge", [
              workspaceId, mid, matchId, "related_to", m.score ?? 0, "INFERRED", "{}", "",
            ]);
            created++;
          } catch { /* best-effort */ }
        }
      }
    }
    return { linksCreated: created, pairsChecked: checked };
  }

  // -----------------------------------------------------------------------
  //  6. suggestConnections  —  triangle-count heuristic
  // -----------------------------------------------------------------------

  async suggestConnections(
    workspaceId: string = "default",
    limit: number = 50,
  ): Promise<SuggestConnectionResult[]> {
    const edges: Record<string, unknown>[] =
      (await (this._client as any)._query("kg_edge", workspaceId, {})) ?? [];
    const nodes: Record<string, unknown>[] =
      (await (this._client as any)._query("kg_node", workspaceId, {})) ?? [];
    if (nodes.length < 2) return [];

    const adj: Record<string, Set<string>> = {};
    for (const e of edges) {
      const s = e.source_node_id as string;
      const t = e.target_node_id as string;
      if (s) { if (!adj[s]) adj[s] = new Set(); adj[s].add(t); }
      if (t) { if (!adj[t]) adj[t] = new Set(); adj[t].add(s); }
    }

    const ids = nodes.map((n) => n.id as string).filter(Boolean).slice(0, limit);
    const out: SuggestConnectionResult[] = [];

    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = ids[i], b = ids[j];
        if (adj[a]?.has(b) || adj[b]?.has(a)) continue;
        const common = [...(adj[a] ?? [])].filter((x) => (adj[b] ?? new Set()).has(x));
        if (common.length >= 1) {
          out.push({
            sourceId: a,
            targetId: b,
            sourceLabel: this._label(a, nodes),
            targetLabel: this._label(b, nodes),
            commonNeighbours: common.slice(0, 5),
            commonCount: common.length,
          });
        }
      }
    }
    out.sort((a, b) => b.commonCount - a.commonCount);
    return out;
  }

  // -----------------------------------------------------------------------
  //  7. lintWorkspace  —  health checks
  // -----------------------------------------------------------------------

  async lintWorkspace(
    workspaceId: string = "default",
    opts?: { checkOrphans?: boolean; checkMissingCrossrefs?: boolean; checkNoteOrphans?: boolean; limit?: number },
  ): Promise<LintResult> {
    const checkOrph = opts?.checkOrphans ?? true;
    const checkCrossRef = opts?.checkMissingCrossrefs ?? true;
    const checkNO = opts?.checkNoteOrphans ?? true;
    const limit = opts?.limit ?? 100;

    const r: LintResult = {
      orphans: [],
      missingCrossrefs: [],
      noteOrphans: [],
      contradictions: [],
      summary: { orphanCount: 0, missingCrossrefCount: 0, noteOrphanCount: 0, contradictionCount: 0, totalIssues: 0 },
    };

    if (checkOrph) r.orphans = await this._orphanNodes(workspaceId);
    if (checkCrossRef) r.missingCrossrefs = await this._missingCrossRefs(workspaceId, limit);
    if (checkNO) r.noteOrphans = await this._noteOrphans(workspaceId, limit);

    r.summary = {
      orphanCount: r.orphans.length,
      missingCrossrefCount: r.missingCrossrefs.length,
      noteOrphanCount: r.noteOrphans.length,
      contradictionCount: 0,
      totalIssues: r.orphans.length + r.missingCrossrefs.length + r.noteOrphans.length,
    };

    await this._log(
      workspaceId,
      "lint",
      `${r.summary.totalIssues} issues (orphans=${r.summary.orphanCount} crossrefs=${r.summary.missingCrossrefCount} noteOrphans=${r.summary.noteOrphanCount})`,
    );
    return r;
  }

  // -----------------------------------------------------------------------
  //  8. ingestSource  —  full source ingestion
  // -----------------------------------------------------------------------

  async ingestSource(
    sourceText: string,
    sourceTitle: string,
    workspaceId: string = "default",
    opts?: { sourceType?: string; embed?: boolean },
  ): Promise<IngestSourceResult> {
    const sourceType = opts?.sourceType ?? "article";
    const embed = opts?.embed ?? true;
    if (!sourceText.trim()) return { note: {}, entities: [], links: [], contradictions: [] };

    const result: IngestSourceResult = { note: {}, entities: [], links: [], contradictions: [] };
    const noteTitle = `Source: ${sourceTitle}`;
    const body = this._formatSource(sourceTitle, sourceText, sourceText, sourceType);

    await this._client.createNote(workspaceId, noteTitle, body, { embed });
    const note = await this._resolveNote(workspaceId, noteTitle);
    result.note = note;

    // Extract entities
    const entityRe = /\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b/g;
    const seen = new Set<string>();
    const labels: string[] = [];
    for (const m of sourceText.match(entityRe) ?? []) {
      const c = m.trim();
      if (c.length < 3 || c.length > 60 || seen.has(c.toLowerCase())) continue;
      seen.add(c.toLowerCase());
      labels.push(c);
    }

    for (const label of labels.slice(0, 10)) {
      try {
        await (this._client as any)._call("create_node", [workspaceId, label, "concept", "", "{}"]);
        const rows = await (this._client as any)._sqlExec(
          `SELECT id FROM kg_node WHERE workspace_id = :ws AND label = :label`,
          { ws: workspaceId, label },
        );
        if (rows.length > 0) result.entities.push(rows[rows.length - 1]);
      } catch { /* best-effort */ }
    }

    const noteId = (note as any).id ?? "";
    for (const node of result.entities) {
      const nodeId = node.id as string;
      if (nodeId && noteId) {
        try {
          await (this._client as any)._call("create_edge", [
            workspaceId, noteId, nodeId, "informed_by", 1.0, "INFERRED", "{}", "",
          ]);
          result.links.push(nodeId);
        } catch { /* best-effort */ }
      }
    }

    const idxSummary = sourceText.slice(0, 100);
    await this._updateIndex(workspaceId, noteTitle, note, idxSummary);
    await this._log(workspaceId, "ingest_source", `'${sourceTitle}' (${result.entities.length} entities)`);
    return result;
  }

  // -----------------------------------------------------------------------
  //  9. createEntityPage
  // -----------------------------------------------------------------------

  async createEntityPage(
    name: string,
    description: string,
    entityType: string = "concept",
    workspaceId: string = "default",
    opts?: { tags?: string[]; relations?: Array<{ name: string; relation: string }>; embed?: boolean },
  ): Promise<EntityPageResult> {
    const embed = opts?.embed ?? true;

    // Upsert KG node
    let node: Record<string, unknown> | null = null;
    const existing = await (this._client as any)._query("kg_node", workspaceId, { label: name });
    if (existing?.length) {
      node = existing[0];
    } else {
      try {
        await this._client.createNode(workspaceId, name, entityType, description);
        const rows = await (this._client as any)._sqlExec(
          `SELECT id, label, node_type, summary FROM kg_node WHERE workspace_id = :ws AND label = :label`,
          { ws: workspaceId, label: name },
        );
        if (rows.length > 0) node = rows[rows.length - 1];
      } catch { /* best-effort */ }
    }

    // Create note
    const tagLine = opts?.tags?.length ? `tags: [${opts.tags.join(", ")}]\n` : "";
    const relLines = opts?.relations?.length
      ? "\n## Relations\n\n" + opts.relations.map((r) => `- **${r.relation}**: ${r.name}\n`).join("")
      : "";

    const content = [
      "---",
      `type: ${entityType}`,
      `${tagLine}sources: []`,
      `created: ${new Date().toISOString().slice(0, 10)}`,
      "---",
      "",
      "## Overview",
      "",
      description,
      "",
      relLines,
      "---",
      `*Entity page: ${name}*`,
    ].filter(Boolean).join("\n");

    await this._client.createNote(workspaceId, name, content, { embed });
    const note = await this._resolveNote(workspaceId, name);

    if (node && (note as any).id) {
      try {
        await (this._client as any)._call("create_edge", [
          workspaceId, (note as any).id, node.id, "describes", 1.0, "INFERRED", "{}", "",
        ]);
      } catch { /* best-effort */ }
    }

    await this._updateIndex(workspaceId, name, note, description.slice(0, 100));
    await this._log(workspaceId, "create_entity_page", `'${name}' (${entityType})`);
    return { node, note };
  }

  // -----------------------------------------------------------------------
  // 10. updateEntityPage
  // -----------------------------------------------------------------------

  async updateEntityPage(
    name: string,
    workspaceId: string = "default",
    opts?: {
      description?: string;
      entityType?: string;
      tags?: string[];
      relations?: Array<{ name: string; relation: string }>;
      embed?: boolean;
    },
  ): Promise<EntityPageResult> {
    const existing = await (this._client as any)._query("kg_node", workspaceId, { label: name });
    if (!existing?.length) return { node: null, note: {} };
    const node = existing[0] as Record<string, unknown>;

    const notes: Record<string, unknown>[] =
      (await (this._client as any)._query("note", workspaceId, { title: name, is_active: "true" })) ?? [];
    const note = (notes[0] ?? {}) as Record<string, unknown>;

    const newType = opts?.entityType ?? (node.node_type as string) ?? "concept";
    const newSummary = opts?.description ?? (node.summary as string) ?? "";

    try { await this._client.updateNode(node.id as string, newSummary, newType); } catch { /* best-effort */ }

    if (note.id) {
      const oldC = (note.content as string) ?? "";
      const tagLine = opts?.tags?.length
        ? `tags: [${opts.tags.join(", ")}]\n`
        : this._extractTag(oldC);
      const relLines = opts?.relations
        ? (opts.relations.length
            ? "\n## Relations\n\n" + opts.relations.map((r) => `- **${r.relation}**: ${r.name}\n`).join("")
            : "")
        : this._extractRel(oldC);

      const newC = [
        "---", `type: ${newType}`, `${tagLine}sources: []`,
        `created: ${new Date().toISOString().slice(0, 10)}`,
        "---", "", "## Overview", "", newSummary, "", relLines, "---", `*Entity page: ${name}*`,
      ].filter(Boolean).join("\n");

      try { await this._client.updateNote(note.id as string, name, newC); } catch { /* best-effort */ }
    }

    await this._updateIndex(workspaceId, name, note, newSummary.slice(0, 100));
    await this._log(workspaceId, "update_entity_page", `'${name}' (${newType})`);
    return { node, note };
  }

  // -----------------------------------------------------------------------
  // 11. createConceptPage
  // -----------------------------------------------------------------------

  async createConceptPage(
    concept: string,
    definition: string,
    workspaceId: string = "default",
    opts?: { relatedConcepts?: string[]; embed?: boolean },
  ): Promise<EntityPageResult> {
    const embed = opts?.embed ?? true;
    const relLines = opts?.relatedConcepts?.length
      ? "\n## Related Concepts\n\n" + opts.relatedConcepts.map((rc) => `- [[${rc}]]\n`).join("")
      : "";

    const body = [
      "---", "type: concept", "tags: [concept]",
      `created: ${new Date().toISOString().slice(0, 10)}`,
      "---", "", "## Definition", "", definition, "", relLines, "---",
      `*Concept page: ${concept}*`,
    ].filter(Boolean).join("\n");

    const noteTitle = `Concept: ${concept}`;
    await this._client.createNote(workspaceId, noteTitle, body, { embed });
    const note = await this._resolveNote(workspaceId, noteTitle);

    let node: Record<string, unknown> | null = null;
    try {
      await this._client.createNode(workspaceId, concept, "concept", definition.slice(0, 300));
      const rows = await (this._client as any)._sqlExec(
        `SELECT id, label, node_type, summary FROM kg_node WHERE workspace_id = :ws AND label = :label`,
        { ws: workspaceId, label: concept },
      );
      if (rows.length > 0) node = rows[rows.length - 1];
    } catch { /* best-effort */ }

    if (node && (note as any).id) {
      try {
        await (this._client as any)._call("create_edge", [
          workspaceId, (note as any).id, node.id, "describes", 1.0, "INFERRED", "{}", "",
        ]);
      } catch { /* best-effort */ }
    }

    await this._updateIndex(workspaceId, noteTitle, note, definition.slice(0, 100));
    await this._log(workspaceId, "create_concept_page", concept);
    return { node, note };
  }

  // -----------------------------------------------------------------------
  // 12. createComparisonPage
  // -----------------------------------------------------------------------

  async createComparisonPage(
    title: string,
    items: Record<string, string>[] | string[],
    workspaceId: string = "default",
    opts?: { criteria?: string[]; embed?: boolean },
  ): Promise<{ note: Record<string, unknown> }> {
    const embed = opts?.embed ?? true;
    if (!items?.length) return { note: {} };

    // Normalise
    let dictItems: Record<string, string>[];
    if (typeof items[0] === "string") {
      dictItems = (items as string[]).map((s) => ({ name: s }));
      if (opts?.criteria) for (const item of dictItems) for (const c of opts.criteria) item[c] = "";
    } else {
      dictItems = items as Record<string, string>[];
    }

    const allKeys = ["name", ...new Set(dictItems.flatMap((it) => Object.keys(it)).filter((k) => k !== "name"))];
    const header = "| " + allKeys.map((k) => k.charAt(0).toUpperCase() + k.slice(1)).join(" | ") + " |";
    const sep = "| " + allKeys.map(() => "---").join(" | ") + " |";
    const rows = dictItems.map((it) => "| " + allKeys.map((k) => it[k] ?? "").join(" | ") + " |");
    const table = [header, sep, ...rows].join("\n");

    const body = [
      "---", "type: comparison", "tags: [comparison]",
      `created: ${new Date().toISOString().slice(0, 10)}`,
      "---", "", `## ${title}`, "", table, "", "---", `*Comparison page: ${title}*`,
    ].join("\n");

    const noteTitle = `Comparison: ${title}`;
    await this._client.createNote(workspaceId, noteTitle, body, { embed });
    const note = await this._resolveNote(workspaceId, noteTitle);

    const nameStr = dictItems.slice(0, 5).map((i) => i.name ?? "").join(", ");
    await this._updateIndex(workspaceId, noteTitle, note, nameStr.slice(0, 100));
    await this._log(workspaceId, "create_comparison_page", title);
    return { note };
  }

  // -----------------------------------------------------------------------
  // 13. exportWorkspace
  // -----------------------------------------------------------------------

  async exportWorkspace(
    workspaceId: string = "default",
    opts?: { includeKg?: boolean; includeSystemNotes?: boolean },
  ): Promise<{ markdown: string; files: Array<{ filename: string; content: string }> }> {
    const includeKg = opts?.includeKg ?? false;
    const includeSys = opts?.includeSystemNotes ?? false;

    let notes: Record<string, unknown>[] = (await (this._client as any)._query("note", workspaceId, {})) ?? [];
    const edges: Record<string, unknown>[] = (await (this._client as any)._query("kg_edge", workspaceId, {})) ?? [];

    // Backlink map
    const blMap: Record<string, Set<string>> = {};
    for (const e of edges) {
      const s = e.source_node_id as string;
      const t = e.target_node_id as string;
      if (s) { if (!blMap[s]) blMap[s] = new Set(); blMap[s].add(t); }
      if (t) { if (!blMap[t]) blMap[t] = new Set(); blMap[t].add(s); }
    }

    const files: Array<{ filename: string; content: string }> = [];
    for (const note of notes) {
      const nid = note.id as string;
      const t = (note.title ?? "untitled") as string;
      const c = (note.content ?? "") as string;
      if (!includeSys && t.startsWith("_")) continue;

      const bl = [...(blMap[nid] ?? [])].slice(0, 20).map((b) => `    - "${b}"`).join("\n");
      const fm = [
        "---",
        `id: "${nid}"`, `title: "${t}"`,
        `created: ${note.created_at ?? ""}`, `updated: ${note.updated_at ?? ""}`,
        "backlinks:", bl, "---", "",
      ].join("\n");

      const safe = t.replace(/[^a-zA-Z0-9 _-]/g, "_").trim() || nid.slice(0, 12);
      files.push({ filename: `${safe.slice(0, 100)}.md`, content: fm + c });
    }

    if (includeKg) {
      const nodes: Record<string, unknown>[] = (await (this._client as any)._query("kg_node", workspaceId, {})) ?? [];
      for (const nd of nodes) {
        const label = (nd.label ?? "unknown") as string;
        const kg = [
          "---",
          `id: "${nd.id}"`, "type: kg_node",
          `node_type: ${nd.node_type ?? "concept"}`, `label: "${label}"`,
          "---", "", `## ${label}`, "", `**Type:** ${nd.node_type ?? "concept"}`, "", nd.summary ?? "",
        ].join("\n");
        files.push({ filename: `_kg_nodes/${label.replace(/[^a-zA-Z0-9 _-]/g, "_").trim().slice(0, 100)}.md`, content: kg });
      }
    }

    const combined = files.map((f) => `# ${f.filename}\n\n${f.content}`).join("\n\n---\n\n");
    return { markdown: combined, files };
  }

  // -----------------------------------------------------------------------
  // 14. generateOverviewPage
  // -----------------------------------------------------------------------

  async generateOverviewPage(
    workspaceId: string = "default",
    embed: boolean = true,
  ): Promise<OverviewResult> {
    const notes: Record<string, unknown>[] = (await (this._client as any)._query("note", workspaceId, {})) ?? [];
    const nodes: Record<string, unknown>[] = (await (this._client as any)._query("kg_node", workspaceId, {})) ?? [];
    const edges: Record<string, unknown>[] = (await (this._client as any)._query("kg_edge", workspaceId, {})) ?? [];
    if (!notes.length && !nodes.length) return { note: {} };

    // Categories
    const entityNotes = notes.filter((n) => {
      const c = (n.content as string) ?? "";
      return c.includes("type: person") || c.includes("type: organization");
    });
    const conceptNotes = notes.filter((n) => ((n.content as string) ?? "").includes("type: concept"));
    const sourceNotes = notes.filter((n) => ((n.title as string) ?? "").startsWith("Source:"));
    const comparisonNotes = notes.filter((n) => ((n.title as string) ?? "").startsWith("Comparison:"));
    const systemNotes = notes.filter((n) => ((n.title as string) ?? "").startsWith("_"));
    const regularNotes = notes.filter((n) => {
      const t = (n.title as string) ?? "";
      return !t.startsWith("_") && !entityNotes.includes(n) && !conceptNotes.includes(n) && !sourceNotes.includes(n) && !comparisonNotes.includes(n);
    });

    // Node / edge type counts
    const nodeTypes: Record<string, number> = {};
    for (const nd of nodes) { const k = (nd.node_type as string) ?? "unknown"; nodeTypes[k] = (nodeTypes[k] ?? 0) + 1; }
    const edgeTypes: Record<string, number> = {};
    for (const e of edges) { const k = (e.relation_type as string) ?? "unknown"; edgeTypes[k] = (edgeTypes[k] ?? 0) + 1; }

    // Orphans
    const connected = new Set<string>();
    for (const e of edges) {
      const s = e.source_node_id as string, t = e.target_node_id as string;
      if (s) connected.add(s); if (t) connected.add(t);
    }
    const orphanCount = nodes.filter((nd) => !connected.has(nd.id as string)).length;

    // Top entities
    const topN = [...nodes].sort((a, b) => ((b.summary as string) ?? "").length - ((a.summary as string) ?? "").length).slice(0, 10);
    const entityRows = topN.length
      ? "| Entity | Type | Summary |\n|--------|------|---------|\n" + topN.map((nd) =>
          `| ${(nd.label as string ?? "?").slice(0, 30)} | ${(nd.node_type as string ?? "?").slice(0, 15)} | ${(nd.summary as string ?? "").slice(0, 80)} |`
        ).join("\n")
      : "";

    // Recent activity
    const logNotes = notes.filter((n) => n.title === "_log");
    let recent = "";
    if (logNotes.length > 0) {
      const lines = ((logNotes[logNotes.length - 1].content as string) ?? "").split("\n").filter((l) => l.startsWith("## [")).slice(-5);
      if (lines.length) recent = lines.map((l) => `- ${l.replace(/^##\s*/, "")}`).join("\n");
    }

    const typeTable = Object.keys(nodeTypes).length
      ? "| Type | Count |\n|------|:-----:|\n" + Object.entries(nodeTypes).sort((a, b) => b[1] - a[1]).map(([k, v]) => `| ${k} | ${v} |`).join("\n")
      : "";

    const lines: string[] = [
      "---", "type: overview", "tags: [overview, synthesis]",
      `created: ${new Date().toISOString().slice(0, 10)}`,
      "---", "", "## Workspace Overview", "",
      `**${notes.length}** notes · **${nodes.length}** KG nodes · **${edges.length}** edges · **${orphanCount}** orphans`,
      "", "### Notes by Category", "",
      "| Category | Count |\n|----------|:-----:|",
      `| Sources | ${sourceNotes.length} |`,
      `| Entity pages | ${entityNotes.length} |`,
      `| Concept pages | ${conceptNotes.length} |`,
      `| Comparisons | ${comparisonNotes.length} |`,
      `| Other | ${regularNotes.length} |`,
      `| System (_index, _log) | ${systemNotes.length} |`,
      "",
    ];
    if (typeTable) lines.push("### KG Entity Types\n", typeTable, "");
    if (entityRows) lines.push("### Top Entities\n", entityRows, "");
    if (orphanCount > 0) lines.push(`> ⚠ **${orphanCount} orphan nodes** — KG nodes with no edges.`, "");
    if (recent) lines.push("### Recent Activity\n", recent, "");
    if (Object.keys(edgeTypes).length) {
      lines.push("### Edge Types\n", "| Relation Type | Count |\n|------|:-----:|\n" +
        Object.entries(edgeTypes).sort((a, b) => b[1] - a[1]).map(([k, v]) => `| ${k} | ${v} |`).join("\n"), "");
    }
    lines.push("---", `*Auto-generated overview for workspace '${workspaceId}'*`);

    const body = lines.join("\n");
    await this._client.createNote(workspaceId, "_overview", body, { embed });
    const note = await this._resolveNote(workspaceId, "_overview");

    await this._log(workspaceId, "generate_overview", `${notes.length} notes, ${nodes.length} nodes, ${edges.length} edges`);
    return { note };
  }

  // -----------------------------------------------------------------------
  //  Private helpers
  // -----------------------------------------------------------------------

  private _generateTitle(query: string, answer: string): string {
    if (query.length < 80) return query.trim().replace(/[?.]$/, "");
    const first = answer.trim().split("\n")[0];
    return first.slice(0, 80).replace(/[?.]$/, "");
  }

  private async _resolveNote(wsId: string, title: string): Promise<Record<string, unknown>> {
    try {
      const rows: Record<string, unknown>[] = await (this._client as any)._query("note", wsId, { title });
      if (rows.length > 0) return rows[0];
      const all: Record<string, unknown>[] = (await (this._client as any)._query("note", wsId, {})) ?? [];
      all.sort((a, b) => ((b.created_at ?? 0) as number) - ((a.created_at ?? 0) as number));
      for (const n of all) if ((n.title as string) === title) return n;
    } catch { /* fall through */ }
    return {};
  }

  private _formatAnswerPage(query: string, answer: string, srcIds?: string[]): string {
    const parts = [`## Question\n\n${query}\n\n`, `## Synthesis\n\n${answer}\n\n`];
    if (srcIds?.length) parts.push(`## Sources\n\n${srcIds.map((s) => `- \`${s}\``).join("\n")}\n`);
    parts.push("---\n*Auto-generated by Compounder*");
    return parts.join("\n");
  }

  private async _updateIndex(wsId: string, title: string, note: Record<string, unknown>, summary: string): Promise<void> {
    const noteId = note?.id as string ?? "";
    if (!summary) {
      const c = (note.content as string) ?? "";
      for (const line of c.split("\n")) {
        const s = line.trim();
        if (s && !s.startsWith("---") && !s.startsWith("#")) { summary = s.slice(0, 120).replace(/\.$/, ""); break; }
      }
    }
    const suffix = summary ? ` — ${summary}` : "";
    const link = `- [${title}](${noteId})${suffix}\n`;

    try {
      const existing: Record<string, unknown>[] = await (this._client as any)._query("note", wsId, { title: "_index" });
      if (existing?.length) {
        await this._client.updateNote(existing[0].id as string, "_index", ((existing[0].content as string) ?? "") + link);
      } else {
        await this._client.createNote(wsId, "_index", "# Workspace Index\n\nAuto-generated index of synthesis pages.\n\n" + link, { embed: false });
      }
    } catch { /* best-effort */ }
  }

  private async _linked(id1: string, id2: string): Promise<boolean> {
    try {
      const edges: Record<string, unknown>[] = await (this._client as any)._query("kg_edge", "", {});
      for (const e of edges) {
        const s = e.source_node_id as string, t = e.target_node_id as string;
        if ((s === id1 && t === id2) || (s === id2 && t === id1)) return true;
      }
    } catch { /* fall through */ }
    return false;
  }

  private _label(id: string, nodes: Record<string, unknown>[]): string {
    for (const n of nodes) if ((n.id as string) === id) return (n.label as string) ?? id;
    return id.slice(0, 12);
  }

  private async _log(wsId: string, event: string, detail: string): Promise<void> {
    const now = new Date().toISOString().replace("T", " ").slice(0, 16) + " UTC";
    const entry = `## [${now}] ${event} | ${detail}\n`;
    try {
      const existing: Record<string, unknown>[] = await (this._client as any)._query("note", wsId, { title: "_log" });
      if (existing?.length) {
        await this._client.updateNote(existing[0].id as string, "_log", ((existing[0].content as string) ?? "") + entry);
      } else {
        await this._client.createNote(wsId, "_log", "# Workspace Log\n\nChronological record.\n\n" + entry, { embed: false });
      }
    } catch { /* best-effort */ }
  }

  // -----------------------------------------------------------------------
  //  Lint sub-routines
  // -----------------------------------------------------------------------

  private async _orphanNodes(wsId: string): Promise<Array<{ id: string; label: string; nodeType: string }>> {
    const nodes: Record<string, unknown>[] = (await (this._client as any)._query("kg_node", wsId, {})) ?? [];
    const edges: Record<string, unknown>[] = (await (this._client as any)._query("kg_edge", wsId, {})) ?? [];
    const connected = new Set<string>();
    for (const e of edges) { const s = e.source_node_id as string, t = e.target_node_id as string; if (s) connected.add(s); if (t) connected.add(t); }
    return nodes.filter((n) => n.id && !connected.has(n.id as string)).map((n) => ({
      id: n.id as string,
      label: (n.label as string) ?? (n.id as string).slice(0, 12),
      nodeType: (n.node_type as string) ?? "unknown",
    }));
  }

  private async _missingCrossRefs(
    wsId: string, limit: number,
  ): Promise<Array<{ entityId: string; entityType: string; mentionedLabel: string; targetNodeId: string }>> {
    const nodes: Record<string, unknown>[] = (await (this._client as any)._query("kg_node", wsId, {})) ?? [];
    const edges: Record<string, unknown>[] = (await (this._client as any)._query("kg_edge", wsId, {})) ?? [];
    const entityConn: Record<string, Set<string>> = {};
    for (const e of edges) {
      const s = e.source_node_id as string, t = e.target_node_id as string;
      (entityConn[s] ??= new Set()).add(t);
      (entityConn[t] ??= new Set()).add(s);
    }
    const labelMap: Record<string, string> = {};
    for (const n of nodes) { const l = ((n.label as string) ?? "").toLowerCase().trim(); if (l) labelMap[l] = n.id as string; }
    if (!Object.keys(labelMap).length) return [];

    const out: Array<{ entityId: string; entityType: string; mentionedLabel: string; targetNodeId: string }> = [];

    for (const mem of ((await (this._client as any)._query("memory", wsId, {})) ?? []).slice(0, limit) as Record<string, unknown>[]) {
      const c = ((mem.content as string) ?? "").toLowerCase();
      const id = mem.id as string;
      if (!id || !c) continue;
      for (const [label, nodeId] of Object.entries(labelMap)) {
        if (c.includes(label) && !entityConn[id]?.has(nodeId)) out.push({ entityId: id, entityType: "memory", mentionedLabel: label, targetNodeId: nodeId });
      }
    }
    for (const note of ((await (this._client as any)._query("note", wsId, {})) ?? []).slice(0, limit) as Record<string, unknown>[]) {
      const c = ((note.content as string) ?? "").toLowerCase();
      const id = note.id as string;
      if (!id || !c) continue;
      for (const [label, nodeId] of Object.entries(labelMap)) {
        if (c.includes(label) && !entityConn[id]?.has(nodeId)) out.push({ entityId: id, entityType: "note", mentionedLabel: label, targetNodeId: nodeId });
      }
    }
    return out;
  }

  private async _noteOrphans(wsId: string, limit: number): Promise<Array<{ id: string; title: string; reason: string }>> {
    let notes: Record<string, unknown>[] = (await (this._client as any)._query("note", wsId, {})) ?? [];
    if (!notes.length) return [];
    notes = notes.slice(0, limit);

    const nodes: Record<string, unknown>[] = (await (this._client as any)._query("kg_node", wsId, {})) ?? [];
    const labelMap: Record<string, string> = {};
    for (const n of nodes) { const l = ((n.label as string) ?? "").toLowerCase().trim(); if (l) labelMap[l] = n.id as string; }

    const edges: Record<string, unknown>[] = (await (this._client as any)._query("kg_edge", wsId, {})) ?? [];
    const connected = new Set<string>();
    for (const e of edges) { const s = e.source_node_id as string, t = e.target_node_id as string; if (s) connected.add(s); if (t) connected.add(t); }

    return notes.filter((note) => {
      const id = note.id as string;
      if (!id || connected.has(id)) return false;
      const combined = ((note.title as string) ?? "").toLowerCase() + " " + ((note.content as string) ?? "").toLowerCase();
      return !Object.keys(labelMap).some((l) => combined.includes(l));
    }).map((n) => ({
      id: n.id as string,
      title: (n.title as string) ?? "untitled",
      reason: "No KG entity mentions or edges.",
    }));
  }

  private _extractTag(c: string): string {
    if (c.startsWith("---")) {
      const end = c.indexOf("---", 3);
      if (end !== -1) for (const line of c.slice(3, end).trim().split("\n")) if (line.startsWith("tags:")) return line + "\n";
    }
    return "";
  }

  private _extractRel(c: string): string {
    if (c.includes("## Relations")) {
      const parts = c.split("## Relations", 2);
      if (parts[1]?.includes("---")) return "## Relations" + parts[1].split("---", 1)[0];
    }
    return "";
  }

  private _formatSource(title: string, full: string, summary: string, stype: string): string {
    let preview = full.slice(0, 2000);
    if (full.length > 2000) preview += `\n\n*[truncated — ${full.length} chars total]*`;
    return `## Summary\n\n${summary}\n\n## Source (${stype}): ${title}\n\n${preview}\n\n---\n*Auto-imported via ingest_source*`;
  }
}
