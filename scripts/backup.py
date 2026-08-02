#!/usr/bin/env python3
"""Backup and restore spacetime-memory data.

Usage:
    python scripts/backup.py export <workspace_id> [--output backup.json]
    python scripts/backup.py import <workspace_id> <input.json>
    python scripts/backup.py s3-upload <file> [--bucket my-bucket] [--prefix spacetime-backups]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# Client helpers (avoid importing the full client module if we aren't inside
# the SDK tree — we add it to sys.path so the import succeeds)
# ---------------------------------------------------------------------------

def _get_client():
    """Import and instantiate the SpacetimeDB Client."""
    # Ensure the SDK path is discoverable
    sdk_dir = os.path.join(os.path.dirname(__file__), "..", "sdk", "python")
    if sdk_dir not in sys.path:
        sys.path.insert(0, os.path.abspath(sdk_dir))

    from spacetime_memory.client import Client
    return Client()


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def cmd_export(args: argparse.Namespace) -> None:
    """Export all workspace tables into a JSON backup file.

    Calls the ``export_backup`` reducer first, then reads the resulting
    ``backup_entry`` rows via SQL and writes them to disk.
    """
    ws = args.workspace_id
    output = args.output

    print(f"[backup] Exporting workspace {ws} ...")

    client = _get_client()

    # 1. Run the export_backup reducer (inserts BackupEntry rows)
    try:
        client._call("export_backup", [ws])
    except RuntimeError as exc:
        print(f"[backup] ERROR: export_backup reducer failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("[backup] Reducer completed. Reading backup entries ...")

    # 2. Read all backup_entry rows for this workspace
    try:
        rows = client._sql(
            f"SELECT * FROM backup_entry WHERE workspace_id = '{_esc(ws)}'"
        )
    except RuntimeError as exc:
        print(f"[backup] ERROR: SQL query failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print("[backup] WARNING: no backup entries found (workspace may be empty).")
        # Still write an empty array so the file is valid JSON
        rows = []

    # 3. Write to file
    backup_data = {
        "workspace_id": ws,
        "exported_at": datetime.utcnow().isoformat(),
        "entries": rows,
    }

    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, indent=2, default=str)

    count = len(rows)
    print(f"[backup] ✓ Exported {count} backup entries to {output}")


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def cmd_import(args: argparse.Namespace) -> None:
    """Import a JSON backup file into the workspace.

    Reads a backup file produced by ``export`` and inserts the entries
    via the ``insert_backup_entries`` reducer.
    """
    ws = args.workspace_id
    input_path = args.input

    if not os.path.isfile(input_path):
        print(f"[backup] ERROR: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[backup] Importing workspace {ws} from {input_path} ...")

    with open(input_path, "r", encoding="utf-8") as f:
        try:
            backup_data = json.load(f)
        except json.JSONDecodeError as exc:
            print(f"[backup] ERROR: invalid JSON in {input_path}: {exc}", file=sys.stderr)
            sys.exit(1)

    entries = backup_data.get("entries", [])
    if not entries:
        print("[backup] WARNING: no entries found in backup file.")
        return

    if not isinstance(entries, list):
        print("[backup] ERROR: 'entries' must be a JSON array.", file=sys.stderr)
        sys.exit(1)

    # Validate required fields
    for i, e in enumerate(entries):
        for field in ("id", "table_name", "record_id", "data_json"):
            if field not in e:
                print(
                    f"[backup] ERROR: entry {i} missing required field '{field}'",
                    file=sys.stderr,
                )
                sys.exit(1)

    client = _get_client()

    # Call the insert_backup_entries reducer (batch insert).
    try:
        client._call("insert_backup_entries", [ws, json.dumps(entries)])
    except RuntimeError as exc:
        print(
            f"[backup] ERROR: insert_backup_entries reducer failed: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[backup] ✓ Imported {len(entries)} backup entries into workspace {ws}")


# ---------------------------------------------------------------------------
# S3 upload
# ---------------------------------------------------------------------------

def cmd_s3_upload(args: argparse.Namespace) -> None:
    """Upload a file to S3 using boto3 (optional dependency)."""
    file_path = args.file
    bucket = args.bucket
    prefix = args.prefix

    if not os.path.isfile(file_path):
        print(f"[backup] ERROR: file not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    try:
        import boto3
    except ImportError:
        print(
            "[backup] ERROR: boto3 is not installed. Install it with:\n"
            "    pip install boto3\n"
            "Or use a different upload method.",
            file=sys.stderr,
        )
        sys.exit(1)

    filename = os.path.basename(file_path)
    key = f"{prefix}/{filename}" if prefix else filename

    print(f"[backup] Uploading {file_path} to s3://{bucket}/{key} ...")

    try:
        s3 = boto3.client("s3")
        s3.upload_file(file_path, bucket, key)
    except Exception as exc:
        print(f"[backup] ERROR: S3 upload failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"[backup] ✓ Uploaded to s3://{bucket}/{key}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(val: str) -> str:
    """Basic SQL string escaping for single-quoted string literals."""
    return val.replace("'", "''")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backup and restore spacetime-memory data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # export
    export_parser = subparsers.add_parser("export", help="Export workspace to JSON file")
    export_parser.add_argument("workspace_id", help="Workspace ID to export")
    export_parser.add_argument(
        "--output", "-o",
        default="backup.json",
        help="Output file path (default: backup.json)",
    )
    export_parser.set_defaults(func=cmd_export)

    # import
    import_parser = subparsers.add_parser("import", help="Import workspace from JSON file")
    import_parser.add_argument("workspace_id", help="Workspace ID to import into")
    import_parser.add_argument("input", help="JSON backup file to import")
    import_parser.set_defaults(func=cmd_import)

    # s3-upload
    s3_parser = subparsers.add_parser("s3-upload", help="Upload a file to S3")
    s3_parser.add_argument("file", help="Path to the file to upload")
    s3_parser.add_argument(
        "--bucket", "-b",
        default=os.environ.get("BACKUP_S3_BUCKET", "my-bucket"),
        help="S3 bucket name (default: $BACKUP_S3_BUCKET or 'my-bucket')",
    )
    s3_parser.add_argument(
        "--prefix", "-p",
        default=os.environ.get("BACKUP_S3_PREFIX", "spacetime-backups"),
        help="S3 key prefix (default: $BACKUP_S3_PREFIX or 'spacetime-backups')",
    )
    s3_parser.set_defaults(func=cmd_s3_upload)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
