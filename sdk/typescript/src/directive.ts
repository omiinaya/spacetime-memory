/**
 * Directive — goal/task directive management.
 *
 * Wraps the corresponding SpacetimeDB reducers for each domain.
 */
import type { ClientLike } from "./types";

// ---------------------------------------------------------------------------
// Directive — task directives with status and progress tracking
// ---------------------------------------------------------------------------

/** Create a new directive (goal/task). */
export async function createDirective(
  client: ClientLike,
  workspaceId: string,
  name: string,
  description: string = "",
  priority: number = 0.0,
  assignedTo: string = "",
  metadataJson: string = "{}",
): Promise<Record<string, unknown>> {
  return client._call("create_directive", [
    workspaceId, name, description, priority, assignedTo, metadataJson,
  ]);
}

/** Update the status of an existing directive. */
export async function updateDirectiveStatus(
  client: ClientLike,
  directiveId: string,
  status: string,
): Promise<Record<string, unknown>> {
  return client._call("update_directive_status", [directiveId, status]);
}

/** Update the progress (0.0–1.0) of an existing directive. */
export async function updateDirectiveProgress(
  client: ClientLike,
  directiveId: string,
  progress: number,
): Promise<Record<string, unknown>> {
  return client._call("update_directive_progress", [directiveId, progress]);
}

/** Delete a directive by its ID. */
export async function deleteDirective(
  client: ClientLike,
  directiveId: string,
): Promise<Record<string, unknown>> {
  return client._call("delete_directive", [directiveId]);
}

/** List all directives for a workspace (reads from directive_list_result). */
export async function listDirectives(
  client: ClientLike,
  workspaceId: string,
): Promise<Record<string, unknown>[]> {
  await client._call("list_directives", [workspaceId]);
  const rows = await client._sqlExec(
    "SELECT * FROM directive_list_result WHERE workspace_id = :ws ORDER BY created_at DESC LIMIT 1",
    { ws: workspaceId },
  );
  if (rows.length > 0 && rows[0].json_data) {
    try {
      return JSON.parse(rows[0].json_data as string) as Record<string, unknown>[];
    } catch {
      // fall through
    }
  }
  return [];
}
