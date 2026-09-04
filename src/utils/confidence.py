"""Real confidence scoring derived from pipeline signals.

Replaces the hardcoded 0.8 default in AgentResponse and DueDiligenceResult
with a score computed from four observable signals:

1. Rescue path — did verify or wide_search fire? (the initial answer was weak)
2. Citation count — how many sources back the answer?
3. Source diversity — single-doc answers are more focused than multi-doc
4. Pipeline depth — fewer nodes = cleaner path = higher confidence
"""

from __future__ import annotations

# Node names that indicate the rescue path fired
_RESCUE_NODES = frozenset({"verify", "wide_search"})

# Node names that count toward total LLM calls
_LLM_NODES = frozenset({"classify", "answer", "verify", "wide_search"})


def compute_confidence(
    trace: list[dict],
    citations: list[str],
    *,
    source_filter: str | None = None,
) -> float:
    """Compute a confidence score from pipeline execution signals.

    Args:
        trace: Per-node timing data from state['trace'].
        citations: Extracted [Source N: ...] citation strings.
        source_filter: If the query was scoped to a specific document.

    Returns:
        Float in [0.05, 1.0] representing answer confidence.
    """
    score = 1.0
    nodes = [entry["node"] for entry in trace]

    # --- Signal 1: Rescue path penalty ---
    # If verify fired, the initial answer was empty/not-found/uncited.
    # If wide_search fired, even the re-examination failed and we fell
    # back to a broad search across all collections.
    rescue_count = sum(1 for n in nodes if n in _RESCUE_NODES)
    score -= 0.15 * rescue_count

    # --- Signal 2: Citation evidence ---
    citation_count = len(citations)
    if citation_count == 0:
        score -= 0.20
    elif citation_count == 1:
        score -= 0.05
    elif citation_count >= 3:
        score += 0.05

    # --- Signal 3: Source diversity ---
    # Parse document names from citations. Mixed-document answers are
    # less focused than single-document answers.
    if citation_count >= 2:
        doc_names = set()
        for c in citations:
            # Citations look like "filename, page X, line Y"
            name = c.split(",")[0].strip().lower()
            doc_names.add(name)
        if len(doc_names) > 2:
            score -= 0.05

    # --- Signal 4: Pipeline depth ---
    # A clean path is classify→search→narrow→answer (4 nodes).
    # Each extra node beyond that adds uncertainty.
    llm_calls = sum(1 for n in nodes if n in _LLM_NODES)
    if llm_calls > 3:
        score -= 0.05 * (llm_calls - 3)

    # --- Signal 5: Document scoping bonus ---
    # If the query was scoped to a specific document (via keyword detection
    # or forced agent), the retrieval was more focused.
    if source_filter:
        score += 0.03

    # Clamp to [0.05, 1.0]
    return max(0.05, min(1.0, round(score, 2)))


def classify_routing_method(
    trace: list[dict],
    agent_type_forced: bool,
) -> str:
    """Determine how the agent type was selected.

    Returns one of: "forced", "keyword", "llm", or "unknown".
    """
    if agent_type_forced:
        return "forced"
    nodes = [entry["node"] for entry in trace]
    if "classify" not in nodes:
        return "forced"  # classify was skipped
    # If classify ran, we can't distinguish keyword vs LLM from timing alone
    # without the actual classification data. Return "auto" to indicate
    # the classifier ran but we don't know which path.
    return "auto"


def trace_summary(trace: list[dict]) -> dict:
    """Extract a human-readable summary from trace data.

    Returns a dict with:
        - path: list of node names in execution order
        - total_ms: total wall time
        - llm_calls: number of LLM-calling nodes that fired
        - rescue_fired: whether verify or wide_search ran
        - bottleneck: the slowest node name
    """
    nodes = [entry["node"] for entry in trace]
    total_ms = sum(entry["ms"] for entry in trace)
    llm_calls = sum(1 for n in nodes if n in _LLM_NODES)
    rescue_fired = bool(set(nodes) & _RESCUE_NODES)
    bottleneck = max(trace, key=lambda e: e["ms"])["node"] if trace else None

    return {
        "path": nodes,
        "total_ms": total_ms,
        "llm_calls": llm_calls,
        "rescue_fired": rescue_fired,
        "bottleneck": bottleneck,
    }
