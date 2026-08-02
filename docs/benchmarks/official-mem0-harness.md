# Running the Official Mem0 Benchmark Harness against Spacetime-Memory

The Mem0 team publishes their benchmark harness at `mem0ai/memory-benchmarks`
(checked out as a submodule of their main repo). We integrate with it so the
**official code, prompts, judge, and metrics** run against the Spacetime-Memory
engine — the only difference is which memory backend answers `add`/`search`.

## Setup

```bash
# Clone Mem0 and init the evaluation submodule
git clone https://github.com/mem0ai/mem0 ~/mem0
cd ~/mem0 && git submodule update --init evaluation

# Install harness deps into the project venv
/path/to/spacetime-memory/.venv/bin/pip install aiolimiter anthropic
```

## StmemClient

`benchmarks/common/stmem_client.py` implements the same async interface as
`Mem0Client` (`add`, `search`, `delete_user`, `get_user_profile`) backed by the
Spacetime-Memory SDK. Run from the project venv so both the harness deps and
the SDK are importable.

## LoCoMo (official harness)

```bash
cd ~/mem0/evaluation
LLM_BASE_URL=http://localhost:4004/v1 OPENAI_API_KEY=dummy-key \
  /path/to/spacetime-memory/.venv/bin/python -m benchmarks.locomo.run \
    --project-name stmem-full \
    --backend stmem \
    --stmem-db spacetime-memory-v2 \
    --stmem-host 127.0.0.1 --stmem-port 3001 \
    --answerer-model deepseek-v4-flash-free \
    --judge-model deepseek-v4-flash-free \
    --conversations 0,1,2,3,4,5,6,7,8,9 \
    --top-k 200 \
    --dataset-path /path/to/data/locomo10.json \
    --output-dir results/locomo
```

## LongMemEval + BEAM

Same pattern with `-m benchmarks.longmemeval.run` / `-m benchmarks.beam.run`
(both patched to accept `--backend stmem` + `--stmem-*` + `--llm-base-url`).

## Fairness notes

- Mem0's published numbers (results/platform/*.json) use **gpt-5** as both
  answerer and judge on Azure. Our runs use deepseek-v4-flash-free via the
  local LLM proxy — cheaper/faster, so score deltas reflect model choice too.
- The dataset is the same `locomo10.json` (1986 questions total; Mem0 evaluates
  categories 1-4 = 1540 questions).
