#!/usr/bin/env python3
"""Generate API documentation for spacetime-memory SDKs.

Usage:
    python scripts/generate_docs.py [--output docs/api]

Generates:
    - docs/api/python/  - Python SDK API reference (HTML via pydoc)
    - docs/api/typescript/ - TypeScript SDK API reference (Markdown from JSDoc)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_API = ROOT / "docs" / "api"


def extract_jsdoc(filepath: Path) -> list[dict]:
    """Extract JSDoc/TSDoc comments from TypeScript files."""
    with open(filepath) as f:
        content = f.read()

    docs = []
    # Match JSDoc comments followed by export function/interface
    pattern = re.compile(
        r'/\*\*\s*\n(.*?)\*/\s*\nexport\s+(?:async\s+)?function\s+(\w+)|'
        r'/\*\*\s*\n(.*?)\*/\s*\nexport\s+interface\s+(\w+)|'
        r'/\*\*\s*\n(.*?)\*/\s*\nexport\s+type\s+(\w+)',
        re.DOTALL,
    )
    for match in pattern.finditer(content):
        doc_comment = match.group(1) or match.group(3) or match.group(5) or ""
        name = match.group(2) or match.group(4) or match.group(6) or ""
        # Clean doc comment
        lines = []
        for line in doc_comment.split("\n"):
            line = line.strip()
            line = line.lstrip("* ")
            if line:
                lines.append(line)
        docs.append({"name": name, "doc": "\n".join(lines), "file": filepath.name})
    return docs


def generate_python_docs(output_dir: Path) -> int:
    """Generate Python API docs using pydoc."""
    python_dir = ROOT / "sdk" / "python"
    if not python_dir.exists():
        print("Python SDK not found, skipping")
        return 0

    py_output = output_dir / "python"
    py_output.mkdir(parents=True, exist_ok=True)

    # Use pydoc to generate HTML
    modules = [
        "spacetime_memory.client",
        "spacetime_memory.client._memories",
        "spacetime_memory.client._memories_search",
        "spacetime_memory.client._memories_tags",
        "spacetime_memory.client._notes",
        "spacetime_memory.client._kg",
        "spacetime_memory.client._session",
        "spacetime_memory.client._reflection_loop",
        "spacetime_memory.client._reasoning_tiers",
        "spacetime_memory.client._cognitive_ops",
        "spacetime_memory.client._memfs",
        "spacetime_memory.client._interrupt",
        "spacetime_memory.client._checkpoint",
        "spacetime_memory.client._dreaming",
        "spacetime_memory.client._mental_models",
        "spacetime_memory.client._pattern_detection",
        "spacetime_memory.client._pipeline",
        "spacetime_memory.client._rbac",
        "spacetime_memory.client._skills",
        "spacetime_memory.client._export_import",
        "spacetime_memory.client._ontology",
        "spacetime_memory.client._task_queue",
        "spacetime_memory.ingest",
        "spacetime_memory.shmr",
        "spacetime_memory.weibull",
        "spacetime_memory.veracity",
        "spacetime_memory.llm",
    ]

    count = 0
    for mod in modules:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pydoc", mod],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                out_file = py_output / f"{mod.replace('.', '_')}.html"
                # Wrap in a simple HTML template
                html = f"""<!DOCTYPE html>
<html><head><title>{mod} API</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }}
pre {{ background: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; }}
</style></head><body>
<h1>{mod}</h1>
<pre>{result.stdout}</pre>
</body></html>"""
                out_file.write_text(html)
                count += 1
                print(f"  ✓ {mod}")
            else:
                print(f"  ✗ {mod}: pydoc failed")
        except Exception as e:
            print(f"  ✗ {mod}: {e}")

    return count


def generate_typescript_docs(output_dir: Path) -> int:
    """Generate TypeScript API reference as Markdown docs."""
    ts_dir = ROOT / "sdk" / "typescript" / "src"
    if not ts_dir.exists():
        print("TypeScript SDK not found, skipping")
        return 0

    ts_output = output_dir / "typescript"
    ts_output.mkdir(parents=True, exist_ok=True)

    count = 0
    for ts_file in sorted(ts_dir.glob("*.ts")):
        docs = extract_jsdoc(ts_file)
        if not docs:
            continue

        md_lines = [
            f"# {ts_file.stem}",
            "",
            f"Source: `sdk/typescript/src/{ts_file.name}`",
            "",
            "## API Reference",
            "",
        ]

        for entry in docs:
            md_lines.append(f"### {entry['name']}")
            md_lines.append("")
            md_lines.append(entry["doc"])
            md_lines.append("")
            md_lines.append("---")
            md_lines.append("")

        out_file = ts_output / f"{ts_file.stem}.md"
        out_file.write_text("\n".join(md_lines))
        count += 1
        print(f"  ✓ {ts_file.stem}.ts ({len(docs)} exports)")

    # Generate index
    index_lines = ["# TypeScript SDK API Reference", "", "## Modules", ""]
    for ts_file in sorted(ts_dir.glob("*.ts")):
        index_lines.append(f"- [{ts_file.stem}]({ts_file.stem}.md)")
    (ts_output / "index.md").write_text("\n".join(index_lines))

    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DOCS_API))
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Generating Python API docs...")
    py_count = generate_python_docs(output_dir)
    print(f"Python docs: {py_count} modules")

    print("\nGenerating TypeScript API docs...")
    ts_count = generate_typescript_docs(output_dir)
    print(f"TypeScript docs: {ts_count} modules")

    # Generate index
    index = [
        "# SpacetimeMemory API Reference",
        "",
        f"Generated on: automatically",
        "",
        "## Python SDK",
        f"- [{py_count} modules](python/)",
        "",
        "## TypeScript SDK",
        f"- [{ts_count} modules](typescript/index.md)",
        "",
    ]
    (output_dir / "index.md").write_text("\n".join(index))

    print(f"\nDone. Docs written to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
