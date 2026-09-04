"""Pure-Python BM25 implementation for hybrid search.

No external dependencies. Implements the Okapi BM25 scoring function
with standard parameters (k1=1.5, b=0.75).
"""

from __future__ import annotations

import math
import re
from collections import Counter

# BM25 parameters
_K1 = 1.5
_B = 0.75

# Stop words to skip during tokenization
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "and", "but", "or", "if", "while", "this", "that", "these", "those",
    "it", "its", "what", "which", "who", "whom",
})


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words, removing stop words."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 1]


def bm25_search(
    query: str,
    corpus: list[dict],
    k: int = 10,
    k1: float = _K1,
    b: float = _B,
) -> list[dict]:
    """Search a corpus using BM25 scoring.

    Args:
        query: Search query string.
        corpus: List of dicts with 'content' key (and optional 'metadata').
        k: Number of results to return.
        k1: Term frequency saturation parameter.
        b: Length normalization parameter.

    Returns:
        Top-k results sorted by BM25 score (descending), each with
        'bm25_score' added to the dict.
    """
    if not corpus or not query.strip():
        return list(corpus[:k]) if corpus else []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return list(corpus[:k])

    # Build document frequency map
    n = len(corpus)
    doc_freq: dict[str, int] = {}
    doc_token_lists: list[list[str]] = []

    for doc in corpus:
        tokens = _tokenize(doc["content"])
        doc_token_lists.append(tokens)
        unique_tokens = set(tokens)
        for t in unique_tokens:
            doc_freq[t] = doc_freq.get(t, 0) + 1

    # Average document length
    avg_dl = sum(len(t) for t in doc_token_lists) / n if n > 0 else 1

    # Score each document
    scored: list[tuple[float, int]] = []
    for idx, tokens in enumerate(doc_token_lists):
        dl = len(tokens)
        tf_map = Counter(tokens)
        score = 0.0

        for qt in query_tokens:
            if qt not in doc_freq:
                continue
            tf = tf_map.get(qt, 0)
            df = doc_freq[qt]
            idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * dl / avg_dl)
            score += idf * numerator / denominator

        if score > 0:
            scored.append((score, idx))

    # Sort by score descending, return top-k with score added
    scored.sort(reverse=True)
    results = []
    for score, idx in scored[:k]:
        result = dict(corpus[idx])
        result["bm25_score"] = round(score, 4)
        results.append(result)

    return results
