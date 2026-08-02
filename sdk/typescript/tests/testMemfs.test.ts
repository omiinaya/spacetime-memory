/**
 * Tests for memfs.ts TypeScript SDK module.
 *
 * These tests use vitest with mocked ClientLike instances to verify
 * that the wrapper functions call the correct reducers and query
 * the correct result tables.
 */
import { describe, it, expect, vi } from "vitest";
import {
  createMemfsEntry,
  deleteMemfsEntry,
  updateMemfsEntry,
  getMemfsEntries,
  getMemfsEntryByPath,
  readMemfsFile,
  writeMemfsFile,
  createMemfsMount,
  deleteMemfsMount,
  getMemfsMounts,
  mountWorkspace,
  mountMemories,
} from "../src/memfs";
import type { ClientLike } from "../src/types";

// -----------------------------------------------------------------------
// Mocks
// -----------------------------------------------------------------------

function mockClient(): ClientLike {
  return {
    _call: vi.fn().mockResolvedValue({ status: "ok" }),
    _callWithResult: vi.fn().mockResolvedValue('"ok"'),
    _sql: vi.fn().mockResolvedValue([]),
    _sqlExec: vi.fn().mockResolvedValue([]),
    _embed: vi.fn().mockResolvedValue([]),
    _query: vi.fn().mockResolvedValue([]),
    _authHeaders: vi.fn().mockReturnValue({}),
    embedderUrl: "http://localhost:9090/v1",
    mcpUrl: "http://localhost:8099",
    tantivyUrl: "http://localhost:9091",
    baseUrl: "http://localhost:3001",
    host: "localhost",
    port: "3001",
    database: "test",
    token: "",
    _metricsCollector: null,
  };
}

// -----------------------------------------------------------------------
// Sample data
// -----------------------------------------------------------------------

const SAMPLE_FILE_ENTRY = {
  id: "entry-001",
  workspace_id: "ws-test",
  parent_id: "",
  name: "readme.md",
  path: "/readme.md",
  entry_type: "file",
  mime_type: "text/markdown",
  data: "# Hello World",
  size: 13,
  is_mounted: false,
  mount_source: "",
  created_at: 1000000,
  updated_at: 1000000,
};

const SAMPLE_DIR_ENTRY = {
  id: "entry-002",
  workspace_id: "ws-test",
  parent_id: "",
  name: "docs",
  path: "/docs",
  entry_type: "directory",
  mime_type: "",
  data: "",
  size: 0,
  is_mounted: false,
  mount_source: "",
  created_at: 1000000,
  updated_at: 1000000,
};

const SAMPLE_MOUNT = {
  id: "mount-001",
  workspace_id: "ws-test",
  mount_path: "/memories",
  source_type: "memory",
  source_config: '{"filter":{"memory_type":"experience"}}',
  filter_query: "",
  created_at: 1000000,
};

/** Build a mock memfs_result row from an entry/mount dict. */
function resultRow(obj: Record<string, unknown>): Record<string, unknown> {
  return { id: obj.id as string, data: JSON.stringify(obj), created_at: 1000000 };
}

// -----------------------------------------------------------------------
// createMemfsEntry
// -----------------------------------------------------------------------

describe("createMemfsEntry", () => {
  it("calls create_memfs_entry reducer with correct args for a file", async () => {
    const client = mockClient();

    const result = await createMemfsEntry(
      client,
      "ws-test",
      "",
      "readme.md",
      "file",
      "text/markdown",
      "# Hello",
    );

    expect(client._call).toHaveBeenCalledWith("create_memfs_entry", [
      "ws-test",
      "",
      "readme.md",
      "file",
      "text/markdown",
      "# Hello",
    ]);
    expect(result).toBeDefined();
  });

  it("calls reducer with default empty mime_type and data for directory", async () => {
    const client = mockClient();

    await createMemfsEntry(client, "ws-test", "", "docs", "directory");

    expect(client._call).toHaveBeenCalledWith("create_memfs_entry", [
      "ws-test",
      "",
      "docs",
      "directory",
      "",
      "",
    ]);
  });
});

// -----------------------------------------------------------------------
// deleteMemfsEntry
// -----------------------------------------------------------------------

describe("deleteMemfsEntry", () => {
  it("calls delete_memfs_entry reducer", async () => {
    const client = mockClient();

    await deleteMemfsEntry(client, "ws-test", "entry-001");

    expect(client._call).toHaveBeenCalledWith("delete_memfs_entry", [
      "ws-test",
      "entry-001",
    ]);
  });
});

// -----------------------------------------------------------------------
// updateMemfsEntry
// -----------------------------------------------------------------------

describe("updateMemfsEntry", () => {
  it("calls update_memfs_entry with name only", async () => {
    const client = mockClient();

    await updateMemfsEntry(client, "ws-test", "entry-001", "new-name.txt");

    expect(client._call).toHaveBeenCalledWith("update_memfs_entry", [
      "ws-test",
      "entry-001",
      "new-name.txt",
      "",
      "",
    ]);
  });

  it("calls with data and mime_type", async () => {
    const client = mockClient();

    await updateMemfsEntry(
      client,
      "ws-test",
      "entry-001",
      "",
      "updated content",
      "text/html",
    );

    expect(client._call).toHaveBeenCalledWith("update_memfs_entry", [
      "ws-test",
      "entry-001",
      "",
      "updated content",
      "text/html",
    ]);
  });
});

// -----------------------------------------------------------------------
// getMemfsEntries
// -----------------------------------------------------------------------

describe("getMemfsEntries", () => {
  it("calls reducer and returns parsed entries from memfs_result", async () => {
    const client = mockClient();
    const children = [
      resultRow({ ...SAMPLE_FILE_ENTRY, id: "e-1", name: "a.txt", path: "/a.txt" }),
      resultRow({ ...SAMPLE_FILE_ENTRY, id: "e-2", name: "b.txt", path: "/b.txt" }),
    ];
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue(children);

    const result = await getMemfsEntries(client, "ws-test", "dir-1");

    expect(client._call).toHaveBeenCalledWith("get_memfs_entries", [
      "ws-test",
      "dir-1",
    ]);
    expect(client._sqlExec).toHaveBeenCalledWith(
      expect.stringContaining("memfs_result"),
      expect.objectContaining({ excl: "_count_dir-1%" }),
      expect.objectContaining({ like: true }),
    );
    expect(result).toHaveLength(2);
    expect(result[0].name).toBe("a.txt");
    expect(result[1].name).toBe("b.txt");
  });

  it("returns empty array when directory is empty", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const result = await getMemfsEntries(client, "ws-test", "empty-dir");
    expect(result).toEqual([]);
  });
});

// -----------------------------------------------------------------------
// getMemfsEntryByPath
// -----------------------------------------------------------------------

describe("getMemfsEntryByPath", () => {
  it("returns the entry when found", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: "found_e1", data: JSON.stringify(SAMPLE_FILE_ENTRY), created_at: 1000000 },
    ]);

    const result = await getMemfsEntryByPath(client, "ws-test", "/readme.md");

    expect(client._call).toHaveBeenCalledWith("get_memfs_entry_by_path", [
      "ws-test",
      "/readme.md",
    ]);
    expect(result).not.toBeNull();
    expect(result!.path).toBe("/readme.md");
    expect(result!.data).toBe("# Hello World");
  });

  it("returns null when not found", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const result = await getMemfsEntryByPath(client, "ws-test", "/nonexistent");
    expect(result).toBeNull();
  });
});

// -----------------------------------------------------------------------
// readMemfsFile
// -----------------------------------------------------------------------

describe("readMemfsFile", () => {
  it("returns file entry with content", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: "read_e1", data: JSON.stringify(SAMPLE_FILE_ENTRY), created_at: 1000000 },
    ]);

    const result = await readMemfsFile(client, "ws-test", "e1");

    expect(client._call).toHaveBeenCalledWith("read_memfs_file", ["ws-test", "e1"]);
    expect(result).not.toBeNull();
    expect(result!.data).toBe("# Hello World");
  });

  it("returns null when file not found", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const result = await readMemfsFile(client, "ws-test", "nonexistent");
    expect(result).toBeNull();
  });
});

// -----------------------------------------------------------------------
// writeMemfsFile
// -----------------------------------------------------------------------

describe("writeMemfsFile", () => {
  it("calls write_memfs_file reducer", async () => {
    const client = mockClient();

    await writeMemfsFile(client, "ws-test", "entry-001", "updated content");

    expect(client._call).toHaveBeenCalledWith("write_memfs_file", [
      "ws-test",
      "entry-001",
      "updated content",
    ]);
  });
});

// -----------------------------------------------------------------------
// createMemfsMount
// -----------------------------------------------------------------------

describe("createMemfsMount", () => {
  it("calls create_memfs_mount with dict config serialised as JSON", async () => {
    const client = mockClient();

    const config = { filter: { memory_type: "experience" } };
    await createMemfsMount(client, "ws-test", "/memories", "memory", config);

    expect(client._call).toHaveBeenCalledWith("create_memfs_mount", [
      "ws-test",
      "/memories",
      "memory",
      JSON.stringify(config),
      "",
    ]);
  });

  it("accepts raw JSON string as source_config", async () => {
    const client = mockClient();

    await createMemfsMount(client, "ws-test", "/notes", "note", '{"workspace_only":true}');

    expect(client._call).toHaveBeenCalledWith("create_memfs_mount", [
      "ws-test",
      "/notes",
      "note",
      '{"workspace_only":true}',
      "",
    ]);
  });
});

// -----------------------------------------------------------------------
// deleteMemfsMount
// -----------------------------------------------------------------------

describe("deleteMemfsMount", () => {
  it("calls delete_memfs_mount reducer", async () => {
    const client = mockClient();

    await deleteMemfsMount(client, "ws-test", "mount-001");

    expect(client._call).toHaveBeenCalledWith("delete_memfs_mount", [
      "ws-test",
      "mount-001",
    ]);
  });
});

// -----------------------------------------------------------------------
// getMemfsMounts
// -----------------------------------------------------------------------

describe("getMemfsMounts", () => {
  it("returns parsed mount list", async () => {
    const client = mockClient();
    const mounts = [
      resultRow({ ...SAMPLE_MOUNT, id: "m1" }),
      resultRow({ ...SAMPLE_MOUNT, id: "m2", mount_path: "/notes", source_type: "note" }),
    ];
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue(mounts);

    const result = await getMemfsMounts(client, "ws-test");

    expect(client._call).toHaveBeenCalledWith("get_memfs_mounts", ["ws-test"]);
    expect(result).toHaveLength(2);
    expect(result[0].source_type).toBe("memory");
    expect(result[1].mount_path).toBe("/notes");
  });

  it("returns empty array when no mounts", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    const result = await getMemfsMounts(client, "ws-empty");
    expect(result).toEqual([]);
  });
});

// -----------------------------------------------------------------------
// Convenience: mountWorkspace / mountMemories
// -----------------------------------------------------------------------

describe("mountWorkspace", () => {
  it("delegates to createMemfsMount with source_type 'workspace'", async () => {
    const client = mockClient();

    await mountWorkspace(client, "ws-test", "/my-workspace");

    expect(client._call).toHaveBeenCalledWith("create_memfs_mount", [
      "ws-test",
      "/my-workspace",
      "workspace",
      "{}",
      "",
    ]);
  });
});

describe("mountMemories", () => {
  it("delegates to createMemfsMount with source_type 'memory'", async () => {
    const client = mockClient();

    await mountMemories(client, "ws-test");

    expect(client._call).toHaveBeenCalledWith("create_memfs_mount", [
      "ws-test",
      "/memories",
      "memory",
      "{}",
      "",
    ]);
  });
});

// -----------------------------------------------------------------------
// Workspace isolation
// -----------------------------------------------------------------------

describe("workspace isolation", () => {
  it("getMemfsEntries returns different results for different workspaces", async () => {
    const client = mockClient();
    (client._sqlExec as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce([resultRow(SAMPLE_FILE_ENTRY)])
      .mockResolvedValueOnce([]);

    const resultA = await getMemfsEntries(client, "ws-a", "");
    const resultB = await getMemfsEntries(client, "ws-b", "");

    expect(client._call).toHaveBeenNthCalledWith(1, "get_memfs_entries", ["ws-a", ""]);
    expect(client._call).toHaveBeenNthCalledWith(2, "get_memfs_entries", ["ws-b", ""]);
    expect(resultA).toHaveLength(1);
    expect(resultB).toHaveLength(0);
  });
});
