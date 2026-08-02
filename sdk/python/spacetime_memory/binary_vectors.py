"""MIB Binary Vectors — Maximally Informative Binarization for embeddings.

Implements Mnemosyne's MIB (Moorcheh ITS, arXiv:2601.11557) sign-based
binarization: positive values → 1, negative/non-positive → 0. Packs 8 bits
per byte for 32× storage reduction vs float32.

Similarity is computed via Hamming distance (bitwise XOR + popcount), which
is deterministic, integer-only, and faster than cosine similarity for large
vector sets.

1024-dim bge-m3:  4096 bytes (float32) → 128 bytes (binary) = 32× compression

Usage::

    from spacetime_memory.binary_vectors import binarize, hamming_similarity

    emb = [0.12, -0.34, 0.56, ...]  # 1024-dim float32
    binary = binarize(emb)            # 128 bytes
    sim = hamming_similarity(binary, other_binary)  # 0.0–1.0
"""

from __future__ import annotations

from collections.abc import Sequence


def binarize(embedding: Sequence[float]) -> bytes:
    """Convert a float32 embedding vector to MIB binary format.

    Sign-based binarization: value > 0 → 1, value ≤ 0 → 0.
    Packs 8 bits into each byte.

    Args:
        embedding: Float32 embedding vector (e.g., 1024-dim).

    Returns:
        Packed binary vector as bytes (len(embedding) // 8 bytes).

    Raises:
        ValueError: If embedding length is not divisible by 8.
    """
    dim = len(embedding)
    if dim % 8 != 0:
        raise ValueError(f"Embedding dimension {dim} must be divisible by 8 for byte-packing")

    num_bytes = dim // 8
    result = bytearray(num_bytes)

    for byte_idx in range(num_bytes):
        byte_val = 0
        base = byte_idx * 8
        for bit in range(8):
            if embedding[base + bit] > 0.0:
                byte_val |= 1 << (7 - bit)  # MSB first
        result[byte_idx] = byte_val

    return bytes(result)


def debinarize(binary: bytes, dim: int | None = None) -> list[float]:
    """Convert MIB binary vector back to float32 approximation.

    Each bit becomes 1.0 (was positive) or -1.0 (was ≤0).
    This is a lossy reconstruction — the exact float values are gone,
    only the sign is preserved.

    Args:
        binary: Packed binary bytes.
        dim: Original embedding dimension (auto-detected from byte length).

    Returns:
        Approximate float32 vector (values are +1.0 or -1.0).
    """
    if dim is None:
        dim = len(binary) * 8
    result = [0.0] * dim

    for byte_idx, byte_val in enumerate(binary):
        base = byte_idx * 8
        for bit in range(8):
            idx = base + bit
            if idx >= dim:
                break
            result[idx] = 1.0 if (byte_val >> (7 - bit)) & 1 else -1.0

    return result


def unpack_bits(binary: bytes) -> list[int]:
    """Unpack binary vector into a list of 0/1 bits.

    Args:
        binary: Packed binary bytes.

    Returns:
        List of integers, each 0 or 1.
    """
    bits = []
    for byte_val in binary:
        for bit in range(8):
            bits.append((byte_val >> (7 - bit)) & 1)
    return bits


def hamming_distance(a: bytes, b: bytes) -> int:
    """Compute Hamming distance between two MIB binary vectors.

    Counts the number of differing bits via XOR + popcount.
    O(dim/8) time — about 40× faster than float32 cosine similarity.

    Args:
        a, b: Packed binary vectors of equal length.

    Returns:
        Number of differing bits (0 = identical, dim = completely dissimilar).
    """
    if len(a) != len(b):
        raise ValueError(f"Binary vectors must be equal length: {len(a)} vs {len(b)}")

    dist = 0
    for byte_a, byte_b in zip(a, b):
        dist += (byte_a ^ byte_b).bit_count()
    return dist


def hamming_similarity(a: bytes, b: bytes) -> float:
    """Compute Hamming similarity (0.0–1.0) between two binary vectors.

    similarity = 1 - (hamming_distance / total_bits)

    Returns:
        Float in [0.0, 1.0] where 1.0 = identical.
    """
    dim_bits = len(a) * 8
    if dim_bits == 0:
        return 0.0
    dist = hamming_distance(a, b)
    return 1.0 - (dist / dim_bits)


def storage_ratio(dim: int) -> float:
    """Return the compression ratio for a given embedding dimension.

    float32: dim × 4 bytes
    MIB:     dim ÷ 8 bytes

    Args:
        dim: Embedding dimension.

    Returns:
        Compressed size as fraction of original (e.g., 0.03125 = 32×).
    """
    return (dim / 8) / (dim * 4)


def bytes_needed(dim: int) -> int:
    """Return the number of bytes needed for an MIB binary vector.

    Args:
        dim: Embedding dimension (must be divisible by 8).

    Returns:
        Number of bytes = dim ÷ 8.
    """
    if dim % 8 != 0:
        raise ValueError(f"Dimension {dim} must be divisible by 8")
    return dim // 8


# ── Batch Operations ────────────────────────────────────────────────────────


def binarize_batch(embeddings: list[Sequence[float]]) -> list[bytes]:
    """Binarize multiple embeddings at once.

    Args:
        embeddings: List of float32 embedding vectors.

    Returns:
        List of packed binary vectors.
    """
    return [binarize(emb) for emb in embeddings]


def similarity_matrix(query: bytes, candidates: list[bytes]) -> list[float]:
    """Compute Hamming similarity between a query and multiple candidates.

    Args:
        query: Packed binary query vector.
        candidates: List of packed binary candidate vectors.

    Returns:
        List of similarity scores (0.0–1.0), one per candidate.
    """
    return [hamming_similarity(query, cand) for cand in candidates]


# ── Display ─────────────────────────────────────────────────────────────────


def format_binary(binary: bytes, max_hex: int = 16) -> str:
    """Format a binary vector as a hex string for display.

    Args:
        binary: Packed binary bytes.
        max_hex: Maximum hex characters to show.

    Returns:
        Hex representation (e.g., "a3f10c...", "128 bytes").
    """
    hex_str = binary.hex()
    if len(hex_str) > max_hex:
        hex_str = hex_str[:max_hex] + "..."
    return f"{len(binary)}B {hex_str}"
