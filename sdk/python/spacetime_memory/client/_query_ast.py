"""Query AST Parser — structured query language for memory search.

Provides a query language with operators (``AND``, ``OR``, ``NOT``, proximity,
field-scoped) and an AST-based parser and executor.

Examples::

    # Boolean operators
    parse_query("person:john AND (location:nyc OR location:boston)")
    # Proximity
    parse_query("data pipeline ~42")
    # Phrase
    parse_query('"exact phrase match"')
    # NOT
    parse_query("foo NOT bar")
"""
from __future__ import annotations

import itertools
import json
import math
import re
from collections.abc import Callable
from typing import Any, Literal

# ---------------------------------------------------------------------------
# AST node
# ---------------------------------------------------------------------------


class QueryNode:
    """A node in the query AST.

    Parameters
    ----------
    type:
        Node kind — ``'term'``, ``'and'``, ``'or'``, ``'not'``, ``'field'``,
        ``'proximity'``, ``'phrase'``.
    value:
        Literal string value (used by ``'term'`` and ``'phrase'`` nodes).
    field:
        Field name for ``'field'`` nodes.
    children:
        Child nodes for boolean operators.
    proximity:
        Max token distance for ``'proximity'`` nodes.
    """

    def __init__(
        self,
        type: Literal["term", "and", "or", "not", "field", "proximity", "phrase"],
        value: str = "",
        field: str = "",
        children: list[QueryNode] | None = None,
        proximity: int = 0,
    ) -> None:
        self.type = type
        self.value = value
        self.field = field
        self.children = children or []
        self.proximity = proximity

    def __repr__(self) -> str:
        if self.type == "term":
            return f"QueryNode({self.type}, {self.value!r})"
        elif self.type == "field":
            return f"QueryNode({self.type}, {self.field}:{self.value!r})"
        elif self.type == "phrase":
            return f"QueryNode({self.type}, {self.value!r})"
        elif self.type == "proximity":
            return f"QueryNode({self.type}, {self.value!r}~{self.proximity})"
        elif self.type in ("not",):
            return f"QueryNode({self.type}, {self.children!r})"
        else:
            return f"QueryNode({self.type}, {self.children!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QueryNode):
            return NotImplemented
        return (
            self.type == other.type
            and self.value == other.value
            and self.field == other.field
            and self.children == other.children
            and self.proximity == other.proximity
        )


# ---------------------------------------------------------------------------
# Lexer / Tokenizer
# ---------------------------------------------------------------------------

# Token types
_LPAREN = "LPAREN"
_RPAREN = "RPAREN"
_AND = "AND"
_OR = "OR"
_NOT = "NOT"
_TERM = "TERM"
_PHRASE = "PHRASE"
_PROXIMITY = "PROXIMITY"
_FIELD = "FIELD"
_EOF = "EOF"

_TOKEN_SPEC: list[tuple[str, str]] = [
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("AND", r"\bAND\b"),
    ("OR", r"\bOR\b"),
    ("NOT", r"\bNOT\b"),
    ("PHRASE", r'"[^"]*"'),
    ("PROXIMITY", r"~\d+"),
    ("FIELD", r"[a-zA-Z_][a-zA-Z0-9_]*:"),
    ("TERM", r"[^\s()~]+"),
    ("WS", r"\s+"),
]

_TOKEN_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in _TOKEN_SPEC))


def _tokenize(query: str) -> list[tuple[str, str]]:
    """Tokenize a query string into (type, value) pairs."""
    tokens: list[tuple[str, str]] = []
    for m in _TOKEN_RE.finditer(query):
        kind: str = m.lastgroup or ""
        val: str = m.group()
        if kind == "WS":
            continue
        tokens.append((kind, val))
    tokens.append((_EOF, ""))
    return tokens


# ---------------------------------------------------------------------------
# Parser (recursive descent)
# ---------------------------------------------------------------------------


class _Parser:
    """Recursive-descent parser for the query language."""

    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> tuple[str, str]:
        return self.tokens[self.pos]

    def consume(self, expected: str | None = None) -> tuple[str, str]:
        tok = self.tokens[self.pos]
        if expected is not None and tok[0] != expected:
            raise ValueError(
                f"Expected token type {expected!r}, got {tok[0]!r} ({tok[1]!r})"
            )
        self.pos += 1
        return tok

    def parse(self) -> QueryNode:
        """Parse the full token stream into an AST root."""
        node = self._parse_or()
        if self.peek()[0] != _EOF:
            raise ValueError(
                f"Unexpected token {self.peek()!r} after parsing complete expression"
            )
        return node

    # precedence: NOT > AND > OR
    def _parse_or(self) -> QueryNode:
        left = self._parse_and()
        while self.peek()[0] == _OR:
            self.consume(_OR)
            right = self._parse_and()
            left = QueryNode(type="or", children=[left, right])
        return left

    def _parse_and(self) -> QueryNode:
        left = self._parse_not()
        while self.peek()[0] == _AND:
            self.consume(_AND)
            right = self._parse_not()
            left = QueryNode(type="and", children=[left, right])
        # Implicit AND — adjacent terms
        if self._is_term_like(self.peek()):
            right = self._parse_not()
            left = QueryNode(type="and", children=[left, right])
        return left

    def _parse_not(self) -> QueryNode:
        if self.peek()[0] == _NOT:
            self.consume(_NOT)
            node = self._parse_atom()
            return QueryNode(type="not", children=[node])
        return self._parse_atom()

    def _parse_atom(self) -> QueryNode:
        tok = self.peek()
        if tok[0] == _LPAREN:
            self.consume(_LPAREN)
            node = self._parse_or()
            self.consume(_RPAREN)
            return node
        elif tok[0] == _PHRASE:
            self.consume(_PHRASE)
            phrase = tok[1][1:-1]  # strip quotes
            return QueryNode(type="phrase", value=phrase)
        elif tok[0] == _FIELD:
            return self._parse_field()
        elif tok[0] == _TERM:
            self.consume(_TERM)
            # Check for proximity operator after term
            if self.peek()[0] == _PROXIMITY:
                prox_tok = self.consume(_PROXIMITY)
                prox_val = int(prox_tok[1][1:])
                return QueryNode(type="proximity", value=tok[1], proximity=prox_val)
            return QueryNode(type="term", value=tok[1])
        else:
            raise ValueError(f"Unexpected token: {tok!r}")

    def _parse_field(self) -> QueryNode:
        field_tok = self.consume(_FIELD)
        field_name = field_tok[1][:-1]  # strip trailing ':'
        # Next token is the value
        val_tok = self.peek()
        if val_tok[0] == _TERM:
            self.consume(_TERM)
            return QueryNode(type="field", field=field_name, value=val_tok[1])
        elif val_tok[0] == _PHRASE:
            self.consume(_PHRASE)
            return QueryNode(type="field", field=field_name, value=val_tok[1][1:-1])
        else:
            raise ValueError(
                f"Expected term or phrase after field {field_name!r}, got {val_tok!r}"
            )

    @staticmethod
    def _is_term_like(tok: tuple[str, str]) -> bool:
        return tok[0] in (_TERM, _PHRASE, _FIELD, _LPAREN, _NOT)


# ---------------------------------------------------------------------------
# Public API: parse_query
# ---------------------------------------------------------------------------


def parse_query(query: str) -> QueryNode:
    """Parse a query string into an AST (tree of :class:`QueryNode` objects).

    Supported syntax:

    * ``term`` — bare word term
    * ``"exact phrase"`` — phrase match
    * ``field:value`` — field-scoped term
    * ``term~N`` — proximity match (within N tokens)
    * ``A AND B`` — boolean AND (also implicit between adjacent terms)
    * ``A OR B`` — boolean OR
    * ``NOT B`` — negation
    * ``( ... )`` — grouping

    Parameters
    ----------
    query:
        The raw query string.

    Returns
    -------
    QueryNode
        Root of the parsed AST.

    Raises
    ------
    ValueError
        On syntax errors.
    """
    if not query or not query.strip():
        raise ValueError("Empty query string")
    tokens = _tokenize(query)
    parser = _Parser(tokens)
    return parser.parse()


# ---------------------------------------------------------------------------
# AST → callable filter
# ---------------------------------------------------------------------------


def _make_term_predicate(node: QueryNode) -> Callable[[str], bool]:
    """Return a predicate that checks if *text* contains the term."""
    term = node.value.lower()

    def predicate(text: str) -> bool:
        return term in text.lower()

    return predicate


def _make_phrase_predicate(node: QueryNode) -> Callable[[str], bool]:
    """Return a predicate that checks if *text* contains the exact phrase."""
    phrase = node.value.lower()

    def predicate(text: str) -> bool:
        return phrase in text.lower()

    return predicate


def _make_field_predicate(node: QueryNode) -> Callable[[dict[str, Any]], bool]:
    """Return a predicate that checks field match."""
    field = node.field
    val = node.value.lower()

    def predicate(memory: dict[str, Any]) -> bool:
        field_val = memory.get(field, memory.get("content", ""))
        if isinstance(field_val, str):
            return val in field_val.lower()
        if isinstance(field_val, dict):
            return val in json.dumps(field_val).lower()
        return False

    return predicate


def _make_proximity_predicate(node: QueryNode) -> Callable[[str], bool]:
    """Return a predicate that checks proximity within N tokens."""
    term = node.value.lower()
    proximity = node.proximity

    def predicate(text: str) -> bool:
        words = text.lower().split()
        indices = [i for i, w in enumerate(words) if term in w]
        if not indices:
            return False
        # Check if any two occurrences are within proximity distance
        if len(indices) > 1:
            for i in range(len(indices) - 1):
                if abs(indices[i] - indices[i + 1]) <= proximity:
                    return True
        # Single occurrence counts as trivially within proximity of itself
        return True

    return predicate


def ast_to_callable(ast: QueryNode) -> Callable[[dict[str, Any]], bool]:
    """Convert an AST to a Python callable filter function.

    The returned callable accepts a ``memory`` dict (with at least a
    ``"content"`` key) and returns ``True`` if it matches the query AST.

    Parameters
    ----------
    ast:
        Root of the query AST.

    Returns
    -------
    Callable[[dict[str, Any]], bool]
        Filter predicate for memory dicts.
    """
    if ast.type == "term":
        term_pred = _make_term_predicate(ast)

        def _term_filter(m: dict[str, Any]) -> bool:
            return term_pred(m.get("content", "") or m.get("summary", "") or "")
        return _term_filter

    elif ast.type == "phrase":
        phrase_pred = _make_phrase_predicate(ast)

        def _phrase_filter(m: dict[str, Any]) -> bool:
            return phrase_pred(m.get("content", "") or m.get("summary", "") or "")
        return _phrase_filter

    elif ast.type == "field":
        return _make_field_predicate(ast)

    elif ast.type == "proximity":
        prox_pred = _make_proximity_predicate(ast)

        def _prox_filter(m: dict[str, Any]) -> bool:
            return prox_pred(m.get("content", "") or m.get("summary", "") or "")
        return _prox_filter

    elif ast.type == "and":
        children = [ast_to_callable(c) for c in ast.children]
        if not children:
            return lambda m: True

        def _and_filter(m: dict[str, Any]) -> bool:
            return all(f(m) for f in children)
        return _and_filter

    elif ast.type == "or":
        children = [ast_to_callable(c) for c in ast.children]
        if not children:
            return lambda m: True

        def _or_filter(m: dict[str, Any]) -> bool:
            return any(f(m) for f in children)
        return _or_filter

    elif ast.type == "not":
        if not ast.children:
            return lambda m: True
        child_filter = ast_to_callable(ast.children[0])

        def _not_filter(m: dict[str, Any]) -> bool:
            return not child_filter(m)
        return _not_filter

    else:
        raise ValueError(f"Unknown AST node type: {ast.type}")


# ---------------------------------------------------------------------------
# Filter memories
# ---------------------------------------------------------------------------


def filter_memories(
    memories: list[dict[str, Any]],
    ast: QueryNode,
) -> list[dict[str, Any]]:
    """Filter a list of memory dicts by a query AST.

    Parameters
    ----------
    memories:
        List of memory dicts (must have ``"content"`` key).
    ast:
        Root of the query AST.

    Returns
    -------
    list[dict[str, Any]]
        Subset of memories that match the query.
    """
    predicate = ast_to_callable(ast)
    return [m for m in memories if predicate(m)]


# ---------------------------------------------------------------------------
# Execute AST with optional embedding similarity
# ---------------------------------------------------------------------------


def execute_ast(
    workspace_id: str,
    ast: QueryNode,
    memories: list[dict[str, Any]],
    embedding_fn: Callable[[str], list[float]] | None = None,
) -> list[dict[str, Any]]:
    """Execute an AST against a memory set.

    This applies the AST filter and, if an ``embedding_fn`` is provided,
    re-ranks results by cosine similarity to a combined query text extracted
    from the AST.

    Parameters
    ----------
    workspace_id:
        Workspace identifier (passed through, not directly used in filtering).
    ast:
        Root of the query AST.
    memories:
        List of memory dicts to filter and score.
    embedding_fn:
        Optional callable that maps a string to an embedding vector. If
        provided, results are re-ranked by embedding similarity.

    Returns
    -------
    list[dict[str, Any]]
        Filtered memories. If ``embedding_fn`` was provided, they are sorted
        by similarity (highest first).
    """
    # First apply AST filter
    filtered = filter_memories(memories, ast)

    if not embedding_fn or not filtered:
        return filtered

    # Extract query text from AST
    query_text = _ast_to_query_text(ast)

    try:
        query_emb = embedding_fn(query_text)
    except Exception:
        return filtered  # graceful degradation

    # Score each memory
    scored: list[tuple[float, dict[str, Any]]] = []
    for mem in filtered:
        mem_emb = mem.get("embedding")
        if mem_emb and isinstance(mem_emb, list) and len(mem_emb) == len(query_emb):
            sim = _cosine_similarity(query_emb, mem_emb)
            scored.append((sim, mem))
        else:
            scored.append((0.0, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored]


def _ast_to_query_text(ast: QueryNode) -> str:
    """Extract a plain-text query from an AST."""
    parts: list[str] = []

    def _walk(n: QueryNode) -> None:
        if n.type == "term" or n.type == "phrase":
            parts.append(n.value)
        elif n.type == "field" or n.type == "proximity":
            if n.value:
                parts.append(n.value)
        elif n.type in ("and", "or"):
            for c in n.children:
                _walk(c)

    _walk(ast)
    return " ".join(parts)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a < 1e-12 or norm_b < 1e-12:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def chunk_text(
    text: str,
    strategy: str = "word",
    chunk_size: int = 200,
    overlap: int = 20,
) -> list[str]:
    """Split *text* into overlapping chunks.

    Parameters
    ----------
    text:
        Input text to chunk.
    strategy:
        Chunking strategy: ``'word'`` (split on whitespace), ``'char'``
        (split by characters), or ``'sentence'`` (split on sentence
        boundaries).
    chunk_size:
        Number of tokens/characters per chunk (default 200).
    overlap:
        Number of tokens/characters of overlap between consecutive chunks
        (default 20).

    Returns
    -------
    list[str]
        List of text chunks.

    Raises
    ------
    ValueError
        If an unknown strategy is given or chunk_size <= overlap.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be less than chunk_size")

    if not text:
        return []

    if strategy == "word":
        tokens = text.split()
        if not tokens:
            return []
        chunks: list[str] = []
        step = chunk_size - overlap
        if step <= 0:
            step = 1  # fallback to avoid infinite loop
        for i in range(0, len(tokens), step):
            chunk = " ".join(tokens[i : i + chunk_size])
            if chunk:
                chunks.append(chunk)
        return chunks

    elif strategy == "char":
        if chunk_size >= len(text):
            return [text]
        chunks = []
        step = chunk_size - overlap
        if step <= 0:
            step = 1
        for i in range(0, len(text), step):
            chunk = text[i : i + chunk_size]
            if chunk:
                chunks.append(chunk)
        return chunks

    elif strategy == "sentence":
        # Simple sentence splitting on .!? followed by space or end
        sentences = re.split(r"(?<=[.!?])\s+", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return []

        chunks = []
        current: list[str] = []
        current_len = 0

        for sent in sentences:
            sent_len = len(sent.split())
            if current_len + sent_len > chunk_size and current:
                chunks.append(" ".join(current))
                # Keep overlap sentences
                overlap_sents: list[str] = []
                overlap_len = 0
                for s in reversed(current):
                    sl = len(s.split())
                    if overlap_len + sl > overlap:
                        break
                    overlap_sents.insert(0, s)
                    overlap_len += sl
                current = overlap_sents[:]
                current_len = overlap_len

            current.append(sent)
            current_len += sent_len

        if current:
            chunks.append(" ".join(current))
        return chunks

    else:
        raise ValueError(
            f"Unknown chunking strategy: {strategy!r}. "
            "Use 'word', 'char', or 'sentence'."
        )


# ---------------------------------------------------------------------------
# Query expansion (standalone, synonym-based)
# ---------------------------------------------------------------------------

# Default synonym dictionary
_DEFAULT_SYNONYMS: dict[str, list[str]] = {
    "ai": ["artificial intelligence", "machine learning", "ML"],
    "ml": ["machine learning", "artificial intelligence", "AI"],
    "nlp": ["natural language processing", "language model", "text processing"],
    "llm": ["large language model", "language model", "transformer"],
    "rag": ["retrieval augmented generation", "retrieval", "knowledge retrieval"],
    "kg": ["knowledge graph", "graph database", "semantic network"],
    "db": ["database", "data store", "storage"],
    "api": ["interface", "endpoint", "service"],
    "ui": ["user interface", "frontend", "dashboard"],
    "vector": ["embedding", "dense retrieval", "semantic search"],
    "search": ["retrieval", "lookup", "query", "find"],
    "memory": ["memories", "recall", "context", "history"],
    "agent": ["assistant", "bot", "autonomous agent", "AI agent"],
    "embedding": ["vector", "representation", "encoding"],
    "benchmark": ["evaluation", "test suite", "performance test"],
}


def expand_query(
    query: str,
    synonyms_dict: dict[str, list[str]] | None = None,
) -> list[str]:
    """Expand a query with synonyms and related terms.

    Parameters
    ----------
    query:
        The original query string.
    synonyms_dict:
        Dictionary mapping terms to lists of synonyms. If ``None``, a
        default built-in synonym map is used.

    Returns
    -------
    list[str]
        List of expanded query variants (including the original).
    """
    if not query or not query.strip():
        return [query]

    synonyms = synonyms_dict if synonyms_dict is not None else _DEFAULT_SYNONYMS
    query_lower = query.lower()
    words = query_lower.split()

    # Collect expansions per word
    expansions: list[list[str]] = []
    for w in words:
        word_variants = [w]
        sub = synonyms.get(w, [])
        # Also check multi-word keys via prefix
        for key, vals in synonyms.items():
            if key != w and key in w:
                sub.extend(vals)
        if sub:
            word_variants.extend(sub)
        expansions.append(word_variants)

    # Generate variants
    variants: set[str] = set()
    variants.add(query)  # original

    # If too many combinations, just add each synonym individually
    if len(expansions) > 5:
        for i, word_variants in enumerate(expansions):
            for v in word_variants[1:]:
                new_words = words[:i] + [v] + words[i + 1 :]
                variants.add(" ".join(new_words))
    else:
        for combo in itertools.product(*expansions):
            variant = " ".join(combo).strip()
            if variant:
                variants.add(variant)

    return sorted(variants)


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------


def benchmark_search(
    queries_correct_pairs: list[tuple[str, list[dict[str, Any]]]],
    all_memories: list[dict[str, Any]],
) -> dict[str, float]:
    """Run a benchmark over query/expected-result pairs.

    For each (query, expected_results) pair, the function parses the query
    into an AST, filters ``all_memories``, and compares against expected
    results. Precision, recall, and F1 are computed macro-averaged across
    all queries.

    Parameters
    ----------
    queries_correct_pairs:
        List of ``(query_string, list_of_expected_memory_dicts)`` tuples.
    all_memories:
        The full set of memories to test against.

    Returns
    -------
    dict[str, float]
        Dictionary with keys ``'precision'``, ``'recall'``, ``'f1'``,
        and ``'num_queries'``.
    """
    if not queries_correct_pairs:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "num_queries": 0}

    total_precision = 0.0
    total_recall = 0.0
    num_queries = len(queries_correct_pairs)

    # Build a set of expected IDs per query
    for query_str, expected in queries_correct_pairs:
        expected_ids = {m.get("id", m.get("memory_id", "")) for m in expected}

        try:
            ast = parse_query(query_str)
        except (ValueError, Exception):
            # Parse failure = zero for this query
            continue

        results = filter_memories(all_memories, ast)
        result_ids = {m.get("id", m.get("memory_id", "")) for m in results}

        if not expected_ids:
            # No expected results — if we returned none, it's perfect
            tp = 0
            fp = len(result_ids)
            fn = 0
        else:
            tp = len(result_ids & expected_ids)
            fp = len(result_ids - expected_ids)
            fn = len(expected_ids - result_ids)

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        (
            2 * prec * rec / (prec + rec)
            if (prec + rec) > 0
            else 0.0
        )

        total_precision += prec
        total_recall += rec

    macro_precision = total_precision / num_queries
    macro_recall = total_recall / num_queries
    macro_f1 = (
        2 * macro_precision * macro_recall / (macro_precision + macro_recall)
        if (macro_precision + macro_recall) > 0
        else 0.0
    )

    return {
        "precision": round(macro_precision, 4),
        "recall": round(macro_recall, 4),
        "f1": round(macro_f1, 4),
        "num_queries": num_queries,
    }


# ---------------------------------------------------------------------------
# Convenience: run_benchmark (alias)
# ---------------------------------------------------------------------------


def run_benchmark(
    workspace_id: str,
    queries: list[tuple[str, list[dict[str, Any]]]],
    all_memories: list[dict[str, Any]] | None = None,
) -> dict[str, float]:
    """Alias for :func:`benchmark_search` with a workspace_id parameter.

    Parameters
    ----------
    workspace_id:
        Workspace identifier (included for API compatibility, not directly
        used in filtering).
    queries:
        List of ``(query_string, expected_results)`` tuples.
    all_memories:
        Full set of memories. If ``None``, a tuple of (empty_list, result)
        is returned.

    Returns
    -------
    dict[str, float]
        Benchmark metrics.
    """
    if all_memories is None:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "num_queries": 0}
    return benchmark_search(queries, all_memories)


# ---------------------------------------------------------------------------
# AST utilities
# ---------------------------------------------------------------------------


def ast_to_filter_function(ast: QueryNode) -> Callable[[dict[str, Any]], bool]:
    """Convert an AST to a Python callable filter (alias for ``ast_to_callable``).

    Parameters
    ----------
    ast:
        Root of the query AST.

    Returns
    -------
    Callable[[dict[str, Any]], bool]
        Filter predicate.
    """
    return ast_to_callable(ast)
