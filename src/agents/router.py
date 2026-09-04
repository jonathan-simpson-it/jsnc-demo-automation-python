"""Router — thin dispatcher that invokes the LangGraph agent graph."""

import json
from collections.abc import Generator

from src.agents.graph import (
    _STRUCTURED_NO_DATA_TYPES,
    PARSERS,
    AgentState,
    annotate_round_mismatch,
    empty_scope_result,
    get_agent_graph,
    scope_lacks_data,
)
from src.core.models import AgentResponse
from src.utils.confidence import classify_routing_method, compute_confidence
from src.vector_store.chroma import VectorStore


class RouterAgent:
    """Central router that dispatches queries through the agent graph."""

    def __init__(self, vector_store: VectorStore, api_key: str | None = None):
        self.vector_store = vector_store
        self.graph = get_agent_graph()

    def invoke(
        self,
        query: str,
        agent_type: str | None = None,
        conversation_history: list[dict] | None = None,
        allowed_filenames: list[str] | None = None,
    ) -> AgentResponse:
        initial_state: AgentState = {
            "query": query,
            "agent_type": agent_type or "due_diligence",
            "agent_type_forced": agent_type is not None,
            "retrieved": "", "narrowed": "", "answer": "",
            "verified": False, "citations": [],
            "conversation_history": conversation_history or [],
            "allowed_filenames": allowed_filenames,
            "vector_store": self.vector_store,
            "trace": [],
        }

        try:
            final = self.graph.invoke(initial_state)
            agent_type_final = final.get("agent_type", "due_diligence")
            answer = final.get("answer", "")
            citations = final.get("citations", [])

            parser = PARSERS.get(agent_type_final)
            if (
                agent_type_final in _STRUCTURED_NO_DATA_TYPES
                and not citations
                and scope_lacks_data(
                    final.get("narrowed") or final.get("retrieved") or ""
                )
            ):
                # Empty scope: no LLM-extracted skeleton — say so explicitly.
                result_data = empty_scope_result(agent_type_final)
            elif parser:
                result_data = parser(answer)
            else:
                result_data = {"summary": answer}

            # Term-sheet questions that name a round the extracted data is
            # not for get an explicit notice instead of silent closest-match.
            if agent_type_final == "term_sheet":
                result_data = annotate_round_mismatch(query, result_data)

            trace = final.get("trace", [])
            confidence = compute_confidence(trace, citations)
            routing = classify_routing_method(trace, agent_type is not None)

            response = AgentResponse(
                agent_type=agent_type_final,
                result=json.dumps(result_data, default=str),
                citations=citations,
                confidence_score=confidence,
                metadata={
                    "query": query,
                    "agent_type": agent_type_final,
                    "agent_type_forced": agent_type is not None,
                    "trace": trace,
                    "routing_method": routing,
                },
            )
            return response
        except Exception as e:
            return AgentResponse(
                agent_type=agent_type or "due_diligence",
                result=f"Error: {e}",
                metadata={"error": True},
            )

    def invoke_streaming(
        self,
        query: str,
        agent_type: str | None = None,
        conversation_history: list[dict] | None = None,
        allowed_filenames: list[str] | None = None,
    ) -> Generator[dict, None, None]:
        """Yield node-by-node state updates as the graph executes.

        Each yield is a dict with keys:
            - node: the node name ("classify", "search", "narrow", "answer", ...)
            - update: the state update dict returned by that node
            - done: False while running, True on the final yield

        The final yield carries the full AgentResponse in "response".
        """
        initial_state: AgentState = {
            "query": query,
            "agent_type": agent_type or "due_diligence",
            "agent_type_forced": agent_type is not None,
            "retrieved": "", "narrowed": "", "answer": "",
            "verified": False, "citations": [],
            "conversation_history": conversation_history or [],
            "allowed_filenames": allowed_filenames,
            "vector_store": self.vector_store,
            "trace": [],
        }

        final_state = initial_state.copy()
        try:
            for event in self.graph.stream(
                initial_state, stream_mode="updates"
            ):
                for node_name, update in event.items():
                    final_state.update(update)
                    yield {
                        "node": node_name,
                        "update": update,
                        "done": False,
                    }

            # Build the final response from accumulated state
            agent_type_final = final_state.get(
                "agent_type", "due_diligence"
            )
            answer = final_state.get("answer", "")
            citations = final_state.get("citations", [])
            trace = final_state.get("trace", [])

            parser = PARSERS.get(agent_type_final)
            if (
                agent_type_final in _STRUCTURED_NO_DATA_TYPES
                and not citations
                and scope_lacks_data(
                    final_state.get("narrowed")
                    or final_state.get("retrieved")
                    or ""
                )
            ):
                result_data = empty_scope_result(agent_type_final)
            elif parser:
                result_data = parser(answer)
            else:
                result_data = {"summary": answer}

            # Term-sheet questions that name a round the extracted data is
            # not for get an explicit notice instead of silent closest-match.
            if agent_type_final == "term_sheet":
                result_data = annotate_round_mismatch(query, result_data)
            confidence = compute_confidence(trace, citations)
            routing = classify_routing_method(
                trace, agent_type is not None
            )

            response = AgentResponse(
                agent_type=agent_type_final,
                result=json.dumps(result_data, default=str),
                citations=citations,
                confidence_score=confidence,
                metadata={
                    "query": query,
                    "agent_type": agent_type_final,
                    "agent_type_forced": agent_type is not None,
                    "trace": trace,
                    "routing_method": routing,
                },
            )
            yield {"done": True, "response": response}

        except Exception as e:
            yield {
                "done": True,
                "response": AgentResponse(
                    agent_type=agent_type or "due_diligence",
                    result=f"Error: {e}",
                    metadata={"error": True},
                ),
            }
