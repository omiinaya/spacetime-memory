# Standardized Benchmarks

This directory contains standardized evaluation scripts that follow the **same
methodology as Mem0's open-source benchmark suite** for fair, apples-to-apples
comparisons.

## Why

Previously, our benchmark scores were collected using:
- A 199-question sample (not the full 1,980+ question dataset)
- A hybrid substring/keyword/LLM judge methodology
- In-process BM25 instead of the real STDB pipeline for some benchmarks

This made our numbers **not directly comparable** to competitor results. The
scripts here fix that by adopting the exact same evaluation methodology used by
Mem0, the current leader: structured LLM judge with detailed rubrics, full
dataset evaluation, and real pipeline testing.

## Available Benchmarks

| Script | Dataset | Questions | What it tests |
|--------|---------|-----------|---------------|
| `run_locomo.py` | LoCoMo (Snap Research) | 1,540 (categories 1-4) | Factual recall, temporal, multi-hop, open-domain |
| `run_beam.py` | BEAM | 700+ | Real-world memory across 10 ability types |
| `run_longmemeval.py` | LongMemEval | 500 | Long-term memory retrieval |

## Methodology

Each benchmark follows a three-stage pipeline:

1. **Ingest** — Store conversation data into the memory system
2. **Search** — Retrieve relevant memories for each question
3. **Evaluate** — Answer via LLM, then judge via LLM

The judge uses Mem0's exact prompt with these rules:
- Paraphrases count as correct
- Extra detail is fine — never penalize
- 14-day date tolerance
- Same referent = correct
- Focus on knowledge, not wording

## Usage

```bash
# LoCoMo — full evaluation (1,540 questions)
python scripts/benchmarks/run_locomo.py --stdb

# LoCoMo — quick check (single conversation)
python scripts/benchmarks/run_locomo.py --stdb --conv 0 --limit 10

# LoCoMo — BM25 baseline comparison
python scripts/benchmarks/run_locomo.py --bm25
```

## Results

Results are saved to `benchmarks/results/locomo/` and can be compared directly
with the `results/` directory from Mem0's benchmark suite.
