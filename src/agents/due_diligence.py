"""Due Diligence Agent — delegates to the LangGraph agent graph."""

from src.agents.graph import AgentState, PARSERS, get_agent_graph
from src.core.models import DueDiligenceResult
from src.tools.search import create_search_tool
from src.vector_store.chroma import VectorStore


class DueDiligenceAgent:
    def __init__(self, vector_store: VectorStore, api_key: str | None = None):
        self.vector_store = vector_store
        self.graph = get_agent_graph()
        self.search_tool = create_search_tool(vector_store)
        self.tools = [self.search_tool]

    def invoke(self, query: str) -> DueDiligenceResult:
        final = self.graph.invoke({
            "query": query, "agent_type": "due_diligence", "agent_type_forced": True,
            "retrieved": "", "narrowed": "", "answer": "",
            "verified": False, "citations": [], "conversation_history": [],
            "vector_store": self.vector_store, "trace": [],
        })
        answer = final.get("answer", "")
        result = DueDiligenceResult(**PARSERS["due_diligence"](answer))
        result._raw_output = answer
        return result
