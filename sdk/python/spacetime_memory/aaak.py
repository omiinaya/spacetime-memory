"""AAAK Compression — Lossless LLM context shorthand.

AAAK (pronounced "ack") is a compression dialect from the Mnemosyne project
(AxDSan/mnemosyne). It applies category abbreviations, phrase substitutions,
structural replacements, and punctuation compaction to produce densely-packed
text that LLMs can parse natively without a formal decompressor.

The design principle: every replacement is visually intuitive. ``PREFERENCE``
becomes ``PREF``. ``User asked for`` becomes ``ASK``. `` and `` becomes ``+``.
An LLM reading the compressed text understands it immediately — no token cost
for a decompression step.

Usage::

    from spacetime_memory.aaak import aak_compress

    compressed = aak_compress(
        "PREFERENCE: User asked for dark mode. STATUS: working correctly"
    )
    # → "PREF|ASK dark mode+STAT|OK"
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List

# ── Rule Loading ────────────────────────────────────────────────────────────

_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "aaak_rules.json"


def _load_rules() -> dict:
    """Load AAAK compression rules from the JSON ruleset."""
    if _RULES_PATH.exists():
        with open(_RULES_PATH) as f:
            return json.load(f)
    # Fallback: embedded minimal ruleset (self-contained)
    return _FALLBACK_RULES


_FALLBACK_RULES = {
    "categories": {
        "PREFERENCE": "PREF", "TRAIT": "TRAIT", "STATUS": "STAT",
        "INSTRUCTION": "INST", "PROJECT": "PROJ", "LOCATION": "LOC",
        "FAMILY": "FAM", "OCCUPATION": "OCC", "DECISION": "DEC",
        "EVENT": "EVT", "TOOL": "TOOL", "FACT": "FACT", "OPINION": "OPN",
    },
    "phrase_table": {
        "User asked ": "ASK ", "User wants ": "WANT ", "User prefers ": "PREF ",
        "User likes ": "LIKE ", "User dislikes ": "DISLIKE ",
        "User is ": "IS ", "User has ": "HAS ", "User built ": "BUILT ",
        "User asked for ": "ASK ", "User requested ": "REQ ",
        "Full-stack developer": "FSDEV", "Software Developer": "SDEV",
        "AI Systems Engineer": "AIENG", "real-time": "RT", "Real-time": "RT",
        "bilingual": "bi", "Bilingual": "bi", "self-hosted": "selfhost",
        "automation": "auto", "transcription": "transc", "translation": "transl",
    },
    "structural": [
        {"match": " - ", "replace": " | "},
        {"match": " -- ", "replace": " | "},
        {"match": ", ", "replace": " | "},
        {"match": " and ", "replace": "+"},
        {"match": " or ", "replace": "/"},
        {"match": " for ", "replace": "→"},
        {"match": " to ", "replace": "→"},
        {"match": " with ", "replace": " w/ "},
        {"match": " over ", "replace": ">"},
        {"match": " instead of ", "replace": "!>"},
        {"match": " because of ", "replace": "\u2235"},
        {"match": " due to ", "replace": "\u2235"},
        {"match": " using ", "replace": "→"},
        {"match": " built ", "replace": "→"},
        {"match": " in ", "replace": ":"},
        {"match": " at ", "replace": "@"},
        {"match": " on ", "replace": "@"},
        {"match": " from ", "replace": "<-"},
    ],
    "trailing_compactions": {
        "working correctly": "OK",
        "working": "OK",
        "complete": "DONE",
        "completed": "DONE",
    },
}

# ── Compilation (module load) ───────────────────────────────────────────────

_rules = _load_rules()

CATEGORIES: Dict[str, str] = _rules["categories"]
PHRASES: Dict[str, str] = _rules["phrase_table"]
STRUCTURAL: List[Dict[str, str]] = _rules["structural"]
TRAILING: Dict[str, str] = _rules.get("trailing_compactions", {})

# Reverse maps for optional decompression
REV_CATEGORIES: Dict[str, str] = {v: k for k, v in CATEGORIES.items()}
REV_PHRASES: Dict[str, str] = {v: k for k, v in PHRASES.items()}

# Sort phrases by length (longest first) for greedy matching
_PHRASES_SORTED = sorted(PHRASES.items(), key=lambda x: len(x[0]), reverse=True)

# Pre-compile structural regex for performance
_STRUCTURAL_PATTERNS = [(re.escape(s["match"]), s["replace"]) for s in STRUCTURAL]


# ── Skip Detection ──────────────────────────────────────────────────────────

def _is_already_compressed(text: str) -> bool:
    """Check if text already appears AAAK-compressed.

    Heuristic: if text contains ``|`` and has ≤3 space-delimited words,
    it likely went through AAAK already.
    """
    if "|" not in text:
        return False
    # Count non-pipe tokens
    parts = [p for p in text.split("|") if p.strip()]
    words = text.replace("|", " ").split()
    return len(words) <= 5  # Slightly relaxed from 3 for partial compressions


# ── Pipeline Steps ──────────────────────────────────────────────────────────

def _apply_categories(text: str) -> str:
    """Replace CATEGORY: prefix with CATEGORY abbreviation + pipe.

    ``PREFERENCE: dark mode`` → ``PREF|dark mode``
    Only matches at start of text (or after newline).
    """
    for full, abbr in CATEGORIES.items():
        prefix = full + ": "
        if text.startswith(prefix):
            return abbr + "|" + text[len(prefix):]
        prefix_nl = "\n" + full + ": "
        if text.startswith(prefix_nl):
            return "\n" + abbr + "|" + text[len(prefix_nl):]
    return text


def _apply_phrases(text: str) -> str:
    """Greedy longest-match-first phrase substitution."""
    for phrase, replacement in _PHRASES_SORTED:
        if phrase in text:
            text = text.replace(phrase, replacement)
    return text


def _apply_structural(text: str) -> str:
    """Sequential structural replacements (conjunctions, prepositions, separator chars)."""
    for pattern, replacement in _STRUCTURAL_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text


def _compact_parens(text: str) -> str:
    """Remove spaces inside parentheses. ``( foo bar )`` → ``(foo bar)``"""
    text = re.sub(r'\(\s+', '(', text)
    text = re.sub(r'\s+\)', ')', text)
    return text


def _apply_trailing(text: str) -> str:
    """Replace terminal phrases with symbols."""
    for phrase, replacement in sorted(TRAILING.items(), key=lambda x: len(x[0]), reverse=True):
        if text.endswith(" " + phrase):
            text = text[:-(len(phrase) + 1)] + " " + replacement
        elif text.rstrip() == phrase:
            text = text.rstrip()[:-(len(phrase))] + replacement
    return text


# ── Public API ──────────────────────────────────────────────────────────────

def aaak_compress(text: str) -> str:
    """Compress text using the AAAK shorthand dialect.

    Applies the 5-step Mnemosyne AAAK pipeline:
    1. Category prefix abbreviations (PREFERENCE→PREF|)
    2. Phrase substitutions (User asked → ASK)
    3. Structural replacements ( and → +, for → →)
    4. Parentheses compaction ( ( x ) → (x) )
    5. Trailing compactions (working correctly → OK)

    Args:
        text: The raw text to compress.

    Returns:
        AAAK-compressed text. If the input already appears compressed
        (contains ``|`` with ≤5 words), it is returned unchanged.
    """
    if not text or _is_already_compressed(text):
        return text

    result = text
    result = _apply_categories(result)
    result = _apply_phrases(result)
    result = _apply_structural(result)
    result = _compact_parens(result)
    result = _apply_trailing(result)
    return result


def aaak_decompress(text: str) -> str:
    """Attempt to reverse AAAK compression using available reverse maps.

    Only category and phrase reversals are supported. Structural replacements
    (``+`` → `` and ``, ``→`` → `` for ``) are NOT reversed because they would
    corrupt legitimate uses of those symbols. Trailing compactions are NOT
    reversed for the same reason.

    This is intentionally partial — AAAK is designed for LLM-native
    comprehension, not programmatic round-tripping.

    Args:
        text: AAAK-compressed text.

    Returns:
        Partially decompressed text.
    """
    result = text
    for abbr, full in REV_CATEGORIES.items():
        prefix = abbr + "|"
        if result.startswith(prefix):
            result = full + ": " + result[len(prefix):]
            break
    for abbr, full in sorted(REV_PHRASES.items(), key=lambda x: len(x[0]), reverse=True):
        if abbr in result:
            result = result.replace(abbr, full)
    return result


def aaak_ratio(original: str) -> float:
    """Return the compression ratio (compressed_size / original_size).

    Values < 1.0 indicate compression. Values close to 1.0 mean the text
    was already compact or contained no compressible patterns.
    """
    if not original:
        return 1.0
    compressed = aaak_compress(original)
    return len(compressed) / len(original)
