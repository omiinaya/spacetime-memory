/**
 * Notes CRUD, backlinks.
 */
import type { ClientLike, NoteRecord } from "./types";

export async function createNote(client: ClientLike, workspaceId: string, title: string, content: string, opts?: { note_date?: string; embed?: boolean }): Promise<void> {
  await client._call("create_note", [workspaceId, title, content, opts?.note_date ?? "", opts?.embed === false ? "[]" : ""]);
}

export async function updateNote(client: ClientLike, noteId: string, title: string = "", content: string = "", embeddingJson: string = "[]", expectedVersion: number = 0): Promise<void> {
  return client._call("update_note", [noteId, title, content, embeddingJson, expectedVersion]);
}

export async function deleteNote(client: ClientLike, noteId: string): Promise<void> {
  return client._call("delete_note", [noteId]);
}

export async function listNotes(client: ClientLike, workspaceId: string): Promise<NoteRecord[]> {
  return (await client._sqlExec(
    "SELECT * FROM note WHERE workspace_id = :ws",
    { ws: workspaceId },
  )) as NoteRecord[];
}

export async function getNote(client: ClientLike, noteId: string): Promise<NoteRecord[]> {
  return (await client._sqlExec(
    "SELECT * FROM note WHERE id = :nid",
    { nid: noteId },
  )) as NoteRecord[];
}

export async function getNoteByDate(client: ClientLike, noteDate: string): Promise<NoteRecord[]> {
  return (await client._sqlExec(
    "SELECT * FROM note WHERE note_date = :nd AND is_active = true",
    { nd: noteDate },
  )) as NoteRecord[];
}

export async function getNoteByTitle(client: ClientLike, title: string): Promise<NoteRecord[]> {
  return (await client._sqlExec(
    "SELECT * FROM note WHERE title = :t AND is_active = true",
    { t: title },
  )) as NoteRecord[];
}

export async function getNoteHistory(client: ClientLike, noteId: string): Promise<Record<string, unknown>[]> {
  const revisions = await client._sqlExec(
    "SELECT version, previous_title, previous_content, new_title AS title, new_content AS content, changed_at, changed_by FROM note_revision WHERE note_id = :nid",
    { nid: noteId },
  );
  (revisions as Record<string, unknown>[]).sort((a, b) => Number(a.version ?? 0) - Number(b.version ?? 0));
  const result: Record<string, unknown>[] = [];
  for (const rev of revisions) {
    result.push({
      version: rev.version ?? 0, previous_title: rev.previous_title ?? "", previous_content: rev.previous_content ?? "",
      title: rev.title ?? "", content: rev.content ?? "", changed_at: rev.changed_at ?? 0, changed_by: rev.changed_by ?? "",
    });
  }
  const current = await client._sqlExec("SELECT title, content, version, updated_at FROM note WHERE id = :nid", { nid: noteId });
  if (current.length > 0) {
    const r = current[0];
    const currentVersion = (r.version as number) ?? 1;
    if (result.length === 0 || (result[result.length - 1].version as number) !== currentVersion) {
      result.push({ version: currentVersion, previous_title: "", previous_content: "", title: r.title ?? "", content: r.content ?? "", changed_at: r.updated_at ?? 0, changed_by: "" });
    }
  }
  return result;
}

export async function getBacklinks(client: ClientLike, noteId: string): Promise<Record<string, unknown>[]> {
  await client._call("get_backlinks", [noteId]);
  return client._sqlExec("SELECT * FROM backlink_result WHERE target_note_id = :nid", { nid: noteId });
}

export async function getOutgoingLinks(client: ClientLike, noteId: string): Promise<Record<string, unknown>[]> {
  return client._sqlExec("SELECT target_note_id, relation FROM note_backlink WHERE source_note_id = :nid", { nid: noteId });
}
