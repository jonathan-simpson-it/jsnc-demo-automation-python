"""Document summarization on ingestion.

Generates a concise one-paragraph summary of a document using the LLM,
stored in ChromaDB collection metadata alongside auto-generated TF-IDF
signals. Displayed in the Streamlit sidebar so users know what's in the
corpus without querying.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage


def summarize_document(
    content: str,
    filename: str,
    *,
    max_chars: int = 2000,
    llm=None,
) -> str:
    """Generate a one-paragraph summary of a document for sidebar display.

    Args:
        content: Full document text.
        filename: Filename (for context in the prompt).
        max_chars: Truncate content to this many chars before summarizing.
        llm: Optional LLM instance. If None, creates a default ChatDeepSeek.

    Returns:
        A 1-3 sentence summary, or empty string on failure.
    """
    if not content or not content.strip():
        return ""

    excerpt = content[:max_chars]

    try:
        if llm is None:
            from src.agents.graph import _make_llm
            llm = _make_llm(temperature=0)

        resp = llm.invoke([
            SystemMessage(
                content=(
                    "Summarize this document in 1-2 sentences. "
                    "Be specific about key topics, data points, and purpose. "
                    "Do not use markdown formatting."
                )
            ),
            HumanMessage(
                content=f"Document: {filename}\n\n{excerpt}"
            ),
        ])
        return resp.content.strip()
    except Exception:
        return ""
