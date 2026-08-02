/**
 * Insights and mental models.
 */
import type { ClientLike, MentalModelRecord } from "./types";

// -----------------------------------------------------------------------
// Mental Models
// -----------------------------------------------------------------------

export async function synthesizeMentalModels(client: ClientLike, workspaceId: string, memoryIds: string[]): Promise<MentalModelRecord[]> {
  await client._call("synthesize_mental_models", [workspaceId, JSON.stringify(memoryIds)]);
  return (await client._sqlExec(
    "SELECT * FROM mental_model_result WHERE workspace_id = :ws",
    { ws: workspaceId },
  )) as MentalModelRecord[];
}

export async function getMentalModel(client: ClientLike, modelId: string): Promise<MentalModelRecord[]> {
  return (await client._sqlExec(
    "SELECT * FROM mental_model WHERE id = :mid",
    { mid: modelId },
  )) as MentalModelRecord[];
}

export async function listMentalModels(client: ClientLike, workspaceId: string, status?: string): Promise<MentalModelRecord[]> {
  let q = "SELECT * FROM mental_model WHERE workspace_id = :ws";
  const params: Record<string, string> = { ws: workspaceId };
  if (status) { q += " AND status = :st"; params.st = status; }
  const rows = await client._sqlExec(q, params);
  return (rows as Record<string, unknown>[]).sort((a, b) => Number(b.created_at ?? 0) - Number(a.created_at ?? 0)) as unknown as MentalModelRecord[];
}

export async function deleteMentalModel(client: ClientLike, modelId: string): Promise<void> {
  return client._call("delete_mental_model", [modelId]);
}

export async function updateMentalModel(client: ClientLike, modelId: string, content: string, confidence?: number, status?: string): Promise<void> {
  return client._call("update_mental_model", [modelId, content, confidence ?? 0.5, status ?? "completed"]);
}

// -----------------------------------------------------------------------
// Harmonic Beliefs
// -----------------------------------------------------------------------

export async function storeHarmonicBeliefs(client: ClientLike, workspaceId: string, peerId: string, beliefsJson: string, clusterId: string): Promise<void> {
  return client._call("store_harmonic_beliefs", [workspaceId, peerId, beliefsJson, clusterId]);
}

export async function clearHarmonicBeliefs(client: ClientLike, workspaceId: string, minConfidence: number): Promise<void> {
  return client._call("clear_harmonic_beliefs", [workspaceId, minConfidence]);
}

export async function logResonanceSession(client: ClientLike, workspaceId: string, peerId: string, clusterCount: number, beliefsGenerated: number, contradictionsResolved: number, harmonyScoreAvg: number, durationMs: number): Promise<void> {
  return client._call("log_resonance_session", [workspaceId, peerId, clusterCount, beliefsGenerated, contradictionsResolved, harmonyScoreAvg, durationMs]);
}

// -----------------------------------------------------------------------
// Pattern Detection
// -----------------------------------------------------------------------

export async function detectPatterns(client: ClientLike, workspaceId: string, opts?: {
  limit?: number; includeClusters?: boolean; includeTerms?: boolean; includeCoOccur?: boolean;
}): Promise<{
  temporal_clusters: Array<{ start_time: number; end_time: number; count: number; ids: string[]; summary_terms: string[] }>;
  frequent_terms: Array<{ term: string; frequency: number; doc_count: number }>;
  co_occurrences: Array<{ term_a: string; term_b: string; count: number }>;
  total_memories: number;
  summary: string;
}> {
  const lim = opts?.limit ?? 200;
  const includeClusters = opts?.includeClusters ?? true;
  const includeTerms = opts?.includeTerms ?? true;
  const includeCoOccur = opts?.includeCoOccur ?? true;

  const memories = await client._sqlExec(
    `SELECT id, content, created_at FROM memory WHERE workspace_id = :ws AND is_active = true LIMIT ${lim}`,
    { ws: workspaceId },
  );

  const total = memories.length;

  function tokenize(text: string, minLen = 3): string[] {
    const tokens = text.toLowerCase().match(/[a-zA-Z0-9_]+/g) ?? [];
    return tokens.filter((t) => t.length >= minLen);
  }

  const result: {
    temporal_clusters: Array<{ start_time: number; end_time: number; count: number; ids: string[]; summary_terms: string[] }>;
    frequent_terms: Array<{ term: string; frequency: number; doc_count: number }>;
    co_occurrences: Array<{ term_a: string; term_b: string; count: number }>;
    total_memories: number;
    summary: string;
  } = { temporal_clusters: [], frequent_terms: [], co_occurrences: [], total_memories: total, summary: "" };

  if (includeClusters && total > 0) {
    const bucketSecs = 30 * 60;
    const buckets = new Map<number, Record<string, unknown>[]>();
    for (const m of memories) {
      let ts = (m.created_at as number) ?? 0;
      if (ts > 1_000_000_000_000) ts = Math.floor(ts / 1_000_000);
      const key = Math.floor(ts / bucketSecs);
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key)!.push(m);
    }
    for (const [key, items] of buckets) {
      if (items.length >= 2) {
        const termCounts = new Map<string, number>();
        for (const item of items) {
          const terms = new Set(tokenize((item.content as string) ?? ""));
          for (const t of terms) termCounts.set(t, (termCounts.get(t) ?? 0) + 1);
        }
        const sortedTerms = [...termCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([t]) => t);
        result.temporal_clusters.push({
          start_time: key * bucketSecs, end_time: (key + 1) * bucketSecs,
          count: items.length, ids: items.map((m: Record<string, unknown>) => m.id as string), summary_terms: sortedTerms,
        });
      }
    }
    result.temporal_clusters.sort((a, b) => b.start_time - a.start_time);
  }

  if (includeTerms && total > 0) {
    const docFreq = new Map<string, number>();
    const termFreq = new Map<string, number>();
    for (const m of memories) {
      const terms = new Set(tokenize((m.content as string) ?? ""));
      for (const t of terms) { docFreq.set(t, (docFreq.get(t) ?? 0) + 1); termFreq.set(t, (termFreq.get(t) ?? 0) + 1); }
    }
    const minDf = 2;
    for (const [term, df] of docFreq) { if (df >= minDf) result.frequent_terms.push({ term, frequency: termFreq.get(term) ?? 0, doc_count: df }); }
    result.frequent_terms.sort((a, b) => b.frequency - a.frequency);
    result.frequent_terms = result.frequent_terms.slice(0, 20);
  }

  if (includeCoOccur && total > 0) {
    const coOccurMap = new Map<string, number>();
    const memoryTerms: Set<string>[] = [];
    for (const m of memories) { memoryTerms.push(new Set(tokenize((m.content as string) ?? ""))); }
    const topTerms = new Set(result.frequent_terms.slice(0, 15).map((t: any) => t.term));
    for (const terms of memoryTerms) {
      const relevant = [...terms].filter((t) => topTerms.has(t));
      for (let i = 0; i < relevant.length; i++) {
        for (let j = i + 1; j < relevant.length; j++) {
          const pair = [relevant[i], relevant[j]].sort().join("::");
          coOccurMap.set(pair, (coOccurMap.get(pair) ?? 0) + 1);
        }
      }
    }
    for (const [pair, count] of coOccurMap) { if (count >= 2) { const [ta, tb] = pair.split("::"); result.co_occurrences.push({ term_a: ta, term_b: tb, count }); } }
    result.co_occurrences.sort((a: any, b: any) => b.count - a.count);
    result.co_occurrences = result.co_occurrences.slice(0, 20);
  }

  const parts: string[] = [];
  if (result.temporal_clusters.length > 0) parts.push(`${result.temporal_clusters.length} temporal cluster(s)`);
  if (result.frequent_terms.length > 0) parts.push(`${result.frequent_terms.length} frequent term(s)`);
  if (result.co_occurrences.length > 0) parts.push(`${result.co_occurrences.length} co-occurrence pair(s)`);
  result.summary = parts.length > 0 ? parts.join(", ") : "No patterns detected";

  return result;
}

// -----------------------------------------------------------------------
// Insights
// -----------------------------------------------------------------------

export async function createInsight(client: ClientLike, workspaceId: string, sourceMemoryId: string, content: string, summary = ""): Promise<any> {
  return await client._call("create_insight", [workspaceId, sourceMemoryId, content, summary]);
}

export async function deleteInsight(client: ClientLike, insightId: string): Promise<any> {
  return await client._call("delete_insight", [insightId]);
}
