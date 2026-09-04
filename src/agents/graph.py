"""LangGraph StateGraph for the PE AI agent pipeline."""

import operator
import re
import time
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_deepseek import ChatDeepSeek
from langgraph.graph import END, StateGraph

from config.settings import settings
from src.agents.prompts import (
    CROSS_DOC_SYSTEM,
    GROUNDING_RULES,
    SOURCE_SELECTION_PROMPT,
    VERIFICATION_PROMPT,
    build_compliance_prompt,
    build_cross_doc_prompt,
    build_lp_report_prompt,
    build_term_sheet_prompt,
    clean_citations,
    is_analysis_query,
    says_not_found,
)
from src.tools.search import create_search_tool
from src.utils.api_key import resolve_api_key
from src.utils.cost_tracker import cost_tracker
from src.utils.llm_cache import llm_cache
from src.vector_store.chroma import VectorStore


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
class AgentState(TypedDict):
    query: str
    agent_type: Literal["due_diligence", "term_sheet", "lp_report", "compliance", "cross_doc"]
    agent_type_forced: bool
    retrieved: str
    narrowed: str
    answer: str
    verified: bool
    citations: list[str]
    conversation_history: list[dict]
    # None = unrestricted retrieval; [] = project exists but has no documents;
    # otherwise the only filenames RAG may retrieve from (project isolation).
    allowed_filenames: list[str] | None
    vector_store: Any
    reviewed: bool
    review_pending: bool
    human_review_decision: str  # "approve" | "edit" | ""
    human_edited_answer: str
    # Reducer required: langgraph >= 1.x overwrites plain list fields per node
    trace: Annotated[list[dict], operator.add]


# ---------------------------------------------------------------------------
# Node tracing: records per-node wall time in execution order
# ---------------------------------------------------------------------------
def _traced(name: str):
    """Decorator that appends {node, ms} to state['trace'] after each node."""

    def deco(fn):
        def wrapper(state: AgentState) -> dict:
            start = time.monotonic()
            updates = fn(state)
            elapsed = round((time.monotonic() - start) * 1000)
            updates["trace"] = [{"node": name, "ms": elapsed}]
            return updates

        return wrapper

    return deco


def _get_store(state: AgentState) -> VectorStore:
    """Use the store injected by the caller, falling back to the default."""
    store = state.get("vector_store")
    return store or VectorStore()


# ---------------------------------------------------------------------------
# Agent system prompts
# ---------------------------------------------------------------------------
_SYSTEM_PROMPTS = {
    "due_diligence": "You are a PE due diligence analyst at Archbridge Capital Partners, Hong Kong SAR. Analyze investment opportunities. Search the knowledge base, identify risks and opportunities, provide a recommendation.",
    "term_sheet": "You are a term sheet analyst at Archbridge Capital Partners, Hong Kong SAR. Extract structured data from financing documents accurately.",
    "lp_report": "You are an LP reporting analyst at Archbridge Capital Partners, Hong Kong SAR. Generate quarterly reports from portfolio and financial data.",
    "compliance": "You are a compliance analyst at Archbridge Capital Partners, Hong Kong SAR. Check documents against SFC, AMLO, HKMA, and Companies Ordinance regulations.",
    "cross_doc": CROSS_DOC_SYSTEM,
}

# Prompt builders per agent type (None = built dynamically in answer_node)
_PROMPT_BUILDERS = {
    "due_diligence": None,
    "term_sheet": build_term_sheet_prompt,
    "lp_report": build_lp_report_prompt,
    "compliance": build_compliance_prompt,
    "cross_doc": build_cross_doc_prompt,
}


# ---------------------------------------------------------------------------
# Parsers (one per agent type)
# ---------------------------------------------------------------------------
def _parse_fields(text: str) -> dict[str, str]:
    """Parse KEY: VALUE lines from LLM output, skipping headers like 'ANSWER:'."""
    fields = {}
    skip_keys = {"answer", "evidence", "summary", "risks", "opportunities", "recommendation", "sources"}
    for line in text.strip().split("\n"):
        if ":" in line:
            key, value = line.lstrip("-•* ").split(":", 1)
            k = key.strip().lower()
            if k in skip_keys or not value.strip():
                continue
            fields[key.strip()] = value.strip()
    return fields


def _safe_float(val: str) -> float:
    """Extract first numeric value from a string."""
    cleaned = clean_citations(val)
    cleaned = re.sub(r"[$€£¥,\s]", "", cleaned)
    match = re.search(r"\d+\.?\d*", cleaned)
    return float(match.group()) if match else 0.0


def _semicolon_list(val: str) -> list[str]:
    """Split semicolon-separated list, filtering out 'not available'."""
    return [
        x.strip() for x in clean_citations(val).split(";")
        if x.strip() and x.strip().lower() not in ("not available", "not specified")
    ]


def _parse_due_diligence(text: str) -> dict:
    sections = {}
    current = None
    for line in text.strip().split("\n"):
        stripped = line.strip()
        clean = stripped.lstrip("-•* ").upper()
        for label in ("ANSWER:", "SUMMARY:", "RISKS:", "OPPORTUNITIES:", "RECOMMENDATION:"):
            if clean.startswith(label):
                current = label.rstrip(":").lower()
                sections[current] = stripped.split(":", 1)[1].strip()
                break
        else:
            # EVIDENCE is part of the answer but not a separate section
            if clean.startswith("EVIDENCE:"):
                current = None  # stop appending to answer
            elif current == "answer" and stripped:
                sections["answer"] = sections.get("answer", "") + " " + stripped
            elif current == "risks" and stripped.startswith("- "):
                sections.setdefault("risks_list", []).append(stripped[2:])
            elif current == "opportunities" and stripped.startswith("- "):
                sections.setdefault("opps_list", []).append(stripped[2:])

    answer = sections.get("answer", "")
    summary = clean_citations(answer or sections.get("summary", ""))
    if not summary:
        # Free-form answers (verify/wide_search rescue responses don't emit
        # section headers) — use the whole text instead of dropping it.
        summary = clean_citations(text)
    return {
        "summary": summary or "Analysis completed",
        "risks": [clean_citations(r) for r in sections.get("risks_list", [])],
        "opportunities": [clean_citations(o) for o in sections.get("opps_list", [])],
        "recommendation": clean_citations(sections.get("recommendation", "")) or "Further analysis needed",
    }


def _safe_str(f: dict, key: str, default: str) -> str:
    """Get a field, clean citations, fall back to default if empty."""
    val = clean_citations(f.get(key, ""))
    return val if val else default


def _parse_term_sheet(text: str) -> dict:
    f = _parse_fields(text)
    return {
        "company_name": _safe_str(f, "COMPANY_NAME", "Unknown"),
        "round_type": _safe_str(f, "ROUND_TYPE", "Unknown"),
        "pre_money_valuation": _safe_float(f.get("PRE_MONEY_VALUATION", "0")),
        "investment_amount": _safe_float(f.get("INVESTMENT_AMOUNT", "0")),
        "liquidation_preference": _safe_str(f, "LIQUIDATION_PREFERENCE", "Standard"),
        "anti_dilution": _safe_str(f, "ANTI_DILUTION", "Standard"),
        "board_seats": _safe_str(f, "BOARD_SEATS", "To be determined"),
        "price_per_share": _safe_str(f, "PRICE_PER_SHARE", "Not specified"),
        "shares_issued": _safe_str(f, "SHARES_ISSUED", "Not specified"),
        "esop_pool": _safe_str(f, "ESOP_POOL", "Not specified"),
        "esop_refresh": _safe_str(f, "ESOP_REFRESH", "Not specified"),
        "founder_ownership_post": _safe_str(f, "FOUNDER_OWNERSHIP_POST", "Not specified"),
        "lead_investor": _safe_str(f, "LEAD_INVESTOR", "Not specified"),
        "protective_provisions": _semicolon_list(f.get("PROTECTIVE_PROVISIONS", "")),
        "information_rights": _semicolon_list(f.get("INFORMATION_RIGHTS", "")),
        "exclusivity": _safe_str(f, "EXCLUSIVITY", "Not specified"),
        "governing_law": _safe_str(f, "GOVERNING_LAW", "Not specified"),
        "dispute_resolution": _safe_str(f, "DISPUTE_RESOLUTION", "Not specified"),
        "key_person_insurance": _safe_str(f, "KEY_PERSON_INSURANCE", "Not specified"),
    }


def _parse_lp_report(text: str) -> dict:
    f = _parse_fields(text)
    highlights = [clean_citations(h) for h in f.get("HIGHLIGHTS", "").split(";") if h.strip()]
    risks = [clean_citations(r) for r in f.get("RISK_FACTORS", "").split(";") if r.strip()]

    financial = {}
    for pair in f.get("FINANCIAL_SUMMARY", "").split(";"):
        pair = pair.strip()
        if ":" in pair:
            k, v = pair.split(":", 1)
            financial[k.strip().replace(" ", "_")] = v.strip()
        elif pair.split():
            parts = pair.split()
            if len(parts) >= 2:
                financial["_".join(parts[:-1])] = parts[-1]

    return {
        "quarter": clean_citations(f.get("QUARTER", "Unknown")),
        "portfolio_highlights": highlights,
        "financial_summary": {k: (v if not isinstance(v, str) else clean_citations(v)) for k, v in financial.items()},
        "risk_factors": risks,
    }


def _parse_compliance(text: str) -> dict:
    f = _parse_fields(text)
    compliant_str = f.get("COMPLIANT", "false").lower()
    return {
        "document_name": clean_citations(f.get("DOCUMENT_NAME", "Unknown Document")),
        "compliant": compliant_str in ("true", "yes", "compliant"),
        "issues": [clean_citations(i) for i in f.get("ISSUES", "").split(";") if i.strip() and i.strip().lower() != "none"],
        "jurisdiction": clean_citations(f.get("JURISDICTION", "Hong Kong SAR")),
        "regulations_checked": [clean_citations(r) for r in f.get("REGULATIONS_CHECKED", "").split(";") if r.strip()],
    }


def _parse_cross_doc(text: str) -> dict:
    """Parse cross-document comparison output.

    The LLM is instructed to output SYNTHESIS, DIFFERENCES, SIMILARITIES,
    and DOCUMENTS sections. Falls back to using the full text as synthesis
    if parsing fails.
    """
    sections = {}
    current = None
    for line in text.strip().split("\n"):
        stripped = line.strip()
        clean = stripped.lstrip("-•* ").upper()
        for label in ("SYNTHESIS:", "DIFFERENCES:", "SIMILARITIES:", "DOCUMENTS:"):
            if clean.startswith(label):
                current = label.rstrip(":").lower()
                sections[current] = stripped.split(":", 1)[1].strip()
                break
        else:
            if current and stripped.startswith("- "):
                sections.setdefault(f"{current}_list", []).append(
                    stripped[2:]
                )
            elif current and stripped:
                sections[current] = (
                    sections.get(current, "") + " " + stripped
                )

    synthesis = clean_citations(
        sections.get("synthesis", "")
    ) or clean_citations(text)
    diffs = [
        clean_citations(d)
        for d in sections.get("differences_list", [])
    ]
    sims = [
        clean_citations(s)
        for s in sections.get("similarities_list", [])
    ]
    docs = [
        clean_citations(d)
        for d in sections.get("documents", "").split(";")
        if d.strip()
    ]
    return {
        "query": "",
        "synthesis": synthesis or "Comparison completed",
        "documents_compared": docs,
        "key_differences": diffs,
        "key_similarities": sims,
    }


PARSERS = {
    "due_diligence": _parse_due_diligence,
    "term_sheet": _parse_term_sheet,
    "lp_report": _parse_lp_report,
    "compliance": _parse_compliance,
    "cross_doc": _parse_cross_doc,
}

# Structured agent types whose parsed result has no natural prose channel for
# "nothing was found" — they get an explicit no-data result instead of a
# skeleton of Unknown/0/default fillers when the retrieval scope is empty.
# due_diligence is excluded: its free-text answer already says
# "Insufficient data" clearly on its own.
_STRUCTURED_NO_DATA_TYPES = ("term_sheet", "lp_report", "compliance", "cross_doc")

# search tool's exact no-content messages (see src/tools/search.py).
_NO_DATA_PREFIXES = ("No documents are assigned", "No relevant documents found")


def scope_lacks_data(text: str) -> bool:
    """True when a retrieval result carries no usable document content.

    Covers an empty scope (project with zero documents), a scope whose
    documents don't match the query, and empty text.
    """
    if not text or not text.strip():
        return True
    return text.strip().startswith(_NO_DATA_PREFIXES)


def empty_scope_result(agent_type: str) -> dict:
    """Explicit no-data result for a structured agent in an empty scope.

    Renders as a single clear message (StructuredOutput shows the top-level
    keys) instead of skeleton fields like "Unknown"/0 that read as if data
    existed. Documents are isolated per project, so the honest signal is that
    the current workspace does not contain what the query asked for.
    """
    what = {
        "term_sheet": "No term sheet data found in this project's workspace",
        "lp_report": "No portfolio or fund data found in this project's workspace",
        "compliance": "No documents to check found in this project's workspace",
        "cross_doc": "No documents to compare found in this project's workspace",
    }.get(agent_type, "No data found in this project's workspace")
    return {
        "message": (
            f"{what} — no document in the current project matched the query. "
            "Documents are isolated per project, so this data may live in a "
            "different project or workspace. Upload the relevant documents and "
            "assign them to this project (Documents page), or switch workspaces "
            "before asking again."
        )
    }


# Explicit financing-round mentions in a query ("Series B", "Seed", …).
# Used to flag when a question asks about one round but the extracted terms
# are for a different one, instead of silently presenting the closest match.
_ASKED_ROUND_RE = re.compile(
    r"\b(pre[- ]?seed|seed|angel|bridge|convertible|series\s*[a-zA-Z0-9]+)\b",
    re.IGNORECASE,
)


def _normalize_round(text: str) -> str:
    return re.sub(r"\s+", "", text).strip().lower()


def annotate_round_mismatch(query: str, data: dict) -> dict:
    """Flag when a term-sheet query names a round the extracted data is not for.

    Example: the user asks about the "Acme Series B term sheet" but the
    retrieved (in-scope) document is a Series A term sheet. Rather than
    serving the Series A values as the answer, the result gets a leading
    ``notice`` that says so explicitly.

    Returns the original dict unchanged when there is nothing to flag (no
    round mentioned in the query, no extracted round, or they match).
    """
    if not query or not isinstance(data, dict) or "round_type" not in data:
        return data
    asked = _ASKED_ROUND_RE.search(query)
    if not asked:
        return data
    asked_round = _normalize_round(asked.group(0))
    got_raw = str(data.get("round_type") or "")
    got_round = _normalize_round(got_raw)
    if not got_round or got_round in ("unknown", "notavailable", "na", "n/a"):
        return data
    # Skip when they match or when the extracted round already names the
    # asked one (e.g. the model wrote "Series A (not Series B)" itself).
    if (
        asked_round == got_round
        or asked_round in got_round
        or got_round in asked_round
    ):
        return data
    asked_label = asked.group(0)
    note = (
        f"The query asks about a {asked_label} round, but the extracted terms "
        f"are for {got_raw} — no {asked_label} term sheet appears among the "
        "retrieved documents. The values above are the closest in-scope match."
    )
    return {"notice": note, **dict(data)}


# ---------------------------------------------------------------------------
# Keyword classification (fast path before LLM)
# ---------------------------------------------------------------------------
_KW_MAP = {
    "cross_doc": [
        "compare", "comparison", "difference between",
        "differences between", "versus", " vs ",
        "across documents", "across all", "across the",
        "how do", "relative to", "against each other",
    ],
    "term_sheet": ["liquidation preference", "anti-dilution", "board seats",
                    "protective provisions", "exclusivity", "esop", "price per share",
                    "governing law", "dispute resolution", "key person insurance"],
    "compliance": ["sfc", "amlo", "hkma", "regulatory compliance check",
                    "compliance check", "anti-money laundering", "companies ordinance"],
    "lp_report": ["lp report", "quarterly report", "portfolio update",
                   "fund performance", "limited partner"],
}


def _classify_keyword(query: str) -> str | None:
    q = query.lower()
    for agent_type, keywords in _KW_MAP.items():
        if any(kw in q for kw in keywords):
            return agent_type
    return None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _make_llm(temperature: float = 0) -> ChatDeepSeek:
    return ChatDeepSeek(model=settings.deepseek_model, temperature=temperature, api_key=resolve_api_key())


def _format_history(history: list[dict], limit: int = 6) -> str:
    """Format recent conversation history for prompt injection."""
    lines = []
    for msg in history[-limit:]:
        role = "User" if msg.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {msg.get('content', '')}")
    return "\n".join(lines)


def _has_content(text: str) -> bool:
    """True when the response carries real content beyond citation tags.

    The model occasionally returns a bare "[Source N: ...]" line with no
    answer text; such responses must be treated as failures, not answers.
    """
    if not text or not text.strip():
        return False
    return bool(clean_citations(text).strip())


def _answer_ok(text: str) -> bool:
    """An answer is usable when it has substantive content and does not
    state the information was not found."""
    return _has_content(text) and not says_not_found(text)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (chars / 4) for cost accounting without provider usage."""
    return max(1, len(text) // 4)


def _invoke_text(llm, messages, retries: int = 2, node: str = "unknown") -> str:
    """Invoke the LLM, retrying when the response is empty or citation-only."""
    last = ""
    for _ in range(retries):
        resp = llm.invoke(messages)
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        last = text
        if _has_content(text):
            input_chars = sum(len(str(m.content or "")) for m in messages)
            cost_tracker.record_call(
                node,
                max(1, input_chars // 4),
                max(1, len(text) // 4),
            )
            return text
    return last


def _extract_citations(text: str) -> list[str]:
    return re.findall(r"\[Source[s]?[\s\d]*:\s*([^\]]+)\]", text)


_STOP_WORDS = frozenset({
    "what", "is", "the", "are", "who", "how", "when", "where", "why",
    "does", "do", "can", "could", "would", "should", "will", "of",
    "for", "in", "on", "at", "to", "a", "an", "and", "or", "but",
    "not", "no", "with", "from", "by", "about", "this", "that",
})


def _filter_sources(retrieved: str, selected: list[int], sources: list[tuple[int, str]]) -> str:
    kept = [text for index, text in sources if index in selected]
    return "\n\n".join(kept) if kept else retrieved


def _select_sources_llm(query: str, sources: list[tuple[int, str]]) -> list[int]:
    if not sources:
        return []
    abbreviated = [
        f"[Source {idx}:]{text[text.find(chr(10)):][:500] if chr(10) in text else text[:500]}"
        for idx, text in sources
    ]
    try:
        prompt_text = SOURCE_SELECTION_PROMPT.format(
            query=query, sources="\n\n".join(abbreviated)
        )
        raw = _make_llm().invoke([HumanMessage(content=prompt_text)]).content.strip().upper()
        cost_tracker.record_call(
            "narrow",
            _estimate_tokens(prompt_text),
            _estimate_tokens(str(raw)),
        )
    except Exception:
        return [idx for idx, _ in sources]

    if "ALL" in raw:
        return [idx for idx, _ in sources]
    valid = {idx for idx, _ in sources}
    selected = list(dict.fromkeys(int(n) for n in re.findall(r"\d+", raw) if int(n) in valid))[:3]
    return selected or [idx for idx, _ in sources]


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------
@_traced("classify")
def classify_node(state: AgentState) -> dict:
    query = state["query"]
    cached = llm_cache.get(query, prefix="classify")
    if cached:
        return {"agent_type": cached}

    kw = _classify_keyword(query)
    if kw:
        llm_cache.set(query, kw, prefix="classify")
        return {"agent_type": kw}

    # LLM fallback (with conversation context for ambiguous follow-ups).
    # Framed as "specialized or none?" so due_diligence is the robust default:
    # a 4-way pick invites the model to invent a specialized label for any
    # regulatory-sounding content question.
    prompt = """Is the user's question about one of these specialized tasks?
- cross_doc: comparing or contrasting information ACROSS multiple documents ("compare", "difference between", "how do X and Y differ", "versus", "across all documents")
- term_sheet: extracting term-sheet fields from a financing document (valuation, liquidation preference, anti-dilution, board seats, ESOP, protective provisions, exclusivity, governing law)
- lp_report: quarterly fund/portfolio reporting to limited partners (fund performance, portfolio update, LP report)
- compliance: explicitly asking to check a document against regulations ("is it compliant", "compliance check", SFC, AMLO, HKMA, Companies Ordinance, KYC, AML)

Factual or analytical questions about a SINGLE document are NOT specialized — answer "none".
Respond with ONLY one word: cross_doc, term_sheet, lp_report, compliance, or none."""
    history = state.get("conversation_history") or []
    messages: list = [SystemMessage(content=prompt)]
    if history:
        history_text = (
            "Recent conversation (for context only):\n"
            f"{_format_history(history)}\n\n"
        )
        messages.append(HumanMessage(content=history_text))
    messages.append(HumanMessage(content=query))
    try:
        cls = _invoke_text(_make_llm(), messages, node="classify").strip().lower()
        for valid in ("cross_doc", "term_sheet", "lp_report", "compliance"):
            if valid in cls:
                llm_cache.set(query, valid, prefix="classify")
                return {"agent_type": valid}
    except Exception:
        pass

    llm_cache.set(query, "due_diligence", prefix="classify")
    return {"agent_type": "due_diligence"}


@_traced("search")
def search_node(state: AgentState) -> dict:
    query = state["query"]
    allowed = state.get("allowed_filenames")
    scope_tag = "*" if allowed is None else "|".join(sorted(allowed))
    cache_prefix = f"{state['agent_type']}|{scope_tag}"
    cached = llm_cache.get(query, prefix=cache_prefix)
    if cached:
        return {"retrieved": cached}

    vs = _get_store(state)
    retrieved = create_search_tool(vs, allowed_filenames=allowed).invoke(query)
    llm_cache.set(query, retrieved, prefix=cache_prefix)
    return {"retrieved": retrieved}


@_traced("narrow")
def narrow_node(state: AgentState) -> dict:
    retrieved = state["retrieved"]
    if (
        not retrieved
        or retrieved.startswith("No relevant documents")
        or retrieved.startswith("No documents are assigned")
    ):
        return {"narrowed": retrieved}

    matches = list(re.finditer(r"\[Source (\d+):[^\]]*\]", retrieved))
    if len(matches) <= 4:
        return {"narrowed": retrieved}

    sources = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(retrieved)
        sources.append((int(m.group(1)), retrieved[m.start():end].strip()))

    # Check if mostly single-doc
    names = [re.sub(r"^\[Source \d+: ", "", t.split("\n", 1)[0]).rsplit(", page", 1)[0].strip() for _, t in sources]
    dominant = max(set(names), key=names.count)
    if names.count(dominant) >= 0.7 * len(names):
        return {"narrowed": _filter_sources(retrieved, [i for i, _ in sources[:16]], sources)}

    selected = _select_sources_llm(state["query"], sources)
    return {"narrowed": _filter_sources(retrieved, selected, sources) if selected and len(selected) < len(sources) else retrieved}


@_traced("answer")
def answer_node(state: AgentState) -> dict:
    agent_type = state["agent_type"]
    config_prompt = _PROMPT_BUILDERS[agent_type]

    history_block = ""
    if state.get("conversation_history"):
        history_block = (
            "\n\n## Conversation History:\n"
            f"{_format_history(state['conversation_history'])}"
        )

    if agent_type == "due_diligence":
        mode = "analysis" if is_analysis_query(state["query"]) else "factual"
        answer_prompt = (
            f"Answer using ONLY the retrieved documents.\n\n{GROUNDING_RULES}"
            f"\n\n## Retrieved Documents:\n{state['narrowed']}"
            f"\n\n## User Question:\n{state['query']}"
            f"{history_block}"
        )
    else:
        answer_prompt = config_prompt(state["narrowed"], state["query"]) + history_block

    answer = _invoke_text(
        _make_llm(temperature=settings.deepseek_temperature),
        [SystemMessage(content=_SYSTEM_PROMPTS[agent_type]), HumanMessage(content=answer_prompt)],
        node="answer",
    )
    # An empty/citation-only/not-found answer triggers the verify/wide_search loop
    found = _answer_ok(answer)
    return {"answer": answer, "citations": _extract_citations(answer), "verified": found}


@_traced("verify")
def verify_node(state: AgentState) -> dict:
    system_prompt = _SYSTEM_PROMPTS.get(
        state.get("agent_type"), _SYSTEM_PROMPTS["due_diligence"]
    )
    try:
        verified = _invoke_text(_make_llm(), [
            SystemMessage(content=system_prompt),
            HumanMessage(content=VERIFICATION_PROMPT.format(
                query=state["query"], retrieved=state["narrowed"]
            )),
        ], node="verify")
        if _answer_ok(verified):
            return {"answer": verified, "citations": _extract_citations(verified), "verified": True}
    except Exception:
        pass
    return {"verified": False}


def _build_wide_context(
    vs: VectorStore,
    queries: list[str],
    allowed_filenames: list[str] | None = None,
    limit: int = 30,
) -> str:
    """Build a rescue-mode retrieval context with fair per-document sampling.

    Searches ALL collections within the retrieval scope (no document
    detection — misrouting is a common failure mode by the time we reach
    wide_search) and interleaves chunks round-robin across documents. A pure
    score-ordered list lets one over-represented document (e.g. a memo
    mentioning the same fund name as the CV) drown out the document that
    actually answers the question.
    """
    seen: set[str] = set()
    per_doc: dict[str, list[dict]] = {}
    scope = set(allowed_filenames) if allowed_filenames is not None else None
    for q in queries:
        for r in vs.search(q, k=40, filenames=scope):
            key = r["content"][:100]
            if key in seen:
                continue
            seen.add(key)
            fn = r["metadata"].get("filename", "?")
            per_doc.setdefault(fn, []).append(r)

    picked: list[dict] = []
    for rnd in range(max(len(chunks) for chunks in per_doc.values())):
        for doc_chunks in per_doc.values():
            if rnd < len(doc_chunks):
                picked.append(doc_chunks[rnd])
                if len(picked) >= limit:
                    break
        if len(picked) >= limit:
            break

    formatted = []
    for r in picked:
        m = r["metadata"]
        formatted.append(
            f"[Source {len(formatted)+1}: {m.get('filename','?')}, "
            f"page {m.get('page',1)}, line {m.get('line',1)}]\n{r['content']}"
        )
    return "\n\n".join(formatted)


@_traced("wide_search")
def wide_search_node(state: AgentState) -> dict:
    """Deep re-search after verify failed."""
    query = state["query"]
    vs = _get_store(state)

    queries = [query]
    keywords = [w for w in re.findall(r"[a-zA-Z0-9]+", query) if w.lower() not in _STOP_WORDS and len(w) > 1]
    if keywords:
        queries.append(" ".join(keywords))

    wide_text = _build_wide_context(vs, queries, state.get("allowed_filenames"))
    if not wide_text:
        return {"verified": True}

    try:
        system_prompt = _SYSTEM_PROMPTS.get(
            state.get("agent_type"), _SYSTEM_PROMPTS["due_diligence"]
        )
        verified = _invoke_text(_make_llm(), [
            SystemMessage(content=system_prompt),
            HumanMessage(content=VERIFICATION_PROMPT.format(
                query=query, retrieved=wide_text
            )),
        ], node="wide_search")
        if _answer_ok(verified):
            return {"answer": verified, "citations": _extract_citations(verified), "verified": True}
    except Exception:
        pass

    return {"verified": True}


# ---------------------------------------------------------------------------
# Conditional edges
# ---------------------------------------------------------------------------
def should_classify(state: AgentState) -> str:
    """Skip LLM/keyword classification when the caller forced an agent type."""
    return "search" if state.get("agent_type_forced") else "classify"



@_traced("review")
def review_node(state: AgentState) -> dict:
    """Human-in-the-loop review node.

    Checks state['human_review_decision'] for:
    - 'approve': pass answer through unchanged
    - 'edit': replace answer with state['human_edited_answer']
    - not set: mark review as pending (UI will collect decision)
    """
    decision = state.get("human_review_decision")

    if decision == "approve":
        return {"reviewed": True}

    if decision == "edit":
        edited = state.get("human_edited_answer", state.get("answer", ""))
        return {"answer": edited, "reviewed": True}

    return {"review_pending": True}


def should_review(state: AgentState) -> str:
    """Route to review if enabled and not already reviewed."""
    if state.get("reviewed"):
        return "verify" if not state.get("verified", True) else "end"
    if settings.enable_human_review:
        return "review"
    return "verify" if not state.get("verified", True) else "end"


def should_verify(state: AgentState) -> str:
    return "end" if state.get("verified", True) else "verify"


def after_verify(state: AgentState) -> str:
    return "end" if state.get("verified", True) else "wide_search"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------
def build_agent_graph() -> StateGraph:
    graph = StateGraph(AgentState)
    for name, fn in [("classify", classify_node), ("search", search_node),
                     ("narrow", narrow_node), ("answer", answer_node),
                     ("review", review_node),
                     ("verify", verify_node), ("wide_search", wide_search_node)]:
        graph.add_node(name, fn)

    graph.set_conditional_entry_point(
        should_classify, {"classify": "classify", "search": "search"}
    )
    graph.add_edge("classify", "search")
    graph.add_edge("search", "narrow")
    graph.add_edge("narrow", "answer")
    # If human review is enabled, route to review before verify
    graph.add_conditional_edges("answer", should_review, {
        "review": "review", "verify": "verify", "end": END,
    })
    graph.add_conditional_edges("review", should_verify, {
        "verify": "verify", "end": END,
    })
    graph.add_conditional_edges("verify", after_verify, {"wide_search": "wide_search", "end": END})
    graph.add_edge("wide_search", END)
    return graph.compile()


_compiled_graph = None


def get_agent_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_agent_graph()
    return _compiled_graph
