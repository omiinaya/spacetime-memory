"""Tests for MIB binary vectors (binary_vectors.py)."""

import pytest
from spacetime_memory.binary_vectors import (
    binarize,
    debinarize,
    unpack_bits,
    hamming_distance,
    hamming_similarity,
    storage_ratio,
    bytes_needed,
    binarize_batch,
    similarity_matrix,
    format_binary,
)


# ── binarize ─────────────────────────────────────────────────────────────────


class TestBinarize:
    """binarize() — float32 → packed binary."""

    def test_positive_becomes_one(self):
        """All positive → all 1s, byte = 0xFF."""
        emb = [1.0] * 8
        result = binarize(emb)
        assert result == b"\xff"
        assert len(result) == 1

    def test_negative_becomes_zero(self):
        """All negative/zero → all 0s."""
        emb = [-0.1, 0.0, -1.0, 0.0, -0.5, 0.0, -2.0, -0.0]
        result = binarize(emb)
        assert result == b"\x00"

    def test_mixed_signs(self):
        """Mixed positive/negative produces correct bit pattern."""
        # + + - - + - + -  →  1 1 0 0 1 0 1 0  = 0xCA
        emb = [1.0, 0.5, -0.1, -1.0, 0.3, -2.0, 0.1, -0.0]
        result = binarize(emb)
        assert result == b"\xca"

    def test_multi_byte(self):
        """1024-dim bge-m3 sized vector."""
        emb = [0.12, -0.34] * 512  # 1024 dims
        result = binarize(emb)
        assert len(result) == 128  # 1024 / 8

    def test_dim_not_divisible_by_8_raises(self):
        """Non-multiple-of-8 dimensions raise ValueError."""
        with pytest.raises(ValueError, match="divisible by 8"):
            binarize([1.0] * 7)

    def test_single_byte_edge(self):
        """Exactly 8 dimensions — one byte."""
        emb = [0.1] * 8
        result = binarize(emb)
        assert len(result) == 1
        assert result == b"\xff"

    def test_empty_ok(self):
        """0-dim embedding produces empty bytes."""
        result = binarize([])
        assert result == b""


# ── debinarize ───────────────────────────────────────────────────────────────


class TestDebinarize:
    """debinarize() — packed binary → float32 approximation."""

    def test_roundtrip_signs(self):
        """Signs are preserved round-trip."""
        original = [1.0, -0.1, 3.0, -5.0, 0.5, -2.0, 0.1, -0.0]
        binary = binarize(original)
        restored = debinarize(binary)
        assert len(restored) == 8
        for orig, rest in zip(original, restored):
            assert (orig > 0) == (rest > 0)
            assert rest in (1.0, -1.0)

    def test_with_explicit_dim(self):
        """Explicit dim parameter is honoured."""
        binary = b"\xff\x00"  # 16 bits
        result = debinarize(binary, dim=12)
        assert len(result) == 12
        assert result[0] == 1.0   # 0xFF bit 7
        assert result[8] == -1.0  # 0x00 bit 7

    def test_zero_bits_become_negative_one(self):
        """Zero bits → -1.0 (was ≤ 0 in original)."""
        binary = b"\x00" * 2  # all zeros
        result = debinarize(binary)
        assert all(v == -1.0 for v in result)

    def test_one_bits_become_positive_one(self):
        """One bits → 1.0 (was > 0 in original)."""
        binary = b"\xff" * 2
        result = debinarize(binary)
        assert all(v == 1.0 for v in result)


# ── unpack_bits ──────────────────────────────────────────────────────────────


class TestUnpackBits:
    """unpack_bits() — binary → list of 0/1."""

    def test_unpack_byte(self):
        """0xCA = 11001010."""
        bits = unpack_bits(b"\xca")
        assert bits == [1, 1, 0, 0, 1, 0, 1, 0]

    def test_unpack_all_ones(self):
        bits = unpack_bits(b"\xff")
        assert bits == [1] * 8

    def test_unpack_all_zeros(self):
        bits = unpack_bits(b"\x00")
        assert bits == [0] * 8

    def test_unpack_empty(self):
        assert unpack_bits(b"") == []

    def test_unpack_multi_byte(self):
        bits = unpack_bits(b"\xf0\x0f")
        assert bits == [1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1]


# ── hamming_distance ─────────────────────────────────────────────────────────


class TestHammingDistance:
    """hamming_distance() — bitwise difference count."""

    def test_identical(self):
        assert hamming_distance(b"\xff", b"\xff") == 0

    def test_opposite(self):
        # 0xFF ^ 0x00 = 0xFF → 8 bits differ
        assert hamming_distance(b"\xff", b"\x00") == 8

    def test_one_bit_diff(self):
        # 0x01 (00000001) vs 0x00 (00000000) = 1 bit
        assert hamming_distance(b"\x01", b"\x00") == 1

    def test_multi_byte(self):
        a = binarize([0.1] * 16)   # all 1s
        b = binarize([-0.1] * 16)  # all 0s
        assert hamming_distance(a, b) == 16

    def test_unequal_length_raises(self):
        with pytest.raises(ValueError, match="equal length"):
            hamming_distance(b"\xff", b"\x00\x00")


# ── hamming_similarity ───────────────────────────────────────────────────────


class TestHammingSimilarity:
    """hamming_similarity() — 0.0–1.0 score."""

    def test_identical_is_one(self):
        assert hamming_similarity(b"\xff", b"\xff") == 1.0

    def test_opposite_is_zero(self):
        assert hamming_similarity(b"\xff", b"\x00") == 0.0

    def test_half_similar(self):
        # 0xF0 (11110000) vs 0x00 (00000000) → 4 bits differ out of 8
        sim = hamming_similarity(b"\xf0", b"\x00")
        assert sim == 0.5

    def test_empty_returns_zero(self):
        assert hamming_similarity(b"", b"") == 0.0

    def test_large_identical(self):
        a = b"\xff" * 100
        assert hamming_similarity(a, a) == 1.0


# ── storage_ratio ────────────────────────────────────────────────────────────


class TestStorageRatio:
    """storage_ratio() — compressed / original fraction."""

    def test_ratio_1024(self):
        # (1024/8) / (1024*4) = 128 / 4096 = 0.03125 = 32×
        assert storage_ratio(1024) == 0.03125

    def test_ratio_8(self):
        assert storage_ratio(8) == 1.0 / 32


# ── bytes_needed ─────────────────────────────────────────────────────────────


class TestBytesNeeded:
    """bytes_needed() — how many bytes for MIB format."""

    def test_1024_dim(self):
        assert bytes_needed(1024) == 128

    def test_8_dim(self):
        assert bytes_needed(8) == 1

    def test_not_divisible_raises(self):
        with pytest.raises(ValueError, match="divisible by 8"):
            bytes_needed(7)


# ── binarize_batch ───────────────────────────────────────────────────────────


class TestBinarizeBatch:
    """binarize_batch() — batch conversion."""

    def test_empty_batch(self):
        assert binarize_batch([]) == []

    def test_multiple(self):
        embs = [[1.0] * 8, [-1.0] * 8, [0.5, -0.5] * 4]
        results = binarize_batch(embs)
        assert len(results) == 3
        assert results[0] == b"\xff"
        assert results[1] == b"\x00"

    def test_single(self):
        results = binarize_batch([[0.1] * 8])
        assert len(results) == 1
        assert results[0] == b"\xff"


# ── similarity_matrix ────────────────────────────────────────────────────────


class TestSimilarityMatrix:
    """similarity_matrix() — query vs multiple candidates."""

    def test_empty_candidates(self):
        assert similarity_matrix(b"\xff", []) == []

    def test_matches(self):
        query = b"\xff"
        candidates = [b"\xff", b"\x00", b"\xf0"]
        scores = similarity_matrix(query, candidates)
        assert scores[0] == 1.0
        assert scores[1] == 0.0
        assert scores[2] == 0.5


# ── format_binary ────────────────────────────────────────────────────────────


class TestFormatBinary:
    """format_binary() — display helper."""

    def test_short_hex(self):
        result = format_binary(b"\xca\xfe")
        assert "2B" in result
        assert "cafe" in result

    def test_long_hex_truncated(self):
        big = b"\xff" * 20
        result = format_binary(big, max_hex=8)
        assert result.endswith("...")
        assert "20B" in result

    def test_max_hex_default(self):
        big = b"\x00" * 50
        result = format_binary(big)
        assert "50B" in result
