/// MIB (Mutual Information Binarization) binary vector encoding.
///
/// Converts float32/f64 embedding vectors into compact binary vectors
/// using median-based binarization. Each dimension is thresholded:
///   1 if value >= median, 0 if value < median
///
/// Binary vectors are packed into `u64` words — 64 dimensions per word.
/// Similarity is measured via **Hamming distance** (popcount of XOR).
///
/// This provides ~32x compression vs float32 embeddings with minimal
/// accuracy loss for nearest-neighbor search tasks.
// Number of dimensions packed per u64 word.
pub const BITS_PER_WORD: usize = 64;

/// Compute median of a slice of f64 values.
pub fn median(values: &[f64]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let mut sorted = values.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let n = sorted.len();
    if n.is_multiple_of(2) {
        (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0
    } else {
        sorted[n / 2]
    }
}

/// Binarize a flat f64 embedding vector into packed u64 words.
///
/// Each dimension becomes 1 bit (1 if >= threshold, 0 if < threshold).
/// Bits are packed MSB-first into u64 words.
///
/// Returns (binary_words, original_dimensionality, threshold_used).
pub fn binarize(embedding: &[f64]) -> (Vec<u64>, usize, f64) {
    if embedding.is_empty() {
        return (Vec::new(), 0, 0.0);
    }

    let dims = embedding.len();
    let med = median(embedding);
    let words_needed = dims.div_ceil(BITS_PER_WORD);

    let mut words = vec![0u64; words_needed];

    for (i, &val) in embedding.iter().enumerate() {
        if val >= med {
            let word_idx = i / BITS_PER_WORD;
            let bit_idx = i % BITS_PER_WORD;
            words[word_idx] |= 1u64 << (63 - bit_idx); // MSB first
        }
    }

    (words, dims, med)
}

/// Compute Hamming distance between two binary vectors.
/// Returns the raw bit count (number of differing bits).
pub fn hamming_distance(a: &[u64], b: &[u64]) -> u64 {
    let min_len = a.len().min(b.len());
    let mut dist = 0u64;
    for i in 0..min_len {
        dist += (a[i] ^ b[i]).count_ones() as u64;
    }
    // Count remaining bits (if lengths differ) as maximum distance
    if a.len() > b.len() {
        for val in a.iter().skip(min_len) {
            dist += val.count_ones() as u64;
        }
    } else if b.len() > a.len() {
        for val in b.iter().skip(min_len) {
            dist += val.count_ones() as u64;
        }
    }
    dist
}

/// Compute MIB similarity score [0.0, 1.0] from Hamming distance.
/// 1.0 = identical, 0.0 = completely different (all bits flipped).
pub fn mib_similarity(a: &[u64], b: &[u64], total_bits: usize) -> f64 {
    if total_bits == 0 {
        return 0.0;
    }
    let dist = hamming_distance(a, b);
    let max_dist = total_bits as u64;
    1.0 - (dist as f64 / max_dist as f64)
}

/// Parse a JSON array of f64 values and return the binary encoding.
pub fn binarize_json(embedding_json: &str) -> Result<(Vec<u64>, usize, f64), String> {
    let values: Vec<f64> = serde_json::from_str(embedding_json)
        .map_err(|e| format!("Failed to parse embedding JSON: {}", e))?;
    Ok(binarize(&values))
}

/// Serialize binary vector words as a comma-separated string.
pub fn words_to_string(words: &[u64]) -> String {
    words.iter()
        .map(|w| w.to_string())
        .collect::<Vec<_>>()
        .join(",")
}

/// Parse a comma-separated string back into binary vector words.
pub fn string_to_words(s: &str) -> Result<Vec<u64>, String> {
    if s.is_empty() {
        return Ok(Vec::new());
    }
    s.split(',')
        .map(|part| part.trim().parse::<u64>().map_err(|e| format!("Bad word: {}", e)))
        .collect()
}

/// Pre-compute binarized index for all embeddings in a workspace.
/// This would be called periodically to keep the MIB index fresh.
pub fn compute_mib_index(embeddings: &[&[f64]]) -> Vec<(Vec<u64>, f64)> {
    embeddings.iter().map(|e| {
        let (words, _dims, threshold) = binarize(e);
        (words, threshold)
    }).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_median_odd() {
        assert!((median(&[1.0, 3.0, 2.0]) - 2.0).abs() < 1e-10);
    }

    #[test]
    fn test_median_even() {
        assert!((median(&[1.0, 4.0, 2.0, 3.0]) - 2.5).abs() < 1e-10);
    }

    #[test]
    fn test_median_single() {
        assert!((median(&[42.0]) - 42.0).abs() < 1e-10);
    }

    #[test]
    fn test_median_empty() {
        assert!((median(&[]) - 0.0).abs() < 1e-10);
    }

    #[test]
    fn test_binarize_small() {
        // 3 dims: [0.1, 0.9, 0.5] — median = 0.5
        // Bits: 0 (0.1<0.5), 1 (0.9>=0.5), 1 (0.5>=0.5) → 0b0110...
        let (words, dims, thresh) = binarize(&[0.1, 0.9, 0.5]);
        assert_eq!(dims, 3);
        assert!((thresh - 0.5).abs() < 1e-10);
        // Only 1 word needed (3 bits in u64)
        assert_eq!(words.len(), 1);
        // Bit 0 (MSB): 0, Bit 1: 1, Bit 2: 1 → 0x6000_0000_0000_0000
        assert_eq!(words[0], 0x6000_0000_0000_0000);
    }

    #[test]
    fn test_binarize_all_above_median() {
        let (words, dims, _) = binarize(&[0.6, 0.7, 0.8, 0.9]);
        assert_eq!(dims, 4);
        // Median = 0.75, so 0.6 (0) and 0.7 (0) are below, 0.8 (1) and 0.9 (1) are above
        // Bits: 0, 0, 1, 1 → 0x3000_0000_0000_0000
        assert_eq!(words[0], 0x3000_0000_0000_0000);
    }

    #[test]
    fn test_binarize_empty() {
        let (words, dims, thresh) = binarize(&[]);
        assert_eq!(dims, 0);
        assert!((thresh - 0.0).abs() < 1e-10);
        assert!(words.is_empty());
    }

    #[test]
    fn test_hamming_distance_identical() {
        let a = vec![0xFFFF_0000_0000_FFFFu64, 0x1234_5678_9ABC_DEF0u64];
        let b = a.clone();
        assert_eq!(hamming_distance(&a, &b), 0);
    }

    #[test]
    fn test_hamming_distance_different() {
        let a = vec![0b1111u64];
        let b = vec![0b0000u64];
        assert_eq!(hamming_distance(&a, &b), 4);
    }

    #[test]
    fn test_hamming_distance_partial() {
        let a = vec![0b1010u64];
        let b = vec![0b1100u64];
        // XOR = 0b0110 → 2 bits differ
        assert_eq!(hamming_distance(&a, &b), 2);
    }

    #[test]
    fn test_hamming_distance_diff_lengths() {
        let a = vec![0b1111u64, 0b0000u64];
        let b = vec![0b0000u64];
        // First word: 4 bits differ. Second word (only in a): 0 bits count.
        assert_eq!(hamming_distance(&a, &b), 4);
    }

    #[test]
    fn test_mib_similarity_identical() {
        let a = vec![0xFFFFu64];
        let sim = mib_similarity(&a, &a, 16);
        assert!((sim - 1.0).abs() < 1e-10);
    }

    #[test]
    fn test_mib_similarity_completely_different() {
        let a = vec![0b0000u64];
        let b = vec![0b1111u64];
        let sim = mib_similarity(&a, &b, 4);
        assert!((sim - 0.0).abs() < 1e-10);
    }

    #[test]
    fn test_mib_similarity_half() {
        let a = vec![0b0011u64];
        let b = vec![0b0101u64];
        // XOR = 0b0110 → 2 bits differ out of 4 → similarity = 0.5
        let sim = mib_similarity(&a, &b, 4);
        assert!((sim - 0.5).abs() < 1e-10);
    }

    #[test]
    fn test_words_to_string_roundtrip() {
        let words = vec![0xDEAD_BEEF_CAFE_F00Du64, 0x1234_5678_9ABC_DEF0u64];
        let s = words_to_string(&words);
        let parsed = string_to_words(&s).unwrap();
        assert_eq!(words, parsed);
    }

    #[test]
    fn test_string_to_words_empty() {
        let parsed = string_to_words("").unwrap();
        assert!(parsed.is_empty());
    }

    #[test]
    fn test_string_to_words_invalid() {
        let result = string_to_words("abc,def");
        assert!(result.is_err());
    }

    #[test]
    fn test_binarize_large_vector() {
        // Test with >64 dimensions to verify multi-word packing
        let mut vals = Vec::new();
        for i in 0..100 {
            vals.push(i as f64 / 100.0);
        }
        let (words, dims, thresh) = binarize(&vals);
        assert_eq!(dims, 100);
        // 100 bits → 2 words (64 + 36)
        assert_eq!(words.len(), 2);
        // Median should be ~0.495
        assert!((thresh - 0.495).abs() < 1e-10);
        // First 64 bits: indices 0-49 (below median) = 0, indices 50-63 (above median) = 1
        // So ~14 ones in first word
        let ones_count = words[0].count_ones();
        assert!(ones_count >= 12 && ones_count <= 18, "got {} ones in first word", ones_count);
    }

    #[test]
    fn test_binarize_consistent() {
        // Same input always produces same output
        let input = vec![0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8];
        let (w1, _, _) = binarize(&input);
        let (w2, _, _) = binarize(&input);
        assert_eq!(w1, w2);
    }

    #[test]
    fn test_compute_mib_index() {
        let e1 = vec![0.1, 0.5, 0.9];
        let e2 = vec![0.9, 0.5, 0.1];
        let index = compute_mib_index(&[&e1, &e2]);
        assert_eq!(index.len(), 2);
        // Each entry should have binary words + threshold
        assert!(!index[0].0.is_empty());
        assert!(!index[1].0.is_empty());
        // Similarity should be higher for similar vectors
        let sim_same = mib_similarity(&index[0].0, &index[0].0, 3);
        let sim_diff = mib_similarity(&index[0].0, &index[1].0, 3);
        assert!(sim_same >= sim_diff);
    }
}
