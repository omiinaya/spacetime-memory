#!/usr/bin/env python3
"""Latency-at-Scale benchmark for Spacetime Memory.

Measures search/store latency as dataset grows from 10 to 100K+ memories.
Critical for beating Zep's claim of "sub-200ms retrieval at 100M facts."

Usage:
    python3 scripts/latency_at_scale_benchmark.py [--sizes 10,100,1000,10000]
    python3 scripts/latency_at_scale_benchmark.py --quick
"""

import json
import os
import sys
import time
import random
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk" / "python"))

import httpx
from spacetime_memory import Client

STDB_URL = os.environ.get("SPACETIMEDB_URL", "http://localhost:3001")
EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://localhost:9090")
TANTIVY_URL = os.environ.get("TANTIVY_URL", "http://localhost:9091")
DB = os.environ.get(
    "SPACETIMEDB_DB",
    "c20076381c624767a61e93ef07b3a8f2a2f012f11d5312a479dbcecc72066e5c",
)

# Template memories and queries at different complexity levels
FACT_TEMPLATES = [
    "The {noun} was invented by {person} in {year}.",
    "{noun} is located in {location} and has a population of {number}.",
    "The {concept} algorithm achieved {metric}% accuracy on {dataset}.",
    "{person}'s research on {topic} was published in {year} and cited {number} times.",
    "The {product} framework version {version} was released on {date} with {feature}.",
    "Training {model} on {dataset} required {number} GPU hours and achieved {metric} loss.",
    "The {conference} accepted {number} papers on {topic} in {year}.",
    "Repository {repo} has {number} stars and {number2} forks on GitHub.",
    "The {company} API supports {feature} with rate limit of {number} requests per second.",
    "Version {version} of {library} added support for {feature} and fixed {number} bugs.",
    "Database {db_name} can handle {number} queries per second with {config} configuration.",
    "The {algorithm} approach reduced latency by {percent}% compared to {baseline}.",
    "Framework {framework} version {version} compiles {number}% faster than previous release.",
    "Model {model_name} achieves {metric}% on benchmark {benchmark_name} with {param_count} parameters.",
    "The paper '{title}' proposes {approach} for solving {problem} in {domain}.",
]

QUERY_TEMPLATES = [
    "Who invented the {noun}?",
    "Where is {noun} located?",
    "What accuracy does {concept} achieve on {dataset}?",
    "When was {person}'s research on {topic} published?",
    "What version of {product} was released?",
    "How many GPU hours were needed to train {model}?",
    "How many papers on {topic} were accepted at {conference}?",
    "How many stars does {repo} have?",
    "What is the rate limit for {company} API?",
    "What features were added in {library} version {version}?",
    "What queries per second can {db_name} handle?",
    "How much did {algorithm} reduce latency?",
    "How many parameters does {model_name} have?",
    "What approach does the paper propose for {problem}?",
]

NOUNS = ["transformer", "neural network", "database", "compiler", "operating system",
         "programming language", "search engine", "web framework", "cryptocurrency", "blockchain"]
PERSONS = ["Geoffrey Hinton", "Yann LeCun", "Andrew Ng", "Demis Hassabis", "Ilya Sutskever",
           "Jeff Dean", "Fei-Fei Li", "Andrej Karpathy", "Richard Sutton", "Leslie Valiant"]
TOPICS = ["deep learning", "reinforcement learning", "computer vision", "NLP", "systems",
          "algorithms", "databases", "networking", "security", "distributed systems"]
COMPANIES = ["Google", "OpenAI", "Meta", "DeepMind", "Microsoft",
             "Anthropic", "Tesla", "Apple", "Amazon", "NVIDIA"]
MODELS = ["GPT-4", "Claude 3", "Gemini", "LLaMA", "BERT",
          "T5", "DALL-E", "Stable Diffusion", "Whisper", "CLIP"]
DATASETS = ["ImageNet", "CIFAR-10", "MNIST", "COCO", "SQuAD",
            "GLUE", "SuperGLUE", "WikiText", "BookCorpus", "CommonCrawl"]

random.seed(42)


def generate_memories(count: int) -> list[str]:
    memories = []
    for i in range(count):
        tpl = random.choice(FACT_TEMPLATES)
        memories.append(tpl.format(
            noun=random.choice(NOUNS),
            person=random.choice(PERSONS),
            year=random.randint(1990, 2026),
            location=random.choice(["San Francisco", "New York", "London", "Tokyo", "Beijing", "Zurich", "Toronto", "Paris", "Berlin", "Singapore"]),
            number=random.randint(1, 1000000),
            number2=random.randint(1, 50000),
            concept=random.choice(TOPICS),
            metric=round(random.uniform(80, 99.9), 1),
            dataset=random.choice(DATASETS),
            topic=random.choice(TOPICS),
            product=random.choice(["PyTorch", "TensorFlow", "JAX", "Keras", "MXNet"]),
            version=f"{random.randint(1,5)}.{random.randint(0,20)}.{random.randint(0,10)}",
            date=f"202{random.randint(0,6)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
            feature=random.choice(["distributed training", "mixed precision", "graph mode", "eager mode", "quantization", "pruning", "XLA compilation"]),
            model=random.choice(MODELS),
            conference=random.choice(["NeurIPS", "ICML", "ICLR", "CVPR", "ACL", "EMNLP", "NAACL", "AAAI", "IJCAI", "SOSP"]),
            repo=random.choice(["pytorch/pytorch", "tensorflow/tensorflow", "huggingface/transformers", "openai/gpt-2", "ggerganov/llama.cpp"]),
            percent=random.randint(20, 95),
            company=random.choice(COMPANIES),
            library=random.choice(["NumPy", "Pandas", "Scikit-learn", "JAX", "Flax"]),
            db_name=random.choice(["PostgreSQL", "MySQL", "SQLite", "MongoDB", "Redis", "SpacetimeDB", "DuckDB", "ClickHouse", "DynamoDB", "Cassandra"]),
            config=random.choice(["default", "optimized", "production", "development", "containerized"]),
            algorithm=random.choice(["SGD", "Adam", "RMSProp", "AdaGrad", "AdamW"]),
            baseline=random.choice(["baseline", "prior work", "state-of-the-art", "previous version"]),
            framework=random.choice(["PyTorch Lightning", "HuggingFace", "Keras", "Fastai", "MLX"]),
            model_name=random.choice(MODELS),
            benchmark_name=random.choice(DATASETS),
            param_count=f"{random.choice(['7B', '13B', '70B', '175B', '1.5B', '3B', '8B', '34B', '65B', '120B'])}",
            title=random.choice([
                "Attention Is All You Need", "BERT: Pre-training of Deep Bidirectional Transformers",
                "Learning Transferable Visual Models From Natural Language Supervision",
                "Language Models are Few-Shot Learners", "Training Language Models to Follow Instructions",
                "Scaling Laws for Neural Language Models", "EfficientNet: Rethinking Model Scaling",
                "Deep Residual Learning for Image Recognition", "Generative Adversarial Networks",
                "Playing Atari with Deep Reinforcement Learning",
            ]),
            approach=random.choice(["a novel attention mechanism", "contrastive learning", "self-supervised pre-training",
                                    "reinforcement learning from human feedback", "mixture of experts",
                                    "knowledge distillation", "neural architecture search", "diffusion models",
                                    "sparse transformers", "retrieval-augmented generation"]),
            problem=random.choice(["text classification", "image generation", "machine translation",
                                    "question answering", "speech recognition", "protein folding",
                                    "game playing", "robotics control", "code generation", "mathematical reasoning"]),
            domain=random.choice(["NLP", "CV", "speech", "robotics", "bioinformatics", "code", "math", "music", "gaming", "science"]),
        ))
    return memories


def generate_queries(count: int, memories: list[str]) -> list[str]:
    """Generate queries that should match the seeded memories."""
    queries = []
    for i in range(min(count, len(memories))):
        mem = memories[i]
        # Extract a noun/phrase from the memory
        words = mem.split()
        # Pick a content word 4-8 chars as query
        content_words = [w for w in words if len(w) > 4 and w[0].isalpha() and w[0].isupper()]
        if content_words:
            query = random.choice(content_words)
        else:
            query = " ".join(words[1:4])
        queries.append(query)
    # Add some random queries that may not match
    while len(queries) < count:
        queries.append(f"research on {random.choice(TOPICS)}")
    return queries


def run_scale_point(
    client: Client,
    ws_id: str,
    n_memories: int,
    n_queries: int = 20,
    n_iterations: int = 5,
) -> dict:
    """Seed N memories, then measure latency for search operations."""
    memories = generate_memories(n_memories)
    queries = generate_queries(n_queries, memories)

    # Seed
    seed_start = time.time()
    mem_ids = []
    # Batch store in chunks of 10
    batch_size = 10
    stored = 0
    for i in range(0, len(memories), batch_size):
        batch = memories[i:i+batch_size]
        for mem in batch:
            try:
                r = client.store(
                    workspace_id=ws_id,
                    content=mem,
                    memory_type="scale_test",
                    confidence=0.9,
                )
                if isinstance(r, dict):
                    mid = r.get("id") or r.get("entity_id", "")
                    if mid:
                        mem_ids.append(mid)
                stored += 1
            except (OSError, json.JSONDecodeError):
                pass
        # Index in Tantivy
        time.sleep(0.5)  # Let indexing catch up
    seed_time = time.time() - seed_start

    # Also index in Tantivy
    http = httpx.Client(timeout=10)
    for mid, mem in zip(mem_ids[:min(500, len(mem_ids))], memories[:min(500, len(memories))]):
        try:
            http.post(
                f"{TANTIVY_URL}/index",
                json={"workspace_id": ws_id, "entity_id": mid,
                       "content": mem, "entity_type": "memory"},
                timeout=5,
            )
        except Exception:
            pass
    http.close()

    # Benchmark search latencies
    ops = {
        "keyword_search": lambda q: client.search(
            ws_id, query=q, limit=5, semantic=False, rerank=False),
        "hybrid_search": lambda q: client.search(
            ws_id, query=q, limit=10, semantic=True, rerank=False),
        "graph_query": lambda q: client._query(
            "memory", workspace_id=ws_id, columns=["id"]),
    }

    results = {}
    for op_name, op_fn in ops.items():
        latencies = []
        for _ in range(n_iterations):
            for q in queries[:n_queries]:
                t0 = time.time()
                try:
                    op_fn(q)
                except Exception:
                    pass
                lat = (time.time() - t0) * 1000
                latencies.append(lat)

        if latencies:
            lat_sorted = sorted(latencies)
            n = len(lat_sorted)
            results[op_name] = {
                "p50_ms": round(lat_sorted[n // 2], 2),
                "p90_ms": round(lat_sorted[int(n * 0.9)], 2),
                "p99_ms": round(lat_sorted[int(n * 0.99)], 2),
                "mean_ms": round(sum(lat_sorted) / n, 2),
                "min_ms": round(min(lat_sorted), 2),
                "max_ms": round(max(lat_sorted), 2),
                "samples": n,
            }

    return {
        "n_memories": n_memories,
        "n_queries": n_queries,
        "n_iterations": n_iterations,
        "seed_time_secs": round(seed_time, 1),
        "memories_stored": stored,
        "search": results,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Latency-at-Scale Benchmark")
    parser.add_argument(
        "--sizes", type=str, default="10,100,1000,5000,10000",
        help="Comma-separated dataset sizes to test",
    )
    parser.add_argument("--queries", type=int, default=10, help="Queries per scale point")
    parser.add_argument("--iterations", type=int, default=3, help="Iterations per query")
    parser.add_argument("--quick", action="store_true", help="Quick mode")
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args()

    sizes = [int(x) for x in args.sizes.split(",")]
    if args.quick:
        sizes = [10, 100, 1000]
        args.iterations = 2
        args.queries = 5

    print("=" * 65)
    print("  LATENCY AT SCALE BENCHMARK")
    print("  Measures how search latency degrades as dataset grows")
    print("=" * 65)
    print(f"  Dataset sizes: {sizes}")
    print(f"  Queries/point: {args.queries}, Iterations: {args.iterations}")
    print()

    # Set up client
    resp = httpx.get(f"{STDB_URL}/v1/database/{DB}", timeout=10)
    token = resp.headers.get("spacetime-identity-token", "")
    identity = resp.headers.get("spacetime-identity", "")
    client = Client(database=DB, embedder_url=EMBEDDER_URL, token=token or None)
    try:
        client._call("register", [f"scale-bench-{os.urandom(4).hex()}", "benchmark789", identity])
    except (RuntimeError, OSError, json.JSONDecodeError):
        pass
    ws = client.create_workspace(f"scale-bench-{os.urandom(4).hex()}", "Scale Benchmark")
    ws_id = ws.get("id") or ws.get("workspace_id", "")
    if not ws_id:
        print("ERROR: Could not create workspace", file=sys.stderr)
        return 1
    print(f"  Workspace: {ws_id}")

    all_results = {}
    for size in sizes:
        print(f"\n--- Size={size} memories ---")
        result = run_scale_point(client, ws_id, size, args.queries, args.iterations)
        all_results[str(size)] = result
        print(f"  Seeded {result['memories_stored']} memories in {result['seed_time_secs']}s")
        for op, stats in result.get("search", {}).items():
            print(f"    {op}: p50={stats['p50_ms']}ms  p90={stats['p90_ms']}ms  mean={stats['mean_ms']}ms")

    # Summary table
    print("\n" + "=" * 65)
    print("  LATENCY SCALING SUMMARY (p50 ms)")
    print("=" * 65)
    ops_list = ["keyword_search", "hybrid_search", "graph_query"]
    header = f"{'Size':>10}"
    for op in ops_list:
        header += f" {op[:10]:>12}"
    print(f"  {header}")
    print(f"  {'-'*10} {'-'*12} {'-'*12} {'-'*12}")
    for size in sizes:
        r = all_results[str(size)]
        line = f"  {size:>10}"
        for op in ops_list:
            stats = r.get("search", {}).get(op, {})
            if stats:
                line += f" {stats['p50_ms']:>10.1f}ms"
            else:
                line += f" {'N/A':>12}"
        print(line)

    output_path = args.output or os.path.join(
        Path(__file__).resolve().parent.parent,
        f"benchmark_results_scale_{int(time.time())}.json",
    )
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
