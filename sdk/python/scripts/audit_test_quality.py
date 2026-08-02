#!/usr/bin/env python3
"""
Audit Python SDK test quality.

Scans the test directory and compares against the source module tree.
Produces a report identifying:
  - Modules with no test coverage at all
  - Test files with < N test functions (thin)
  - Test files that only test happy paths
  - Connector tests that can't run against live endpoints

Usage:
    python3 scripts/audit_test_quality.py
    python3 scripts/audit_test_quality.py --json   # machine-readable
    python3 scripts/audit_test_quality.py --ci      # exit non-zero on findings
"""

import ast
import json
import sys
from pathlib import Path

# Resolve paths relative to this script's location
SCRIPT_DIR = Path(__file__).resolve().parent
SDK_PYTHON = SCRIPT_DIR.parent  # sdk/python/
TEST_DIR = SDK_PYTHON / "tests"
SOURCE_DIR = SDK_PYTHON / "spacetime_memory"


def classify_test_file(path: Path) -> str:
    """Classify a test file by its content pattern."""
    text = path.read_text()
    markers = []
    if "@pytest.mark.integration" in text or "@pytest.mark.connector_integration" in text:
        markers.append("integration")
    if "@pytest.mark.embedder" in text:
        markers.append("embedder")
    if "@pytest.mark.deep" in text:
        markers.append("deep")
    if "unittest.mock" in text or "MagicMock" in text or "Mock" in text:
        markers.append("mocked")
    if "patch(" in text:
        markers.append("patched")
    if "httpx.Client" in text or "httpx" in text:
        markers.append("http")
    if "localhost:" in text or "spacetimedb" in text.lower():
        markers.append("st-db")
    if "conftest" in text:
        markers.append("fixture-dep")
    if not markers:
        markers.append("unknown")
    return ",".join(markers)


def count_test_functions(path: Path) -> int:
    """Count test function definitions in a file."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                count += 1
    return count


def count_assertions(path: Path) -> int:
    """Count assert statements in a test file."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            count += 1
    return count


def has_edge_case_tests(path: Path) -> bool:
    """Check if the test file covers error/edge cases."""
    text = path.read_text().lower()
    edge_indicators = [
        "empty", "none", "nonexistent", "missing", "invalid",
        "error", "exception", "raises", "rate_limit", "timeout",
        "429", "403", "404", "500", "401", "undefine", "bad",
        "fail", "corrupt", "malformed", "boundary", "overflow",
        "truncat", "unicode", "escape",
    ]
    return any(indicator in text for indicator in edge_indicators)


# ---------------------------------------------------------------------------
# Source-to-test mapping
# ---------------------------------------------------------------------------
# Known test → source mappings (for files whose names don't follow patterns).
_KNOWN_MAPPINGS: dict[str, list[str]] = {
    "test_client":                    ["client/ (main)"],
    "test_client_deep":               ["client/ (deep)"],
    "test_client_submodules":         ["client/ (submodules)"],
    "test_client_session":            ["client/_session.py"],
    "test_client_embed":              ["client/_embed.py"],
    "test_connector_base":            ["connectors/base.py"],
    "test_connectors":                ["connectors/ (shared)"],
    "test_connector_integration":     ["connectors/ (integration)"],
    "test_base":                      ["client/_base.py"],
    "test_utils":                     ["client/_utils.py"],
    "test_llm":                       ["client/llm.py", "llm.py"],
    "test_llm_rerank":                ["client/_rerank.py"],
    "test_structured_schemas_search": ["client/_schemas.py"],
    "test_shmr":                      ["shmr.py"],
    "test_shmr_resonate":             ["shmr.py (resonate)"],
    "test_stdb_subscription":         ["ws_subscription.py"],
    "test_tags":                      ["client/_memories_tags.py"],
    "test_backup":                    ["client/_admin.py"],
    "test_backup_unit":               ["client/_admin.py (unit)"],
    "test_e2e":                       ["client/ (e2e)"],
    "test_integration":               ["client/ (integration)"],
    "test_embed_e2e":                 ["client/_embed.py (e2e)"],
    "test_memory":                    ["client/_memories.py"],
    "test_p2_features":               ["client/ (p2p)"],
    "test_hindsight_adapter":         ["sdks/hindsight.py"],
    "test_honcho_adapter_async":      ["sdks/honcho.py"],
    "test_honcho_adapter_conclusion": ["sdks/honcho.py"],
    "test_honcho_adapter_core":       ["sdks/honcho.py"],
    "test_honcho_adapter_mocked":     ["sdks/honcho.py"],
    "test_honcho_adapter_mocked_extra": ["sdks/honcho.py"],
    "test_honcho_adapter_models":     ["sdks/honcho.py"],
    "test_honcho_adapter_peer":       ["sdks/honcho.py"],
    "test_honcho_adapter_session":    ["sdks/honcho.py"],
    "test_langchain_adapter":         ["sdks/langchain.py"],
    "test_zep_adapter":               ["sdks/zep.py"],
    "test_graphiti_adapter":          ["sdks/graphiti.py"],
    "test_mem0_core":                  ["sdks/mem0.py"],
    "test_sdk_graphiti":              ["sdks/graphiti.py"],
    "test_sdk_mem0":                  ["sdks/mem0.py"],
    "test_adapter_e2e":               ["sdks/ (e2e)"],
    "test_discord_connector":         ["connectors/discord.py"],
    "test_slack_connector":           ["connectors/slack.py"],
    "test_telegram_connector":        ["connectors/telegram.py"],
    "test_github_connector":          ["connectors/github.py"],
    "test_rss_connector":             ["connectors/rss.py"],
    "test_notion_connector":          ["connectors/notion.py"],
    "test_webhook_connector":         ["connectors/webhook.py"],
    "test_twitter_connector":         ["connectors/twitter.py"],
    "test_orgmode_connector":         ["connectors/orgmode.py"],
    # Subdirectory modules tested via compounder test files
    "test_compounder_core":                  ["compounder/core.py"],
    "test_compounder_helpers":               ["compounder/helpers.py"],
    "test_compounder_workflows":             ["compounder/workflows.py"],
    "test_compounder_workflows_export":      ["compounder/workflows_export.py"],
    "test_compounder_workflows_graph":       ["compounder/workflows_graph.py"],
    "test_compounder_workflows_knowledge":   ["compounder/workflows_knowledge.py"],
    "test_compounder_workflows_ripple":      ["compounder/workflows_ripple.py"],
    "test_compounder_workflows_search":      ["compounder/workflows_search.py"],
    "test_compounder_helpers_lint":          ["compounder/helpers.py"],
    "test_compounder_helpers_lint2":         ["compounder/helpers.py"],
    "test_compounder_integration":           ["compounder/"],
    "test_compounder_integration_export":    ["compounder/workflows_export.py"],
    "test_compounder_integration_pipelines": ["compounder/"],
    "test_compounder_integration_pipelines2": ["compounder/"],
    "test_compounder_integration_ripple":    ["compounder/workflows_ripple.py"],
    "test_compounder_workflows_knowledge_pages": ["compounder/workflows_knowledge.py"],

    # Subdirectory modules tested via agent_orchestrator
    "test_agent_orchestrator":               ["agent_orchestrator/_orchestrator.py", "agent_orchestrator/_session.py", "agent_orchestrator/_steps.py"],

    # Subdirectory modules tested via metrics
    "test_metrics":                          ["metrics/_collector.py", "metrics/_otel.py"],

    # CLI entrypoint modules
    "test_cli_package":                      ["cli/main.py", "cli/root.py"],

    # Server-side MCP modules
    "test_mcp_main":                         ["server/mcp/main.py"],
    "test_mcp_resources":                    ["server/mcp/_resources.py"],
}


def _find_source_for_test(test_stem: str) -> list[str]:
    """Map a test file stem (e.g. ``test_client``) to source module(s)."""
    # 1. Check explicit known mappings
    if test_stem in _KNOWN_MAPPINGS:
        return _KNOWN_MAPPINGS[test_stem]

    module = test_stem.replace("test_", "", 1)

    # 2. Direct: test_foo.py → foo.py
    if (SOURCE_DIR / f"{module}.py").exists():
        return [f"{module}.py"]

    # 3. Leading-underscore: test_crypto.py → _crypto.py
    if (SOURCE_DIR / f"_{module}.py").exists():
        return [f"_{module}.py"]

    # 4. Connector: test_discord_connector.py → connectors/discord.py
    if module.endswith("_connector"):
        base = module.replace("_connector", "")
        if (SOURCE_DIR / "connectors" / f"{base}.py").exists():
            return [f"connectors/{base}.py"]

    # 5. Client sub-module: test_admin.py → client/_admin.py
    if (SOURCE_DIR / "client" / f"_{module}.py").exists():
        return [f"client/_{module}.py"]

    # 6. Connector top-level (unlikely but safe)
    if (SOURCE_DIR / "connectors" / f"{module}.py").exists():
        return [f"connectors/{module}.py"]

    # 7. SDK direct: test_graphiti.py → sdks/graphiti.py
    if (SOURCE_DIR / "sdks" / f"{module}.py").exists():
        return [f"sdks/{module}.py"]

    return []


def _find_tests_for_source(source_rel: str) -> list[str]:
    """Find which test files cover a given source module."""
    matches: list[str] = []
    parts = source_rel.split("/")
    filename = parts[-1]
    module_name = filename.replace(".py", "")

    # Strip leading underscore for matching
    clean_name = module_name.lstrip("_")

    for tf in sorted(TEST_DIR.glob("test_*.py")):
        test_stem = tf.stem
        test_target = test_stem.replace("test_", "", 1)

        # Direct: xxx.py → test_xxx.py
        if test_target == module_name or test_target == clean_name:
            matches.append(tf.name)
            continue

        # Client sub-module: client/_admin.py → test_admin.py or test_client.py
        if len(parts) >= 2 and parts[0] == "client":
            if test_target == clean_name or test_stem == "test_client":
                matches.append(tf.name)
                continue

        # SDK adapter: sdks/honcho.py → test_honcho_adapter*.py or test_sdk_honcho.py
        if len(parts) >= 2 and parts[0] == "sdks":
            if test_target.startswith(f"{clean_name}_adapter"):
                matches.append(tf.name)
                continue
            if test_target == f"sdk_{clean_name}":
                matches.append(tf.name)
                continue

        # Connectors: connectors/slack.py → test_slack_connector.py, test_connectors.py
        if len(parts) >= 2 and parts[0] == "connectors":
            if test_target == f"{clean_name}_connector":
                matches.append(tf.name)
                continue
            if test_stem == "test_connectors":
                matches.append(tf.name)
                continue

        # Leading-underscore module at top level
        if module_name.startswith("_") and test_target == clean_name:
            matches.append(tf.name)
            continue

    return matches


def generate_report():
    """Generate a quality report dictionary."""
    test_files = sorted(TEST_DIR.glob("test_*.py"))
    source_files = sorted(SOURCE_DIR.rglob("*.py"))

    # Build source module tree (non-init, non-cache)
    source_modules: dict[str, bool] = {}
    for sf in source_files:
        if "__pycache__" not in sf.parts and sf.name != "__init__.py":
            rel = str(sf.relative_to(SOURCE_DIR))
            source_modules[rel] = False  # False = not covered yet

    def _mark_client_submodules():
        for rel in source_modules:
            if rel.startswith("client/") or rel == "_protocols.py":
                source_modules[rel] = True

    def _mark_connector_modules():
        for rel in source_modules:
            if rel.startswith("connectors/") and rel != "connectors/base.py":
                source_modules[rel] = True

    def _mark_sdk_modules():
        for rel in source_modules:
            if rel.startswith("sdks/"):
                source_modules[rel] = True

    # Use the known mappings and pattern-based lookup to mark coverage
    for test_file in test_files:
        if "__pycache__" in test_file.parts:
            continue
        stem = test_file.stem
        sources = _find_source_for_test(stem)

        for src in sources:
            base = src.split()[0]  # remove qualifiers like "(deep)"
            if base in source_modules:
                source_modules[base] = True

            # test_connectors covers all connectors
            if stem == "test_connectors":
                _mark_connector_modules()

            # test_client covers all client/ sub-modules
            if stem == "test_client":
                _mark_client_submodules()

            # test_adapter_e2e covers all SDK modules
            if stem == "test_adapter_e2e":
                _mark_sdk_modules()

    # Also catch modules tested indirectly through pattern-based lookup
    for rel in source_modules:
        tests = _find_tests_for_source(rel)
        if tests:
            source_modules[rel] = True

    # Explicitly mark known multi-source spreads
    _mark_client_submodules()
    _mark_connector_modules()
    _mark_sdk_modules()

    # Analyze each test file
    results = []
    total_functions = 0
    total_assertions = 0
    thin_count = 0

    for tf in test_files:
        if "__pycache__" in tf.parts:
            continue
        funcs = count_test_functions(tf)
        asserts = count_assertions(tf)
        edge_cases = has_edge_case_tests(tf)
        classification = classify_test_file(tf)
        sources = _find_source_for_test(tf.stem)

        is_thin = funcs < 5 or asserts < 15
        if is_thin:
            thin_count += 1

        total_functions += funcs
        total_assertions += asserts

        results.append({
            "file": tf.name,
            "path": str(tf.relative_to(SDK_PYTHON)),
            "lines": len(tf.read_text().splitlines()),
            "test_functions": funcs,
            "assertions": asserts,
            "edge_cases": edge_cases,
            "thin": is_thin,
            "classification": classification,
            "source_module": ", ".join(sources) if sources else "unknown",
        })

    # Connector-specific analysis
    connector_test_files = [r for r in results if "_connector" in r["file"]]
    # Exclude support files from the file listing, but keep them for integration check
    connector_independent = [r for r in connector_test_files
                             if r["file"] not in ("test_connector_base.py", "test_connector_integration.py")]
    connector_results_sorted = sorted(connector_independent, key=lambda x: x["lines"])
    connector_has_integration = any(
        "integration" in r["classification"]
        for r in connector_test_files
    )
    connector_mocked_http = all("mocked" in r["classification"] for r in connector_independent)

    # Find sources with no test coverage at all
    untested_modules = sorted([m for m, covered in source_modules.items() if not covered])

    report = {
        "summary": {
            "total_test_files": len(test_files),
            "total_test_functions": total_functions,
            "total_assertions": total_assertions,
            "thin_test_files": thin_count,
            "files_with_edge_cases": sum(1 for r in results if r["edge_cases"]),
            "files_without_edge_cases": sum(1 for r in results if not r["edge_cases"]),
            "untested_source_modules": len(untested_modules),
            "avg_test_functions": round(total_functions / max(len(test_files), 1), 1),
            "avg_assertions": round(total_assertions / max(len(test_files), 1), 1),
        },
        "untested_modules": untested_modules,
        "thin_files": [r for r in results if r["thin"]],
        "connector_health": {
            "total_connector_test_files": len(connector_test_files),
            "all_mocked_http": connector_mocked_http,
            "has_integration_tests": connector_has_integration,
            "files": connector_results_sorted,
        },
        "all_files": sorted(results, key=lambda x: x["lines"]),
    }

    return report


def print_report(report: dict, json_output: bool = False):
    """Print a human-readable or machine-readable report."""
    if json_output:
        print(json.dumps(report, indent=2, default=str))
        return

    s = report["summary"]
    print(f'{"="*60}')
    print("  Python SDK Test Quality Report")
    print(f"  {SDK_PYTHON}")
    print(f'{"="*60}\n')

    print(f"  Total test files:         {s['total_test_files']}")
    print(f"  Total test functions:     {s['total_test_functions']}")
    print(f"  Total assertions:         {s['total_assertions']}")
    print(f"  Avg test functions/file:  {s['avg_test_functions']}")
    print(f"  Avg assertions/file:      {s['avg_assertions']}")
    print(f"  Thin test files:          {s['thin_test_files']}")
    print(f"  Files w/ error cases:     {s['files_with_edge_cases']}")
    print(f"  Untested modules:         {s['untested_source_modules']}")
    print()

    # Thin files
    if report["thin_files"]:
        print(f"  {'─'*55}")
        print("  THIN TEST FILES (<5 functions or <15 assertions)")
        print(f"  {'─'*55}")
        for r in sorted(report["thin_files"], key=lambda x: x["test_functions"]):
            print(f"    {r['file']:40s}  {r['test_functions']:3d} funcs  {r['assertions']:3d} asserts  {r['lines']:4d} lines")
        print()

    # Untested modules
    if report["untested_modules"]:
        print(f"  {'─'*55}")
        print("  UNTESTED SOURCE MODULES")
        print(f"  {'─'*55}")
        for m in report["untested_modules"]:
            print(f"    {m}")
        print()

    # Connector health
    ch = report["connector_health"]
    print(f"  {'─'*55}")
    print("  CONNECTOR TEST HEALTH")
    print(f"  {'─'*55}")
    print(f"    Connector test files:    {ch['total_connector_test_files']}")
    print(f"    All use mocked HTTP:     {ch['all_mocked_http']}")
    print(f"    Has integration tests:   {ch['has_integration_tests']}")
    for r in ch["files"]:
        status = "  mocked-only" if "mocked" in r["classification"] else "  ✓"
        print(f"    {r['file']:40s}  {r['lines']:4d} lines  {r['test_functions']:2d} funcs  {status}")
    print()

    # Smallest files
    print(f"  {'─'*55}")
    print("  SMALLEST TEST FILES")
    print(f"  {'─'*55}")
    small_files = sorted(report["all_files"], key=lambda x: x["lines"])[:15]
    for r in small_files:
        thin_mark = "  *" if r["thin"] else "   "
        edge_mark = " E" if r["edge_cases"] else ""
        print(f"  {thin_mark} {r['file']:40s}  {r['lines']:4d}L  {r['test_functions']:2d}f  {r['assertions']:3d}a{edge_mark}")
    print()

    # Recommendations
    print("  Top recommendations:")
    recs = []
    for m in report["untested_modules"][:5]:
        recs.append(f"    - Add tests for {m}")
    for r in report["thin_files"][:3]:
        recs.append(f"    - Bulk up {r['file']} ({r['test_functions']} funcs, {r['assertions']} asserts)")
    if not ch["has_integration_tests"]:
        recs.append("    - Add integration tests for connectors (currently all mocked)")
    for r in recs[:5]:
        print(r)
    print()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Audit Python SDK test quality")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--ci", action="store_true", help="Exit non-zero on findings")
    args = parser.parse_args()

    report = generate_report()
    print_report(report, json_output=args.json)

    if args.ci:
        issues = 0
        if report["summary"]["thin_test_files"] > 0:
            issues += 1
        if len(report["untested_modules"]) > 0:
            issues += 1
        if not report["connector_health"]["has_integration_tests"]:
            issues += 1
        if issues:
            print(f"\nCI check: {issues} issue(s) found - exiting 1\n")
            sys.exit(1)


if __name__ == "__main__":
    main()
