# Test Effectiveness Audit

## Test Counts
| Language | Count |
|----------|-------|
| Python (pytest) | 4,567 |
| Rust (#[test]) | 442 |
| TypeScript (it()) | 177 |
| **Total** | **5,186** |

Claimed: 5,167 — Actual: 5,186 (difference: +19)

## Coverage Analysis
- Coverage DB tracks only 63/217 Python source files
- Reported statement coverage: 55.0% (6,158 missed / 13,738 statements)
- True line coverage across all Python source: ~33.5%
- The 22.3% figure likely includes all Python files (~127k lines) vs covered lines (~28k)
- Rust (442 tests) and TypeScript (177 tests) are NOT included in coverage measurement

## Low Coverage Hotspots
| File | Lines | Coverage | Impact |
|------|-------|----------|--------|
| cli.py | 4,845 | 0% | Largest untested file |
| sdks/langchain.py | 1,163 | 15.6% | SDK adapter |
| sdks/mem0.py | 1,510 | 18.3% | SDK adapter |
| sdks/zep.py | 2,532 | 19.8% | SDK adapter |
| sdks/honcho.py | 2,291 | 23.6% | SDK adapter |
| sdks/graphiti.py | 1,069 | 55% | SDK adapter |

## Conclusion
- **Test count**: 5,186 (close to claimed 5,167)
- **Coverage**: 55% on tracked files, ~22% on all Python source
- **Root cause**: 154 untracked Python files, large untracked modules (cli.py 4,845 lines, sdks/*)
- **Rust/TS tests not in coverage**: 631 tests excluded from measurement
