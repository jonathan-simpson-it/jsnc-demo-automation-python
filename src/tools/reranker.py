"""Lightweight re-ranking for search results.

Uses keyword overlap scoring (no ML model needed) to re-rank
vector search results by term precision. This is a lightweight
alternative to cross-encoder models.
"""

from __future__ import annotations

import re
from collections import Counter


def _tokenize(text: str) -> Counter:
    """Tokenize text into a term frequency counter."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return Counter(w for w in words if len(w) > 1)


def rerank_results(
    query: str,
    results: list[dict],
    k: int = 5,
) -> list[dict]:
    """Re-rank search results by keyword precision.

    Scores each result by the fraction of query terms present in the content,
    weighted by TF-IDF-like term frequency. Higher score = better match.

    Args:
        query: Original search query.
        results: List of result dicts with 'content' and 'score' keys.
        k: Number of results to return.

    Returns:
        Top-k results re-sorted by rerank_score (descending).
    """
    if not results or not query.strip():
        return results[:k]

    query_tf = _tokenize(query)
    if not query_tf:
        return results[:k]

    query_terms = set(query_tf.keys())
    total_query_terms = len(query_terms)

    scored_results = []
    for result in results:
        content_tf = _tokenize(result["content"])
        # Count how many query terms appear in the content
        matching_terms = query_terms & set(content_tf.keys())
        # Precision: fraction of query terms found
        precision = len(matching_terms) / total_query_terms if total_query_terms > 0 else 0.0
        # Frequency boost: sum of TF for matching terms
        freq_boost = sum(content_tf[t] for t in matching_terms)
        # Combined score (precision is primary, freq is tiebreaker)
        rerank_score = precision + 0.01 * freq_boost

        entry = dict(result)
        entry["rerank_score"] = round(rerank_score, 4)
        scored_results.append(entry)

    scored_results.sort(key=lambda r: r["rerank_score"], reverse=True)
    return scored_results[:k]
