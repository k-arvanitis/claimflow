from __future__ import annotations

import anthropic

from claimflow.config import settings
from claimflow.state import ClaimState, PolicyAnswer

_client: anthropic.Anthropic | None = None
_qdrant = None
_reranker = None


def _get_qdrant():
    global _qdrant
    if _qdrant is None:
        from qdrant_client import QdrantClient
        _qdrant = QdrantClient(url=settings.qdrant_url)
    return _qdrant


def _get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    return _reranker


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    return _client


def _failure_to_question(failure: dict) -> str:
    rule = failure["rule"]
    reason = failure["reason"]
    if rule == "icd10_lookup":
        return f"Is the following diagnosis code billable under standard health insurance policy? {reason}"
    if rule == "cpt_lookup":
        return f"Is the following procedure code covered? {reason}"
    if rule == "arithmetic":
        return f"What is the policy on charge discrepancies? {reason}"
    return f"What does policy say about: {reason}"


def _search(question: str) -> list[dict]:
    qdrant = _get_qdrant()
    try:
        hits = qdrant.query(
            collection_name=settings.qdrant_collection,
            query_text=question,
            limit=5,
        )
        return [{"text": h.document, "score": h.score} for h in hits]
    except Exception:
        return []


def _synthesize(question: str, chunks: list[dict]) -> PolicyAnswer:
    if not chunks:
        return PolicyAnswer(
            question=question,
            answer="No relevant policy document found.",
            citations=[],
        )

    reranker = _get_reranker()
    pairs = [(question, c["text"]) for c in chunks]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
    top = [c for _, c in ranked[:3]]

    context = "\n\n".join(f"[{i+1}] {c['text']}" for i, c in enumerate(top))
    prompt = (
        f"Answer the following question using only the policy excerpts below. "
        f"Cite sources as [1], [2], [3].\n\n"
        f"Question: {question}\n\nPolicy excerpts:\n{context}"
    )

    response = _get_client().messages.create(
        model=settings.llm_model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return PolicyAnswer(
        question=question,
        answer=response.content[0].text,
        citations=[f"policy excerpt [{i+1}]" for i in range(len(top))],
    )


def retrieve_node(state: ClaimState) -> dict:
    failures = state.get("validation_failures") or []
    if not failures:
        return {"policy_answers": []}

    answers: list[PolicyAnswer] = []
    seen_questions: set[str] = set()
    for failure in failures:
        question = _failure_to_question(failure)
        if question in seen_questions:
            continue
        seen_questions.add(question)
        chunks = _search(question)
        answers.append(_synthesize(question, chunks))

    return {"policy_answers": answers}
