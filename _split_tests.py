#!/usr/bin/env python3
"""Split test_client_deep.py and test_mcp.py by domain.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent
TESTS_DIR = REPO / "sdk" / "python" / "tests"

# ── Domain grouping for test_client_deep.py ──
CLIENT_DEEP_DOMAINS = {
    "health": [
        "TestHealth", "TestKeywordFallback",
    ],
    "memory": [
        "TestContextChain", "TestStoreBatch", "TestStoreBatchDeep",
        "TestMemoryManagement", "TestMergeWorkflow", "TestBatchOps",
        "TestStoreEdge", "TestMergeOps", "TestMemoryRetrieval",
        "TestPatternDetection",
    ],
    "graph": [
        "TestGraphDeep", "TestGraphTraversal",
    ],
    "notes": [
        "TestNotesCRUD", "TestDocuments",
    ],
    "profiles": [
        "TestProfilesDeep", "TestProfileFacts", "TestProfilesWithPeers",
        "TestSessionsDeep",
    ],
    "admin": [
        "TestWorkspaceEdge", "TestTours", "TestEntityLinking",
        "TestBackupRestore", "TestAPIKeys", "TestPeers",
        "TestContextPacks", "TestSearchWithFilters",
        "TestSearchSessionsSemantic", "TestRecommend", "TestDecay",
        "TestDirectories", "TestDeltaSync", "TestDecayDeep",
        "TestParseRerankJson", "TestParseSqlResponse",
        "TestFuzzyGet", "TestGlobGet", "TestUserMemories",
    ],
}

# ── Domain grouping for test_mcp.py ──
MCP_DOMAINS = {
    "mcp_compounder": [
        "TestSearchEntities", "TestIngestSource", "TestLintWorkspace",
        "TestStoreAnswer", "TestStoreAnswersBatch",
        "TestCreateEntityPage", "TestUpdateEntityPage",
        "TestCreateConceptPage", "TestCreateComparisonPage",
        "TestGenerateOverview",
    ],
    "mcp_graph": [
        "TestGetNode", "TestUpdateNode", "TestCreateEdge",
        "TestGetNeighbors", "TestGetCommunity", "TestQueryGraph",
        "TestShortestPath", "TestGraphBFS", "TestComputePagerank",
        "TestComputeCommunityHierarchy", "TestComputeKgStats",
    ],
    "mcp_search": [
        "TestRecommendMemories", "TestSearchSessionsSemantic",
        "TestGetUserMemories", "TestSearchProfiles",
        "TestSearchWithFilters",
    ],
    "mcp_profiles": [
        "TestAddDynamicContext", "TestAddProfileFact",
        "TestGetProfileContext", "TestDeleteFactMCP",
        "TestUpdateFactMCP", "TestSearchFactsMCP",
    ],
    "mcp_memory": [
        "TestDeleteWorkspace", "TestFuzzyGet", "TestDetectPatterns",
        "TestGetNoteByDate", "TestGlobGet", "TestListMemories",
        "TestAddNodeCitation", "TestAddEdgeCitation",
    ],
}

def parse_classes(filepath: Path) -> dict[str, tuple[int, int, str]]:
    """Find class definitions and their line ranges."""
    content = filepath.read_text()
    lines = content.split("\n")
    
    classes: dict[str, tuple[int, int]] = {}  # name -> (start_line, end_line)
    
    class_starts = []
    for i, line in enumerate(lines):
        m = re.match(r'^class (\w+)', line)
        if m:
            class_starts.append((i, m.group(1)))
    
    for idx, (start, name) in enumerate(class_starts):
        if idx + 1 < len(class_starts):
            end = class_starts[idx + 1][0]
        else:
            end = len(lines)
        classes[name] = (start, end)
    
    return classes


def split_file(filepath: Path, domains: dict[str, list[str]], prefix: str):
    """Split a test file by domain."""
    source_name = filepath.name
    classes = parse_classes(filepath)
    source_lines = filepath.read_text().split("\n")
    
    # Find preamble (imports, fixtures) up to the first test class
    first_class_line = min(start for start, _ in [(v[0], k) for k, v in classes.items()])
    preamble = "\n".join(source_lines[:first_class_line])
    
    if not preamble.endswith("\n"):
        preamble += "\n"
    
    for domain, class_names in domains.items():
        output_name = f"{prefix}_{domain}.py"
        output_path = TESTS_DIR / output_name
        
        if output_path.exists():
            print(f"  SKIP (exists): {output_name}")
            continue
        
        content = preamble
        
        for cls in class_names:
            if cls not in classes:
                print(f"  WARNING: {cls} not found in {source_name}")
                continue
            start, end = classes[cls]
            content += "\n".join(source_lines[start:end]) + "\n"
        
        output_path.write_text(content)
        # Count test methods
        test_count = content.count("    def test_")
        print(f"  Created: {output_name} ({len(content.splitlines())} lines, {test_count} tests)")


def main():
    print("=== Splitting test_client_deep.py ===")
    split_file(TESTS_DIR / "test_client_deep.py", CLIENT_DEEP_DOMAINS, "test_client_deep")
    
    print("\n=== Splitting test_mcp.py ===")
    split_file(TESTS_DIR / "test_mcp.py", MCP_DOMAINS, "test_mcp")


if __name__ == "__main__":
    main()
