/**
 * Cognitive operations — named abstraction wrapping pipeline stages (Cognee parity).
 *
 * Operations have types: observe, filter, extract, transform, classify, rank, store.
 * They can be registered, executed individually, or composed into pipelines.
 */
import type { ClientLike } from "./types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CognitiveOp {
  id: string;
  workspace_id: string;
  name: string;
  op_type: string;
  description: string;
  config_json: string;
  pipeline_stage_type: string;
  created_at: number;
  updated_at: number;
}

export interface CognitiveOpResult {
  id: string;
  workspace_id: string;
  data: string;
  created_at: number;
}

// ---------------------------------------------------------------------------
// CRUD operations
// ---------------------------------------------------------------------------

/** Register a new cognitive operation. */
export async function registerCognitiveOp(
  client: ClientLike,
  workspaceId: string,
  name: string,
  opType: string,
  description: string = "",
  configJson: string = "{}",
  pipelineStageType: string = "",
): Promise<Record<string, unknown>> {
  return client._call("register_cognitive_op", [
    workspaceId, "", name, opType, description, configJson, pipelineStageType,
  ]);
}

/** Unregister (delete) a cognitive operation. */
export async function unregisterCognitiveOp(
  client: ClientLike,
  workspaceId: string,
  opId: string,
): Promise<Record<string, unknown>> {
  return client._call("unregister_cognitive_op", [workspaceId, opId]);
}

/** Get cognitive operations, optionally filtered by type. */
export async function getCognitiveOps(
  client: ClientLike,
  workspaceId: string,
  opTypeFilter: string = "",
): Promise<CognitiveOp[]> {
  await client._call("get_cognitive_ops", [workspaceId, opTypeFilter]);
  const rows = await client._sqlExec(
    "SELECT * FROM cognitive_op_result WHERE workspace_id = :ws ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId },
  );
  if (rows.length > 0 && rows[0].data) {
    try {
      return JSON.parse(rows[0].data as string) as CognitiveOp[];
    } catch {
      // fall through
    }
  }
  return [];
}

/** Execute a cognitive operation with input data. */
export async function executeCognitiveOp(
  client: ClientLike,
  workspaceId: string,
  opId: string,
  inputData: Record<string, unknown> = {},
): Promise<Record<string, unknown>> {
  const inputJson = JSON.stringify(inputData);
  await client._call("execute_cognitive_op", [workspaceId, opId, inputJson]);
  const rows = await client._sqlExec(
    "SELECT * FROM cognitive_op_result WHERE workspace_id = :ws ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId },
  );
  if (rows.length > 0 && rows[0].data) {
    try {
      return JSON.parse(rows[0].data as string) as Record<string, unknown>;
    } catch {
      // fall through
    }
  }
  return { status: "error", message: "No result found" };
}

/** Get the ordered pipeline of registered cognitive ops. */
export async function getCognitivePipeline(
  client: ClientLike,
  workspaceId: string,
): Promise<CognitiveOp[]> {
  await client._call("get_cognitive_pipeline", [workspaceId]);
  const rows = await client._sqlExec(
    "SELECT * FROM cognitive_op_result WHERE workspace_id = :ws ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId },
  );
  if (rows.length > 0 && rows[0].data) {
    try {
      return JSON.parse(rows[0].data as string) as CognitiveOp[];
    } catch {
      // fall through
    }
  }
  return [];
}
