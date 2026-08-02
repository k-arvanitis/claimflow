from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from claimflow.nodes.extract import extract_node
from claimflow.nodes.ingest import ingest_node
from claimflow.nodes.retrieve import retrieve_node
from claimflow.nodes.review import review_node
from claimflow.nodes.validate import validate_node
from claimflow.state import ClaimState


def _should_retrieve(state: ClaimState) -> str:
    if state.get("validation_failures"):
        return "retrieve"
    return "review"


def build_graph():
    g = StateGraph(ClaimState)

    g.add_node("ingest", ingest_node)
    g.add_node("extract", extract_node)
    g.add_node("validate", validate_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("review", review_node)

    g.set_entry_point("ingest")
    g.add_edge("ingest", "extract")
    g.add_edge("extract", "validate")
    g.add_conditional_edges(
        "validate", _should_retrieve, {"retrieve": "retrieve", "review": "review"}
    )
    g.add_edge("retrieve", "review")
    g.add_edge("review", END)

    return g.compile(checkpointer=MemorySaver())
