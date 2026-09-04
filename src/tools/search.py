"""LangChain tools for PE document search."""

import re

from langchain_core.tools import tool

from config.settings import settings
from src.vector_store.chroma import VectorStore

# Maximum distance threshold — results above this are too dissimilar
# ChromaDB uses L2 distance by default: 0 = identical, higher = less similar
# In-scope PE queries typically score 1.3-1.8, unrelated queries score 1.8+
MAX_DISTANCE = 2.0

# Auto-generated signals loaded from ChromaDB at runtime
_auto_signals_cache: dict[str, tuple[dict[str, int], dict[str, int]]] | None = None


def _extract_keywords(query: str) -> str:
    """Extract key terms from a natural language query for better search."""
    # Remove common stop words and question phrases
    stop_words = {
        'what', 'is', 'the', 'are', 'who', 'how', 'when', 'where', 'why',
        'does', 'do', 'can', 'could', 'would', 'should', 'will', 'of',
        'for', 'in', 'on', 'at', 'to', 'a', 'an', 'and', 'or', 'but',
        'not', 'no', 'with', 'from', 'by', 'about', 'this', 'that',
        'these', 'those', 'it', 'its', 'they', 'them', 'their', 'we',
        'our', 'you', 'your', 'i', 'my', 'me', 'he', 'she', 'him', 'her',
        'have', 'has', 'had', 'was', 'were', 'been', 'being', 'am',
        'company', 'acme', 'corp', 'limited',
    }
    words = re.findall(r'[a-zA-Z0-9%$]+', query)
    keywords = [w for w in words if w.lower() not in stop_words and len(w) > 1]
    return ' '.join(keywords)


# Field synonyms used to generate expanded query variants for better recall.
# Key: trigger word in the query. Value: extra terms appended to the variant.
_SYNONYM_EXPANSIONS = {
    # Contact info
    'email': ['contact', 'address'],
    'e-mail': ['contact', 'address'],
    'phone': ['number', 'contact', 'mobile'],
    'contact': ['email', 'phone', 'address'],
    'address': ['location'],
    # Time/date
    'deadline': ['date', 'milestone', 'timeline'],
    'milestone': ['deadline', 'date'],
    # Money
    'fee': ['cost', 'price', 'pricing'],
    'price': ['fee', 'cost'],
    'cost': ['fee', 'price'],
    'revenue': ['income', 'sales'],
    'income': ['revenue', 'earnings'],
    'margin': ['profit', 'earnings'],
    'profit': ['margin', 'earnings'],
    # Academic
    'gpa': ['grade', 'cgpa', 'academic'],
    'grade': ['score', 'mark'],
    'cgpa': ['gpa', 'grade', 'academic'],
    # Quantifiers
    'how many': ['count', 'number', 'total'],
    'how much': ['amount', 'number', 'total', 'value'],
    'name': ['person', 'title'],
    'instructor': ['teacher', 'professor', 'lecturer'],
    'professor': ['instructor', 'lecturer'],
    'course': ['module', 'class', 'programme'],
    'clinic': ['patients', 'practice'],
    'valuation': ['value', 'worth'],
    'revenue model': ['business', 'pricing'],
    'team': ['members', 'founders'],
    # Domain-specific
    'pii': ['encryption', 'data privacy', 'privacy'],
    'prototype': ['stage', 'roadmap'],
    'headquarter': ['principal offices'],
    'conference': ['analyst day'],
    'lecture': ['time', 'date', 'schedule'],
    'take place': ['time', 'date', 'venue', 'when'],
    'bi': ['tableau', 'looker studio', 'visualization', 'excel'],
}


def _expand_query_variant(query: str) -> str | None:
    """Generate a synonym-expanded variant of the query for better recall.

    Returns None if no expansion applies.

    Args:
        query: Original search query.

    Returns:
        Expanded query string, or None.
    """
    query_lower = query.lower()
    expansions: list[str] = []
    for trigger, terms in _SYNONYM_EXPANSIONS.items():
        if re.search(r'\b' + re.escape(trigger) + r'\b', query_lower):
            for term in terms:
                if term not in query_lower:
                    expansions.append(term)

    if not expansions:
        return None
    return f"{query} {' '.join(dict.fromkeys(expansions))}"


def _strip_years(query: str) -> str | None:
    """Generate a variant with years (2025, 2026…) removed.

    Document prose often references years differently from queries
    ("our 2025 Users Conference" vs "the 2025 Users Conference"), so dropping
    the year can dramatically improve retrieval recall in large documents.

    Returns None if the query contains no years.
    """
    stripped = re.sub(r'\b(?:19|20)\d{2}\b', '', query)
    stripped = re.sub(r'\s+', ' ', stripped).strip().strip('?')
    if not stripped or stripped == query.strip().strip('?'):
        return None
    return stripped


def _query_variants(query: str) -> list[str]:
    """All query variants to search, excluding duplicates of the original."""
    variants = []
    for candidate in (_expand_query_variant(query), _strip_years(query)):
        if candidate and candidate.strip() not in variants and candidate != query.strip():
            variants.append(candidate.strip())
    return variants


# Weighted keyword signals per document for routing queries to the right doc.
# Weights: 2 = strong signal, 1 = weak. Negative signals subtract weight so
# generic terms in a query do not hijack routing to the wrong document.
_DOC_SIGNALS: dict[str, tuple[dict[str, int], dict[str, int]]] = {
    'cv-jonathandevano-hkma.pdf': (
        {
            'candidate': 2, 'resume': 2, 'cv': 2, 'education': 1,
            'university': 1, 'degree': 1, 'phone': 1, 'email': 1,
            'address': 1, 'skills': 2, 'coursework': 2, 'award': 1,
            'bloomberg': 2, 'hitachi': 2, 'jonathan devano': 2, 'devoob': 2,
            'work experience': 1, 'placement': 1, 'intern': 1,
            'hku': 2, 'hkma': 2, 'gpa': 2, 'cgpa': 2, 'bachelor': 1,
            'undergraduate': 1, 'linkedin': 1, 'scholar': 1,
            'certification': 1, 'extracurricular': 1, 'leadership': 1,
            'workflow audits': 2, 'fine-tuning': 2, 'fine tuning': 2,
            'sentence': 2, 'embedding': 2, 'scholarship': 2,
            'informatics': 2, 'olympiad': 2, 'detection accuracy': 2,
            'technical': 1, 'bi': 2, 'visualization': 2, 'tableau': 2,
            'looker': 2, 'excel': 2, 'pivot': 1, 'database': 1,
        },
        {
            'annual report': 3, 'revenue': 3, 'eps': 3, 'shareholder': 3,
            'syllabus': 3, 'lecture': 3, 'enosis': 2, 'lifexp': 2,
            'dr yip': 2, 'stage': 2, 'roadmap': 2, 'prototype': 2,
            'pdf solutions': 3, 'semiconductor': 2, 'securewise': 2,
        },
    ),
    'dr_yip_draft.pdf': (
        {
            'dr yip': 2, 'yip': 2, 'aesthetic': 2, 'clinic': 1,
            'jonathan simpson': 2, 'digital transformation': 2,
            'patient intake': 2, 'discovery blindspot': 2,
            'omnichannel': 2, 'three-pillar': 2, 'phased rollout': 2,
            'clinical intelligence': 2, 'premium digital': 2,
            'lead strategist': 2, 'value proposition': 1,
            'contact email': 1, 'proposal create': 1,
            'package churn': 1, 'idle time': 1,
            'simpson': 2, 'proposal': 1, 'consultant': 1,
            'wellness': 1, 'medspa': 1, 'dermatology': 1, 'botox': 1,
            'injectable': 1, 'patient': 1, 'retention': 1,
            'marketing': 1, 'customer journey': 1,
            'prepared': 2, 'prepared by': 2, 'pillar 1': 2, 'pillar 2': 2,
            'pillar 3': 2, 'pii': 2, 'encryption': 2, 'privacy': 1,
            'calendar synchronization': 2, 'calendar': 1, 'blueprint': 2,
            'audit': 1, 'deliverable': 1,
        },
        {
            'syllabus': 3, 'jmsc': 3, 'lecture': 3, 'tutorial': 3,
            'moodle': 3, 'course': 2, 'semester': 2, 'assessment': 2,
            'assignment': 2, 'exam': 2, 'annual report': 2,
            'enosis': 2, 'revenue': 2, 'eps': 2, 'stage': 2,
            'roadmap': 2, 'prototype': 2,
        },
    ),
    'polyu-ifc-enosis.pdf': (
        {
            'enosis': 2, 'polyu ifc': 2, 'pitch deck': 1,
            'data translation': 2, 'clinical friction': 2,
            'eehealth': 2, 'compliance deadline': 2, 'mantra': 2,
            'tam': 1, 'sam': 1, 'som': 2, 'bento': 2,
            'zero-touch': 2, 'clinic integration': 2,
            'average contract value': 2, 'competitive advantage': 1,
            'markets beyond': 1, 'friction reduced': 1,
            'pitch': 1, 'startup': 1, 'healthtech': 1, 'market size': 1,
            'unit economics': 1, 'pipeline': 1, 'enterprise': 1,
            'investor': 1, 'solution': 1, 'acv': 1, 'founder': 2,
            'implementation time': 2, 'per clinic': 2,
            'year 3': 2, 'target revenue': 2,
            'annual recurring revenue': 2, 'team': 2,
            'lead ai architect': 2, 'regulatory counsel': 2,
            'alan lau': 2, 'tsang': 2, 'gba': 1,
        },
        {
            'syllabus': 3, 'lecture': 3, 'course': 2, 'annual report': 3,
            'eps': 3, 'dividend': 3, 'shareholder': 3, 'dr yip': 2,
            'stage': 2, 'roadmap': 2, 'prototype': 2, 'headquartered': 2,
        },
    ),
    'Syllabus_JMSC2043 Health Communication_Fall 2026.pdf': (
        {
            'syllabus': 2, 'jmsc2043': 2, 'health communication': 2,
            'instructor': 1, 'lecture': 1, 'tutorial': 1,
            'week 1': 2, 'week 2': 2, 'week 3': 2, 'week 7': 2,
            'reading week': 2, 'moodle': 2, 'eh102': 2,
            'attendance': 1, 'assessment': 1, 'quiz': 1,
            'venue': 2, 'junhan chen': 2, 'course venue': 2,
            'course': 1, 'credit': 2, 'unit': 1, 'semester': 1,
            'module': 1, 'assignment': 1, 'exam': 1, 'grading': 1,
            'participation': 1, 'fye': 1, 'faculty': 1, 'time': 1,
            'office': 2, 'eliot hall': 2, 'lecture time': 2, 'take place': 1,
            'date and time': 2, 'project proposal': 1,
            'peer evaluation': 2, 'written report': 2, 'report': 1,
            'written': 1,
        },
        {
            'annual report': 3, 'revenue': 3, 'eps': 3, 'shareholder': 3,
            'enosis': 2, 'dr yip': 2, 'lifexp': 2, 'cv': 2,
            'stage': 2, 'roadmap': 2, 'prototype': 2, 'headquartered': 2,
        },
    ),
    'FINAL Annual Report.pdf': (
        {
            'annual report': 2, 'pdf solutions': 2, 'semiconductor': 2,
            'securewise': 2, 'exensio': 2, 'shareholder': 2,
            'gaap': 2, 'backlog': 2, 'platform revenue': 2,
            'volume-based': 2, 'recurring revenue': 2,
            'non-gaap': 2, 'diluted eps': 2,
            'fiscal': 2, 'fye': 2, 'net income': 2, 'gross margin': 2,
            'operating income': 2, 'segment': 1, 'balance sheet': 2,
            'cash flow': 2, 'guidance': 2, 'eps': 2, 'revenue': 2,
            'financial results': 2, 'income statement': 2, 'diluted': 1,
            'headquarter': 2, 'headquartered': 2, 'santa clara': 2,
            'users conference': 2, 'analyst day': 2, 'conference': 1,
            'ticker': 2, 'nasdaq': 2, 'ceo': 2, 'par value': 2,
        },
        {
            'syllabus': 3, 'lecture': 3, 'jmsc': 3, 'cv': 2,
            'candidate': 2, 'enosis': 2, 'lifexp': 2, 'dr yip': 2,
            'stage': 2, 'roadmap': 2, 'prototype': 2, 'pillar': 2,
            'audit': 2,
        },
    ),
    'LifeXP PRD.pdf': (
        {
            'lifexp': 2, 'prd': 2, 'product requirements': 2,
            'feedback loops': 2, 'maintenance system': 2,
            'growth system': 2, 'milestones': 1, 'milestone': 1,
            'design principles': 2, 'no pressure': 2, 'no streaks': 2,
            'no guilt': 2, 'recording': 2, 'dashboard': 1,
            'ai responsibilities': 2, 'learning mode': 2,
            'app': 1, 'feature': 1, 'user': 1, 'habit': 1,
            'routine': 1, 'notification': 1, 'onboarding': 1,
            'subscription': 1, 'product': 1,
            'stage': 2, 'roadmap': 2, 'prototype': 2, 'mvp': 2,
            'monetisation': 2, 'monetization': 2, 'freemium': 2,
            'skills': 3, 'evidence': 2, 'accumulate': 2, 'xp': 2,
            'points': 2, 'never': 2, 'invent': 2, 'growth': 1,
            'active skills': 2, 'free tier': 2, 'free': 1, 'premium': 2,
            'systems': 1, 'two independent systems': 2, 'independent': 1,
        },
        {
            'annual report': 3, 'revenue': 3, 'eps': 3, 'shareholder': 3,
            'syllabus': 3, 'lecture': 3, 'enosis': 2, 'dr yip': 2, 'cv': 2,
        },
    ),
    'sample_investment_memo.md': (
        {
            'acme': 2, 'corp': 2, 'investment memo': 2, 'due diligence': 2,
            'ceo': 2, 'arr': 2, 'valuation': 2, 'series a': 2,
            'sarah chen': 2, 'employee': 1, 'employees': 1, 'headcount': 1, 'team size': 2,
            'risk': 1, 'revenue': 1, 'growth': 1, 'retention': 1,
            'fundraise': 1, 'capital': 1, 'portfolio': 1,
            'archbridge': 2, 'liquidation': 2, 'board': 1,
        },
        {
            'annual report': 3, 'syllabus': 3, 'enosis': 2, 'dr yip': 2,
            'cv': 2, 'lifexp': 2, 'pdf solutions': 3,
        },
    ),
    'sample_term_sheet.md': (
        {
            'term sheet': 2, 'acme': 2, 'liquidation preference': 3,
            'anti-dilution': 2, 'board seats': 2, 'pre-money': 2,
            'investment amount': 2, 'series a': 2,
            'protective provisions': 2, 'exclusivity': 2,
            'esop': 1, 'governing law': 1, 'dispute resolution': 1,
            'archbridge': 2, 'lead investor': 1,
        },
        {
            'annual report': 3, 'syllabus': 3, 'enosis': 2, 'dr yip': 2,
            'cv': 2, 'lifexp': 2, 'pdf solutions': 3,
        },
    ),
    'sample_financial_model.md': (
        {
            'financial model': 2, 'acme': 2, 'revenue projection': 2,
            'ebitda': 2, 'irr': 2, 'gross margin': 2, 'cac': 2,
            'ltv': 1, 'payback': 1, 'opex': 1, 'headcount': 1,
            'use of funds': 2, 'scenario': 1, 'bull': 1, 'bear': 1,
            'archbridge': 1, 'series a': 1,
        },
        {
            'annual report': 3, 'syllabus': 3, 'enosis': 2, 'dr yip': 2,
            'cv': 2, 'lifexp': 2, 'pdf solutions': 3,
        },
    ),
}


def _detect_document(
    query: str,
    vector_store: VectorStore,
    allowed_filenames: list[str] | None = None,
) -> str | None:
    """Detect which document the query is about based on keyword matching.

    Uses weighted positive signals and negative signals. Returns the filename
    if a specific document is confidently detected, None otherwise. When
    ``allowed_filenames`` is set, detection only ever picks documents inside
    that retrieval scope.

    Args:
        query: User query.
        vector_store: Vector store to list available documents.
        allowed_filenames: Optional filenames the scope permits.

    Returns:
        Filename if a specific document is detected, None otherwise.
    """
    documents = vector_store.list_documents()
    if not documents:
        return None

    allowed = set(allowed_filenames) if allowed_filenames is not None else None
    if allowed is not None:
        documents = [d for d in documents if d["filename"] in allowed]
        if not documents:
            return None

    query_lower = query.lower()

    # Merge hardcoded signals with auto-generated signals from ChromaDB.
    # Auto signals override hardcoded ones for the same document.
    auto_signals = _load_auto_signals(vector_store)
    all_signals: dict[str, tuple[dict[str, int], dict[str, int]]] = dict(_DOC_SIGNALS)
    for doc_name, (pos, neg) in auto_signals.items():
        if doc_name in all_signals:
            # Merge: auto signals add to / override hardcoded
            h_pos, h_neg = all_signals[doc_name]
            merged_pos = {**h_pos, **pos}
            merged_neg = {**h_neg, **neg}
            all_signals[doc_name] = (merged_pos, merged_neg)
        else:
            all_signals[doc_name] = (pos, neg)

    # Score each document: (total_score, max_signal, positive_hits)
    best_doc = None
    best_tuple = (0, 0, 0)
    for doc_name, (pos_signals, neg_signals) in all_signals.items():
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
        # Tie-break: strongest single signal first, then more distinct hits.
        # (Previously hits came first, letting two weak generic hits beat one
        # strong domain signal — e.g. memo's revenue+growth vs the annual
        # report's revenue on "year-over-year revenue growth".)
        score_tuple = (total, max_signal, hits)
        if score_tuple > best_tuple:
            best_tuple = score_tuple
            best_doc = doc_name

    # Return if confident match (score >= 2)
    if best_tuple[0] >= 2:
        return best_doc
    return None


def detect_document(query: str, vector_store: VectorStore) -> str | None:
    return _detect_document(query, vector_store)


def _load_auto_signals(vector_store: VectorStore) -> dict[str, tuple[dict[str, int], dict[str, int]]]:
    """Load auto-generated keyword signals from ChromaDB collection metadata.

    At ingest time, TF-IDF keywords are stored in each collection's metadata.
    This function reads them and returns a signals dict compatible with
    _DOC_SIGNALS. Results are cached; call invalidate_auto_signals_cache()
    after ingesting or deleting documents.
    """
    global _auto_signals_cache
    if _auto_signals_cache is not None:
        return _auto_signals_cache

    signals: dict[str, tuple[dict[str, int], dict[str, int]]] = {}
    try:
        collections = vector_store._chroma_client.list_collections()
        for col in collections:
            try:
                collection = vector_store._chroma_client.get_collection(col.name)
                # Get filename from metadata
                sample = collection.get(limit=1)
                if not sample or not sample["metadatas"]:
                    continue
                filename = sample["metadatas"][0].get("filename", col.name)

                # Get auto signals from collection metadata
                col_metadata = collection.metadata or {}
                pos_raw = col_metadata.get("auto_positive_signals", {})
                neg_raw = col_metadata.get("auto_negative_signals", {})

                if pos_raw:
                    # Parse from JSON string if needed
                    if isinstance(pos_raw, str):
                        import json
                        pos_raw = json.loads(pos_raw)
                    if isinstance(neg_raw, str):
                        import json
                        neg_raw = json.loads(neg_raw)

                    pos = {k: int(v) for k, v in pos_raw.items()}
                    neg = {k: int(v) for k, v in neg_raw.items()}
                    signals[filename] = (pos, neg)
            except Exception:
                continue
    except Exception:
        pass

    _auto_signals_cache = signals
    return signals


def invalidate_auto_signals_cache() -> None:
    """Drop the cached auto-signals so the next detection re-reads ChromaDB.

    Must be called after documents are ingested or deleted, otherwise new
    uploads stay invisible to document detection until the process restarts.
    """
    global _auto_signals_cache
    _auto_signals_cache = None


def _rewrite_query_llm(query: str) -> str:
    """Use LLM to rewrite a query for better retrieval.

    Extracts key entities and rephrases for vector similarity matching.
    Returns original query on any failure.
    """
    if not settings.enable_llm_rewrite:
        return query
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from src.agents.graph import _make_llm
        resp = _make_llm(temperature=0).invoke([
            SystemMessage(content=(
                "Rewrite this query to improve document retrieval. "
                "Extract key entities, expand abbreviations, and add synonyms. "
                "Return ONLY the rewritten query, no explanation."
            )),
            HumanMessage(content=query),
        ])
        rewritten = resp.content.strip()
        return rewritten if rewritten else query
    except Exception:
        return query


def _apply_recency(results: list[dict]) -> list[dict]:
    """Temporal recency weighting for regulatory results.

    Results carrying regulator metadata + an issuance_date get their score
    multiplied by a decay factor (>=0.5) based on document age, so recent
    circulars outrank stale ones at equal similarity. Non-regulatory results
    are untouched (factor 1.0).
    """
    import calendar
    from datetime import date, datetime

    months = {m: i for i, m in enumerate(calendar.month_abbr) if m}

    def parse_date(raw: str) -> date | None:
        raw = (raw or "").strip()
        for fmt in ("%Y-%m-%d", "%d %b %Y", "%b %d %Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        return None

    for r in results:
        meta = r.get("metadata") or {}
        if "regulator" not in meta:
            continue
        parsed = parse_date(meta.get("issuance_date") or "")
        if parsed is None:
            continue
        age_days = (date.today() - parsed).days
        decay = max(0.5, 1 - age_days / 3650)
        base = r.get("hybrid_score", 1.0 - (r["score"] / MAX_DISTANCE)) if MAX_DISTANCE > 0 else r.get("hybrid_score", 1.0)
        r["hybrid_score"] = base * decay
        r["_recency_decay"] = decay
    # Rank decayed results so recent circulars actually outrank stale ones.
    if any("_recency_decay" in r for r in results):
        results.sort(key=lambda r: r.get("hybrid_score", 0), reverse=True)
    return results


def create_search_tool(
    vector_store: VectorStore,
    allowed_filenames: list[str] | None = None,
):
    """Create a LangChain tool for searching PE documents.

    Args:
        vector_store: The vector store instance to search against.
        allowed_filenames: Optional retrieval scope. When set, only these
            documents may be retrieved (project isolation); when an empty
            list, the scope has no documents and the tool says so explicitly.

    Returns:
        LangChain tool for document search.
    """
    scope = set(allowed_filenames) if allowed_filenames is not None else None

    @tool
    def search_pe_documents(query: str) -> str:
        """Search the private equity knowledge base for relevant documents.

        Use this tool to find information from investment memos, term sheets,
        financial models, and portfolio reports. The search returns relevant
        document chunks that can answer questions about deals, valuations,
        financial metrics, and PE-specific topics.

        Only returns documents that are sufficiently similar to the query.
        If no documents match closely enough, returns a clear message.

        Args:
            query: The search query describing what information you need.

        Returns:
            Relevant document chunks as a formatted string, or a message
            indicating no relevant documents were found.
        """
        query = _rewrite_query_llm(query)
        variants = _query_variants(query)

        # A scope with no documents: say so honestly instead of hallucinating.
        if scope is not None and not scope:
            return (
                "No documents are assigned to the current project scope. "
                "Upload documents and assign them to this project (Documents page) "
                "before asking questions about it."
            )

        # Detect if query is about a specific document
        target_doc = _detect_document(query, vector_store, allowed_filenames)
        detected = target_doc is not None

        if target_doc:
            # Search only that document's collection — use higher k for small docs
            results = vector_store.search(query, k=20, source_filter=target_doc, filenames=scope)
            for variant in variants:
                variant_results = vector_store.search(
                    variant, k=20, source_filter=target_doc, filenames=scope
                )
                seen_contents = {r['content'][:100] for r in results}
                for vr in variant_results:
                    if vr['content'][:100] not in seen_contents:
                        results.append(vr)
                        seen_contents.add(vr['content'][:100])

            # If nothing relevant found in the detected doc, fall back to a
            # scope-wide search (never outside the scope)
            if not any(r['score'] <= MAX_DISTANCE for r in results):
                target_doc = None

        if not target_doc:
            # Search all collections (restricted to the scope when set)
            results = vector_store.search(query, k=10, filenames=scope)

            # Also search with extracted keywords for better coverage
            keywords = _extract_keywords(query)
            if keywords != query.strip():
                keyword_results = vector_store.search(keywords, k=10, filenames=scope)
                seen_contents = {r['content'][:100] for r in results}
                for kr in keyword_results:
                    if kr['content'][:100] not in seen_contents:
                        results.append(kr)
                        seen_contents.add(kr['content'][:100])

            # Also search the query variants (in parallel)
            if variants:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                seen_contents = {r['content'][:100] for r in results}
                with ThreadPoolExecutor(max_workers=min(len(variants), 4)) as pool:
                    futures = {
                        pool.submit(vector_store.search, v, 10, filenames=scope): v
                        for v in variants
                    }
                    for future in as_completed(futures):
                        for vr in future.result():
                            if vr['content'][:100] not in seen_contents:
                                results.append(vr)
                                seen_contents.add(vr['content'][:100])

        # Sort by score (lower = more similar) and take the top results.
        # Detected (single-document) searches get a higher cap so smaller docs
        # are fully represented in context.
        results.sort(key=lambda r: r['score'])
        # --- Hybrid BM25 scoring ---
        if settings.enable_bm25 and results:
            from src.tools.bm25 import bm25_search
            bm25_results = bm25_search(query, results, k=len(results))
            if bm25_results:
                max_bm25 = max(r["bm25_score"] for r in bm25_results) or 1.0
                for r in results:
                    bm25_match = next(
                        (b for b in bm25_results if b["content"][:80] == r["content"][:80]),
                        None,
                    )
                    bm25_norm = (bm25_match["bm25_score"] / max_bm25) if bm25_match else 0.0
                    vector_norm = 1.0 - (r["score"] / MAX_DISTANCE) if MAX_DISTANCE > 0 else 0.0
                    r["hybrid_score"] = 0.6 * vector_norm + 0.4 * bm25_norm
                results.sort(key=lambda r: r.get("hybrid_score", 0), reverse=True)

        # Temporal recency: recent regulatory circulars beat stale equals.
        _apply_recency(results)
        if any("_recency_decay" in r for r in results):
            results.sort(key=lambda r: r.get("hybrid_score", 0), reverse=True)

        results = results[:16 if detected else 10]

        # Filter out results that are too dissimilar
        relevant = [r for r in results if r['score'] <= MAX_DISTANCE]

        if not relevant:
            return (
                "No relevant documents found in the knowledge base for this query. "
                "The available documents cover: Acme Corp (investment memo, term sheet, "
                "financial model). If your question is about a different topic, I cannot "
                "answer it from the available data."
            )

        formatted_results = []
        for i, result in enumerate(relevant, 1):
            meta = result['metadata']
            filename = meta.get('filename', 'unknown')
            page = meta.get('page', 1)
            line = meta.get('line', 1)
            formatted_results.append(
                f"[Source {i}: {filename}, page {page}, line {line}]\n{result['content']}"
            )

        return "\n\n".join(formatted_results)

    return search_pe_documents
