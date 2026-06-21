"""Pytest tests for spacetime_memory.binary_vectors — MIB binary vector operations."""

import os

import pytest
from spacetime_memory.binary_vectors import (
    binarize,
    binarize_batch,
    bytes_needed,
    debinarize,
    format_binary,
    hamming_distance,
    hamming_similarity,
    similarity_matrix,
    storage_ratio,
    unpack_bits,
)


# ── binarize tests ──────────────────────────────────────────────────────────

class TestBinarize:
    """Convert float32 embedding vectors to packed MIB binary format."""

    def test_all_positive(self):
        """All positive values → all bits set to 1."""
        emb = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        result = binarize(emb)
        assert result == b"\xff"

    def test_all_negative(self):
        """All negative values → all bits 0."""
        emb = [-0.1, -0.2, -0.3, -0.4, -0.5, -0.6, -0.7, -0.8]
        result = binarize(emb)
        assert result == b"\x00"

    def test_all_zero(self):
        """Zero values (≤ 0) → all bits 0."""
        emb = [0.0] * 8
        result = binarize(emb)
        assert result == b"\x00"

    def test_mixed_signs(self):
        """Alternating positive/negative → alternating 1/0 bits (MSB first)."""
        emb = [1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0]
        result = binarize(emb)
        # MSB first: 1,0,1,0,1,0,1,0 = 0b10101010 = 0xAA
        assert result == b"\xaa"

    def test_mixed_reversed(self):
        """Alternating negative/positive → 0/1 bits (MSB first)."""
        emb = [-1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0]
        result = binarize(emb)
        # MSB first: 0,1,0,1,0,1,0,1 = 0b01010101 = 0x55
        assert result == b"\x55"

    def test_very_small_positive(self):
        """Very small positive (e.g., 1e-10) is still > 0 → bit 1."""
        emb = [1e-10] + [0.0] * 7
        result = binarize(emb)
        assert result[0] >> 7 == 1  # first bit (MSB) is 1

    def test_very_small_negative(self):
        """Very small negative (e.g., -1e-10) is ≤ 0 → bit 0."""
        emb = [-1e-10] + [0.0] * 7
        result = binarize(emb)
        assert result[0] >> 7 == 0  # first bit (MSB) is 0

    def test_16_dim(self):
        """16-dimensional embedding → 2 bytes."""
        emb = [-1.0] * 8 + [1.0] * 8
        result = binarize(emb)
        assert len(result) == 2
        assert result == b"\x00\xff"

    def test_standard_1024_dim(self):
        """Standard bge-m3 1024-dim embedding → 128 bytes."""
        # Create a pattern: all even positions positive, odd negative
        emb = [1.0 if i % 2 == 0 else -1.0 for i in range(1024)]
        result = binarize(emb)
        assert len(result) == 128
        # Each byte should be 0xAA (10101010) since even=positive=1, odd=negative=0
        for byte in result:
            assert byte == 0xAA

    def test_dim_not_multiple_of_8(self):
        """Non-byte-aligned dimension raises ValueError."""
        with pytest.raises(ValueError, match="divisible by 8"):
            binarize([0.0] * 7)

        with pytest.raises(ValueError, match="divisible by 8"):
            binarize([0.0] * 9)

        with pytest.raises(ValueError, match="divisible by 8"):
            binarize([0.0] * 10)

    def test_empty_embedding(self):
        """0-dim embedding → 0 bytes (0 % 8 == 0)."""
        result = binarize([])
        assert result == b""
        assert len(result) == 0

    def test_integer_values(self):
        """Integer values work (Sequence[float] accepts ints)."""
        emb = [1, -2, 3, -4, 5, -6, 7, -8]
        result = binarize(emb)
        assert result == b"\xaa"  # alternating

    def test_bool_values(self):
        """Boolean values (True=1, False=0) work."""
        emb = [True, False, True, False, True, False, True, False]
        result = binarize(emb)
        assert result == b"\xaa"

    def test_multi_byte_packing(self):
        """Verify correct packing across multiple bytes with boundary test."""
        # 16-dim: first 8 all 1s, last 8: bits 1,0,1,0,1,0,1,0
        emb = [1.0] * 8 + [1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0]
        result = binarize(emb)
        assert result == b"\xff\xaa"


# ── debinarize tests ────────────────────────────────────────────────────────

class TestDebinarize:
    """Convert MIB binary vectors back to float32 approximations."""

    def test_all_ones_byte(self):
        """0xFF → all +1.0."""
        result = debinarize(b"\xff")
        assert result == [1.0] * 8

    def test_all_zeros_byte(self):
        """0x00 → all -1.0."""
        result = debinarize(b"\x00")
        assert result == [-1.0] * 8

    def test_alternating_byte(self):
        """0xAA → +1, -1 alternating."""
        result = debinarize(b"\xaa")
        assert result == [1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0]

    def test_two_bytes(self):
        """Two bytes → 16 values."""
        result = debinarize(b"\xff\x00")
        assert result == [1.0] * 8 + [-1.0] * 8

    def test_auto_dim(self):
        """dim=None auto-detects from byte length."""
        result = debinarize(b"\xff\xff\xff")
        assert len(result) == 24  # 3 * 8

    def test_explicit_dim_matching(self):
        """Explicit dim matching byte length."""
        result = debinarize(b"\xff", dim=8)
        assert len(result) == 8

    def test_explicit_dim_less_than_bits(self):
        """Explicit dim smaller than available bits → truncated."""
        result = debinarize(b"\xff", dim=4)
        assert len(result) == 4
        assert result == [1.0, 1.0, 1.0, 1.0]  # first 4 bits of 0xFF

    def test_explicit_dim_greater_than_bits(self):
        """Explicit dim larger than available bits → padded with 0.0."""
        result = debinarize(b"\xff", dim=10)
        assert len(result) == 10
        # First 8 are 1.0 (from 0xFF), last 2 are 0.0 (padding from init)
        assert result[:8] == [1.0] * 8
        assert result[8:] == [0.0, 0.0]

    def test_empty_bytes_auto_dim(self):
        """Empty bytes with auto dim → empty list."""
        result = debinarize(b"")
        assert result == []

    def test_empty_bytes_explicit_dim(self):
        """Empty bytes with explicit dim → padded zeros."""
        result = debinarize(b"", dim=5)
        assert result == [0.0] * 5

    def test_roundtrip_128_bytes(self):
        """Binarize then debinarize — signs preserved."""
        import random
        random.seed(42)
        original = [random.uniform(-1.0, 1.0) for _ in range(1024)]
        binary = binarize(original)
        recovered = debinarize(binary)
        assert len(recovered) == 1024
        # Sign must match: > 0 → 1.0, ≤ 0 → -1.0
        for orig, rec in zip(original, recovered):
            if orig > 0:
                assert rec == 1.0
            else:
                assert rec == -1.0

    def test_roundtrip_small(self):
        """Binarize then debinarize for 8-dim vector — sign preserved."""
        original = [0.5, -0.5, 0.0, 1e-9, -1e-9, 100.0, -100.0, 0.0]
        binary = binarize(original)
        recovered = debinarize(binary)
        expected_signs = [1.0 if v > 0 else -1.0 for v in original]
        assert recovered == expected_signs


# ── unpack_bits tests ───────────────────────────────────────────────────────

class TestUnpackBits:
    """Unpack binary vector into list of 0/1 bits."""

    def test_all_ones(self):
        """0xFF → eight 1s."""
        assert unpack_bits(b"\xff") == [1] * 8

    def test_all_zeros(self):
        """0x00 → eight 0s."""
        assert unpack_bits(b"\x00") == [0] * 8

    def test_alternating(self):
        """0xAA → 1,0,1,0,1,0,1,0 (MSB first)."""
        assert unpack_bits(b"\xaa") == [1, 0, 1, 0, 1, 0, 1, 0]

    def test_single_bit_set(self):
        """0x01 → MSB is bit 7, bit 0 is LSB: [0,0,0,0,0,0,0,1]."""
        assert unpack_bits(b"\x01") == [0, 0, 0, 0, 0, 0, 0, 1]

    def test_msb_set(self):
        """0x80 → [1, 0, 0, 0, 0, 0, 0, 0]."""
        assert unpack_bits(b"\x80") == [1, 0, 0, 0, 0, 0, 0, 0]

    def test_multiple_bytes(self):
        """Three bytes → 24 bits."""
        result = unpack_bits(b"\xff\x00\xaa")
        assert len(result) == 24
        assert result[:8] == [1] * 8
        assert result[8:16] == [0] * 8
        assert result[16:] == [1, 0, 1, 0, 1, 0, 1, 0]

    def test_empty_bytes(self):
        """Empty bytes → empty list."""
        assert unpack_bits(b"") == []

    def test_roundtrip_with_binarize(self):
        """binarize(...) then unpack_bits gives same signs as original (0/1)."""
        emb = [0.5, -0.5, 0.0, 1.0, -1.0, 0.1, -0.1, 3.14]
        binary = binarize(emb)
        bits = unpack_bits(binary)
        expected_bits = [1 if v > 0 else 0 for v in emb]
        assert bits == expected_bits


# ── hamming_distance tests ──────────────────────────────────────────────────

class TestHammingDistance:
    """XOR + popcount Hamming distance between equal-length binary vectors."""

    def test_identical_bytes(self):
        """Identical vectors → 0 differing bits."""
        assert hamming_distance(b"\xff\x00", b"\xff\x00") == 0

    def test_completely_different(self):
        """0xFF vs 0x00 → 8 differing bits per byte."""
        assert hamming_distance(b"\xff", b"\x00") == 8
        assert hamming_distance(b"\xff\xff", b"\x00\x00") == 16

    def test_one_bit_difference(self):
        """0x01 vs 0x00 → 1 differing bit."""
        assert hamming_distance(b"\x01", b"\x00") == 1

    def test_half_different(self):
        """0xFF vs 0xAA → 4 differing bits (half)."""
        assert hamming_distance(b"\xff", b"\xaa") == 4

    def test_empty_vectors(self):
        """Two empty byte strings → distance 0."""
        assert hamming_distance(b"", b"") == 0

    def test_single_byte_zero_diff(self):
        """Single byte, no difference."""
        assert hamming_distance(b"\x55", b"\x55") == 0

    def test_multi_byte_different(self):
        """Multi-byte vectors with mixed differences."""
        # 0xFF ^ 0x00 = 0xFF → popcount 8
        # 0x00 ^ 0xFF = 0xFF → popcount 8
        # 0xAA ^ 0x55 = 0xFF → popcount 8 (since 10101010 ^ 01010101 = 11111111)
        assert hamming_distance(b"\xff\x00\xaa", b"\x00\xff\x55") == 24

    def test_mismatched_lengths_raises(self):
        """Different-length binary vectors raise ValueError."""
        with pytest.raises(ValueError, match="equal length"):
            hamming_distance(b"\xff", b"\xff\x00")

        with pytest.raises(ValueError, match="equal length"):
            hamming_distance(b"\xff\x00", b"\xff")

        with pytest.raises(ValueError, match="equal length"):
            hamming_distance(b"", b"\x00")


# ── hamming_similarity tests ────────────────────────────────────────────────

class TestHammingSimilarity:
    """Normalized Hamming similarity (0.0–1.0)."""

    def test_identical(self):
        """Identical vectors → 1.0."""
        assert hamming_similarity(b"\xff\x00", b"\xff\x00") == 1.0

    def test_completely_different(self):
        """0xFF vs 0x00 → 0.0 (all bits differ)."""
        assert hamming_similarity(b"\xff", b"\x00") == 0.0

    def test_half_similar(self):
        """0xFF vs 0xAA → 0.5."""
        assert hamming_similarity(b"\xff", b"\xaa") == 0.5

    def test_one_bit_different_eight_bits(self):
        """1 differing bit out of 8 → 7/8 = 0.875."""
        assert hamming_similarity(b"\xfe", b"\xff") == 7.0 / 8.0

    def test_multi_byte(self):
        """0xFF\x00 vs 0xFF\xFF → 8 differences out of 16 → 0.5."""
        assert hamming_similarity(b"\xff\x00", b"\xff\xff") == 0.5

    def test_empty_vectors(self):
        """Empty bytes → 0.0 (special case, dim_bits==0)."""
        assert hamming_similarity(b"", b"") == 0.0

    def test_mismatched_lengths_raises(self):
        """Mismatched lengths propagate ValueError from hamming_distance."""
        with pytest.raises(ValueError, match="equal length"):
            hamming_similarity(b"\xff", b"\xff\x00")

    def test_exact_values(self):
        """Verify exact float values for known distances."""
        # 2 differing bits out of 8 → 6/8 = 0.75
        # 0b00000011 vs 0b00000000 → 2 bits differ
        assert hamming_similarity(b"\x03", b"\x00") == 6.0 / 8.0

    def test_range_zero_to_one(self):
        """All results should be in [0.0, 1.0]."""
        import random
        random.seed(99)
        for _ in range(50):
            a = bytes([random.randint(0, 255) for _ in range(8)])
            b = bytes([random.randint(0, 255) for _ in range(8)])
            sim = hamming_similarity(a, b)
            assert 0.0 <= sim <= 1.0


# ── storage_ratio tests ─────────────────────────────────────────────────────

class TestStorageRatio:
    """Compression ratio: MIB bytes / float32 bytes."""

    def test_standard_1024(self):
        """1024-dim: 128 bytes / 4096 bytes = 0.03125."""
        assert storage_ratio(1024) == 128.0 / 4096.0
        assert storage_ratio(1024) == 1.0 / 32.0

    def test_8_dim(self):
        """8-dim: 1 byte / 32 bytes = 1/32."""
        assert storage_ratio(8) == 1.0 / 32.0

    def test_16_dim(self):
        """16-dim: 2 bytes / 64 bytes = 1/32."""
        assert storage_ratio(16) == 2.0 / 64.0
        assert storage_ratio(16) == 1.0 / 32.0

    def test_always_1_over_32(self):
        """storage_ratio is always 1/32 independent of dim."""
        assert storage_ratio(1000) == pytest.approx(1.0 / 32.0)
        assert storage_ratio(8) == pytest.approx(1.0 / 32.0)
        assert storage_ratio(1024) == pytest.approx(1.0 / 32.0)
        assert storage_ratio(256) == pytest.approx(1.0 / 32.0)

    def test_one_dim(self):
        """1-dim: (1/8) / 4 = 0.03125."""
        assert storage_ratio(1) == pytest.approx(1.0 / 32.0)

    def test_zero_dim(self):
        """0-dim: would be 0/0 mathematically, but computed as (0/8)/(0*4) = 0/0."""
        # Python: 0.0 / 0.0 raises ZeroDivisionError
        with pytest.raises(ZeroDivisionError):
            storage_ratio(0)


# ── bytes_needed tests ──────────────────────────────────────────────────────

class TestBytesNeeded:
    """Compute bytes needed for MIB binary vector of given dimension."""

    def test_1024_dim(self):
        """1024 / 8 = 128."""
        assert bytes_needed(1024) == 128

    def test_8_dim(self):
        """8 / 8 = 1."""
        assert bytes_needed(8) == 1

    def test_16_dim(self):
        """16 / 8 = 2."""
        assert bytes_needed(16) == 2

    def test_0_dim(self):
        """0 / 8 = 0."""
        assert bytes_needed(0) == 0

    def test_256_dim(self):
        assert bytes_needed(256) == 32

    def test_not_divisible_by_8_raises(self):
        """Dimensions not divisible by 8 raise ValueError."""
        for dim in [1, 7, 9, 10, 15, 33, 1023, 1025]:
            with pytest.raises(ValueError, match="divisible by 8"):
                bytes_needed(dim)

    def test_negative_dim_raises(self):
        """Negative dimension: -8 % 8 == 0 in Python, so it does NOT raise.
        The function only checks divisibility by 8, not negativity."""
        # -8 // 8 = -1 in Python. The function returns -1.
        assert bytes_needed(-8) == -1

    def test_large_dim(self):
        """Large dimension."""
        assert bytes_needed(1048576) == 131072  # 1M / 8


# ── binarize_batch tests ────────────────────────────────────────────────────

class TestBinarizeBatch:
    """Batch conversion of multiple embeddings."""

    def test_empty_list(self):
        """Empty list → empty list."""
        assert binarize_batch([]) == []

    def test_single_embedding(self):
        """Single embedding → single binary result."""
        result = binarize_batch([[1.0] * 8])
        assert len(result) == 1
        assert result[0] == b"\xff"

    def test_multiple_embeddings(self):
        """Multiple embeddings — all correctly binarized."""
        embs = [
            [1.0] * 8,
            [-1.0] * 8,
            [1.0, -1.0] * 4,
        ]
        result = binarize_batch(embs)
        assert len(result) == 3
        assert result[0] == b"\xff"
        assert result[1] == b"\x00"
        assert result[2] == b"\xaa"

    def test_returns_bytes_objects(self):
        """All results should be bytes."""
        embs = [[0.5] * 8, [-0.3] * 8]
        result = binarize_batch(embs)
        assert all(isinstance(r, bytes) for r in result)

    def test_invalid_embedding_in_batch_raises(self):
        """A non-aligned embedding in batch propagates ValueError."""
        with pytest.raises(ValueError, match="divisible by 8"):
            binarize_batch([[1.0] * 8, [1.0] * 7])


# ── similarity_matrix tests ─────────────────────────────────────────────────

class TestSimilarityMatrix:
    """Batch Hamming similarity between query and candidates."""

    def test_empty_candidates(self):
        """Empty candidate list → empty list."""
        assert similarity_matrix(b"\xff", []) == []

    def test_single_candidate(self):
        """Single candidate → single similarity score."""
        result = similarity_matrix(b"\xff", [b"\xff"])
        assert result == [1.0]

    def test_multiple_candidates(self):
        """Multiple candidates → list of similarity scores."""
        query = b"\xff"  # all 1s
        candidates = [b"\xff", b"\x00", b"\xaa"]  # 1.0, 0.0, 0.5
        result = similarity_matrix(query, candidates)
        assert result == [1.0, 0.0, 0.5]

    def test_identity_vs_mixed(self):
        """Query identical to itself → 1.0; mixed scores for others."""
        query = b"\xff\x00"
        candidates = [b"\xff\x00", b"\x00\xff", b"\xff\xff"]
        result = similarity_matrix(query, candidates)
        assert result[0] == 1.0  # identical
        assert result[1] == 0.0  # completely different
        assert result[2] == 0.5  # half match

    def test_mismatched_candidate_raises(self):
        """A candidate with mismatched length raises ValueError."""
        with pytest.raises(ValueError, match="equal length"):
            similarity_matrix(b"\xff", [b"\xff\x00"])

    def test_all_scores_in_range(self):
        """All similarity scores should be in [0.0, 1.0]."""
        import random
        random.seed(7)
        query = bytes([random.randint(0, 255) for _ in range(16)])
        candidates = [
            bytes([random.randint(0, 255) for _ in range(16)])
            for _ in range(20)
        ]
        result = similarity_matrix(query, candidates)
        assert all(0.0 <= s <= 1.0 for s in result)


# ── format_binary tests ─────────────────────────────────────────────────────

class TestFormatBinary:
    """Hex display formatting for binary vectors."""

    def test_short_binary(self):
        """Short binary under max_hex → full hex display."""
        result = format_binary(b"\xff\xaa", max_hex=16)
        assert result == "2B ffaa"

    def test_long_binary_truncated(self):
        """Long binary over max_hex → truncated with '...'."""
        long_binary = bytes(range(256))
        result = format_binary(long_binary, max_hex=8)
        assert result == f"256B {long_binary.hex()[:8]}..."

    def test_default_max_hex(self):
        """Default max_hex=16. 20 hex chars → truncated."""
        binary = b"\x00" * 10  # 20 hex chars
        result = format_binary(binary)
        # 20 > 16, so truncated
        assert result == f"10B {binary.hex()[:16]}..."

    def test_exact_max_hex_boundary(self):
        """Exactly max_hex length → no truncation."""
        binary = b"\xab" * 4  # 8 hex chars
        result = format_binary(binary, max_hex=8)
        assert result == "4B abababab"

    def test_empty_binary(self):
        """Empty bytes."""
        result = format_binary(b"")
        assert result == "0B "

    def test_custom_max_hex_large(self):
        """Large max_hex shows everything."""
        binary = b"\xde\xad\xbe\xef"
        result = format_binary(binary, max_hex=100)
        assert result == "4B deadbeef"

    def test_max_hex_zero(self):
        """max_hex=0 → empty hex part with truncation marker."""
        binary = b"\xff\x00\xaa"
        result = format_binary(binary, max_hex=0)
        assert result == "3B ..."

    def test_format_includes_byte_count(self):
        """Format always starts with '{N}B '."""
        binary = os.urandom(32)
        result = format_binary(binary)
        assert result.startswith(f"{len(binary)}B ")

    def test_single_byte(self):
        """Single byte."""
        result = format_binary(b"\x3f")
        assert result == "1B 3f"


# ── Integration / cross-function tests ──────────────────────────────────────

class TestIntegration:
    """End-to-end workflows combining multiple binary_vectors functions."""

    def test_binarize_then_similarity(self):
        """Full workflow: embeddings → binarize → similarity."""
        emb1 = [0.1] * 1024
        emb2 = [-0.1] * 1024
        emb3 = [0.1 if i < 512 else -0.1 for i in range(1024)]

        b1 = binarize(emb1)
        b2 = binarize(emb2)
        b3 = binarize(emb3)

        # emb1 and emb2 are completely opposite
        assert hamming_similarity(b1, b2) == 0.0
        # emb1 and emb3 are half similar
        assert hamming_similarity(b1, b3) == 0.5
        # emb1 is identical to itself
        assert hamming_similarity(b1, b1) == 1.0

    def test_full_pipeline_8_dim(self):
        """Full pipeline on small vector: binarize → debinarize → unpack → compare."""
        original = [0.5, -0.3, 0.0, 1.0, -0.1, 2.0, -5.0, 0.001]
        binary = binarize(original)
        recovered = debinarize(binary)
        bits = unpack_bits(binary)

        assert len(binary) == 1  # 8 dim → 1 byte
        assert len(recovered) == 8
        assert len(bits) == 8

        # Signs match
        for i, v in enumerate(original):
            expected_sign = 1.0 if v > 0 else -1.0
            assert recovered[i] == expected_sign
            expected_bit = 1 if v > 0 else 0
            assert bits[i] == expected_bit

        # Hamming with itself is 0
        assert hamming_distance(binary, binary) == 0
        # Similarity with itself is 1.0
        assert hamming_similarity(binary, binary) == 1.0

    def test_batch_workflow(self):
        """Batch binarize then compute similarity matrix."""
        embs = [
            [1.0] * 16,
            [-1.0] * 16,
            [1.0, -1.0] * 8,
            [0.0] * 16,
        ]
        binaries = binarize_batch(embs)
        assert len(binaries) == 4

        query = binaries[0]  # all 1s
        sims = similarity_matrix(query, binaries)
        assert sims == [1.0, 0.0, 0.5, 0.0]

    def test_storage_and_bytes_consistency(self):
        """Storage ratio and bytes_needed are consistent."""
        for dim in [8, 16, 64, 128, 256, 512, 1024, 2048, 4096]:
            n_bytes = bytes_needed(dim)
            assert n_bytes == dim // 8
            ratio = storage_ratio(dim)
            assert ratio == pytest.approx(n_bytes / (dim * 4))

    def test_256_dim_random_roundtrip(self):
        """Random 256-dim vector roundtrips correctly."""
        import random
        random.seed(12345)
        emb = [random.uniform(-1.0, 1.0) for _ in range(256)]
        binary = binarize(emb)
        assert len(binary) == 32  # 256/8
        recovered = debinarize(binary)
        for orig, rec in zip(emb, recovered):
            assert rec == (1.0 if orig > 0 else -1.0)
