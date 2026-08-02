/**
 * Reasoning tiers — formal tier system for agent reasoning depth (Honcho parity).
 *
 * Manages reasoning tiers: quick, balanced, deep, research.
 * Tiers constrain agent reasoning depth with configurable parameters.
 */
import type { ClientLike } from "./types";

// ---------------------------------------------------------------------------
// Default tiers configuration
// ---------------------------------------------------------------------------

export const DEFAULT_REASONING_TIERS = {
  quick: {
    name: "quick",
    description: "Fast response with minimal context, low tokens, high temperature for speed",
    max_tokens: 256,
    temperature: 0.9,
    top_p: 0.9,
    max_context_memories: 5,
    min_confidence: 0.7,
    requires_reflection: false,
    requires_graph_traversal: false,
    priority: 10,
    is_default: false,
  },
  balanced: {
    name: "balanced",
    description: "Default balanced reasoning tier for most queries",
    max_tokens: 1024,
    temperature: 0.7,
    top_p: 0.9,
    max_context_memories: 15,
    min_confidence: 0.5,
    requires_reflection: false,
    requires_graph_traversal: false,
    priority: 20,
    is_default: true,
  },
  deep: {
    name: "deep",
    description: "Thorough analysis with more context and guided reasoning",
    max_tokens: 4096,
    temperature: 0.5,
    top_p: 0.95,
    max_context_memories: 30,
    min_confidence: 0.3,
    requires_reflection: true,
    requires_graph_traversal: true,
    priority: 30,
    is_default: false,
  },
  research: {
    name: "research",
    description: "Maximum depth reasoning using knowledge graph traversal and reflection",
    max_tokens: 8192,
    temperature: 0.3,
    top_p: 0.98,
    max_context_memories: 50,
    min_confidence: 0.1,
    requires_reflection: true,
    requires_graph_traversal: true,
    priority: 40,
    is_default: false,
  },
} as const;

/** Full reasoning tier type. */
export interface ReasoningTier {
  id: string;
  workspace_id: string;
  name: string;
  description: string;
  max_tokens: number;
  temperature: number;
  top_p: number;
  max_context_memories: number;
  min_confidence: number;
  requires_reflection: boolean;
  requires_graph_traversal: boolean;
  priority: number;
  is_default: boolean;
  created_at: number;
  updated_at: number;
}

// ---------------------------------------------------------------------------
// Reducer helpers
// ---------------------------------------------------------------------------

/** Create a new reasoning tier. */
export async function createReasoningTier(
  client: ClientLike,
  workspaceId: string,
  name: string,
  description: string = "",
  maxTokens: number = 1024,
  temperature: number = 0.7,
  topP: number = 0.9,
  maxContextMemories: number = 15,
  minConfidence: number = 0.5,
  requiresReflection: boolean = false,
  requiresGraphTraversal: boolean = false,
  priority: number = 20,
  isDefault: boolean = false,
): Promise<Record<string, unknown>> {
  return client._call("create_reasoning_tier", [
    workspaceId, "", name, description,
    maxTokens, temperature, topP,
    maxContextMemories, minConfidence,
    requiresReflection, requiresGraphTraversal,
    priority, isDefault,
  ]);
}

/** Update an existing reasoning tier. */
export async function updateReasoningTier(
  client: ClientLike,
  workspaceId: string,
  tierId: string,
  name: string = "",
  description: string = "",
  maxTokens: number = 1024,
  temperature: number = 0.7,
  topP: number = 0.9,
  maxContextMemories: number = 15,
  minConfidence: number = 0.5,
  requiresReflection: boolean = false,
  requiresGraphTraversal: boolean = false,
  priority: number = 20,
  isDefault: boolean = false,
): Promise<Record<string, unknown>> {
  return client._call("update_reasoning_tier", [
    workspaceId, tierId, name, description,
    maxTokens, temperature, topP,
    maxContextMemories, minConfidence,
    requiresReflection, requiresGraphTraversal,
    priority, isDefault,
  ]);
}

/** Delete a reasoning tier. */
export async function deleteReasoningTier(
  client: ClientLike,
  workspaceId: string,
  tierId: string,
): Promise<Record<string, unknown>> {
  return client._call("delete_reasoning_tier", [workspaceId, tierId]);
}

/** Get all reasoning tiers for a workspace. */
export async function getReasoningTiers(
  client: ClientLike,
  workspaceId: string,
): Promise<ReasoningTier[]> {
  await client._call("get_reasoning_tiers", [workspaceId]);
  const rows = await client._sqlExec(
    "SELECT * FROM reasoning_tier_result WHERE workspace_id = :ws ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId },
  );
  if (rows.length > 0 && rows[0].data) {
    try {
      return JSON.parse(rows[0].data as string) as ReasoningTier[];
    } catch {
      // fall through
    }
  }
  return [];
}

/** Get the default reasoning tier for a workspace. */
export async function getDefaultReasoningTier(
  client: ClientLike,
  workspaceId: string,
): Promise<ReasoningTier | null> {
  await client._call("get_default_reasoning_tier", [workspaceId]);
  const rows = await client._sqlExec(
    "SELECT * FROM reasoning_tier_result WHERE workspace_id = :ws ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId },
  );
  if (rows.length > 0 && rows[0].data) {
    try {
      const data = JSON.parse(rows[0].data as string);
      return data as ReasoningTier;
    } catch {
      // fall through
    }
  }
  return null;
}

/** Set the default tier for a workspace. */
export async function setDefaultTier(
  client: ClientLike,
  workspaceId: string,
  tierId: string,
): Promise<Record<string, unknown>> {
  return client._call("set_default_tier", [workspaceId, tierId]);
}

/** Apply a reasoning tier to a memory (tag it). */
export async function applyReasoningTierToMemory(
  client: ClientLike,
  workspaceId: string,
  memoryId: string,
  tierId: string,
): Promise<Record<string, unknown>> {
  return client._call("apply_reasoning_tier_to_memory", [workspaceId, memoryId, tierId]);
}
