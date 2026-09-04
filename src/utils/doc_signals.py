"""Auto-generate per-document keyword signals using TF-IDF.

Replaces the hardcoded _DOC_SIGNALS dict in search.py with dynamically
extracted keywords that work for any uploaded document.
"""

import re
from collections import Counter


def extract_doc_signals(
    chunks: list[dict],
    top_n: int = 15,
) -> tuple[dict[str, int], dict[str, int]]:
    """Extract top positive and negative keyword signals from document chunks.

    Uses a simple TF-IDF-like approach without requiring scikit-learn:
    - Positive signals: high-frequency terms in THIS document that are
      distinctive (not common stop words).
    - Negative signals: terms shared with other documents that could
      cause false routing matches.

    Args:
        chunks: List of chunk dicts with 'content' and 'metadata' keys.
        top_n: Number of positive signals to extract.

    Returns:
        Tuple of (positive_signals, negative_signals) dicts mapping
        keyword -> weight (2 for strong, 1 for weak).
    """
    # Combine all chunk text for this document
    all_text = " ".join(chunk["content"] for chunk in chunks)
    all_text_lower = all_text.lower()

    # Extract words (3+ chars, not pure numbers)
    words = re.findall(r'[a-zA-Z]{3,}', all_text_lower)

    # Stop words to exclude
    stop_words = {
        'the', 'and', 'for', 'that', 'this', 'with', 'from', 'are', 'was',
        'were', 'been', 'being', 'have', 'has', 'had', 'will', 'would',
        'could', 'should', 'may', 'might', 'can', 'shall', 'not', 'but',
        'what', 'when', 'where', 'who', 'how', 'why', 'which', 'their',
        'there', 'then', 'than', 'them', 'they', 'these', 'those', 'your',
        'you', 'our', 'its', 'our', 'any', 'all', 'each', 'every',
        'also', 'just', 'only', 'over', 'such', 'into', 'more', 'most',
        'other', 'some', 'very', 'well', 'back', 'much', 'about',
        'after', 'before', 'between', 'through', 'during', 'under',
        'above', 'below', 'same', 'here', 'does', 'done', 'made',
        'make', 'including', 'based', 'within', 'using', 'used',
        'used', 'must', 'per', 'via', 'etc', 'the', 'new', 'first',
        'last', 'next', 'both', 'few', 'own', 'same', 'too',
        'rather', 'quite', 'still', 'already', 'yet', 'ever',
        'while', 'although', 'though', 'because', 'since', 'unless',
        'until', 'whether', 'either', 'neither', 'however', 'therefore',
        'furthermore', 'moreover', 'otherwise', 'meanwhile', 'indeed',
        'otherwise', 'thus', 'hence', 'accordingly',
    }

    # Count word frequencies
    word_counts = Counter(w for w in words if w not in stop_words)

    # Score by frequency relative to document length
    doc_len = len(words) if words else 1
    scored_words = []
    for word, count in word_counts.most_common(200):
        # Frequency score (0-1 range normalized by doc length)
        freq = count / doc_len
        # Boost multi-word phrases found in text
        phrase_bonus = 1.0
        if f" {word} " in f" {all_text_lower} ":
            # Check if it appears as part of a longer phrase
            phrase_matches = len(re.findall(r'\b' + re.escape(word) + r'\b', all_text_lower))
            if phrase_matches > count * 1.5:
                phrase_bonus = 1.5

        score = freq * phrase_bonus
        scored_words.append((word, score, count))

    # Take top N as positive signals
    positive_signals: dict[str, int] = {}
    for word, score, count in scored_words[:top_n]:
        weight = 2 if count >= 3 or score > 0.01 else 1
        positive_signals[word] = weight

    # Also extract bigrams (two-word phrases) for better signals
    bigram_counts: Counter = Counter()
    for i in range(len(words) - 1):
        w1, w2 = words[i], words[i + 1]
        if w1 not in stop_words or w2 not in stop_words:
            if w1 not in stop_words and w2 not in stop_words:
                bigram_counts[f"{w1} {w2}"] += 1

    for bigram, count in bigram_counts.most_common(10):
        if count >= 2:
            positive_signals[bigram] = 2

    # Negative signals are intentionally empty: the old implementation emitted
    # only weight-0 stop words, which never affected detection. Keeping the
    # slot (and the merge logic in search.py) preserves the API shape in case
    # corpus-level negative signals are added later.
    negative_signals: dict[str, int] = {}

    return positive_signals, negative_signals


def detect_document_auto(
    query: str,
    doc_signals: dict[str, tuple[dict[str, int], dict[str, int]]],
    threshold: int = 2,
) -> str | None:
    """Detect which document a query is about using auto-generated signals.

    Args:
        query: User query.
        doc_signals: Mapping of filename -> (positive_signals, negative_signals).
        threshold: Minimum score to confidently detect a document.

    Returns:
        Filename if detected, None otherwise.
    """
    query_lower = query.lower()

    best_doc = None
    best_tuple = (0, 0, 0)

    for doc_name, (pos_signals, neg_signals) in doc_signals.items():
        total = 0
        hits = 0
        max_signal = 0

        for keyword, weight in pos_signals.items():
            if re.search(r'\b' + re.escape(keyword) + r'\b', query_lower):
                total += weight
                hits += 1
                max_signal = max(max_signal, weight)

        for keyword, weight in neg_signals.items():
            if weight > 0 and re.search(r'\b' + re.escape(keyword) + r'\b', query_lower):
                total -= weight

        if total <= 0:
            continue

        score_tuple = (total, hits, max_signal)
        if score_tuple > best_tuple:
            best_tuple = score_tuple
            best_doc = doc_name

    if best_tuple[0] >= threshold:
        return best_doc
    return None
