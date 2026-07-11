from __future__ import annotations

import logging
import os

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from claimflow.config import settings
from claimflow.prompts import PROMPT_VERSION, RETRIEVAL_SYNTHESIS
from claimflow.state import ClaimState, PolicyAnswer

logger = logging.getLogger(__name__)

_qdrant = None
_reranker = None
_llm_client = None


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


def _get_llm_client():
    global _llm_client
    if _llm_client is None:
        if settings.doc_intel_provider == "anthropic":
            import anthropic
            _llm_client = ("anthropic", anthropic.Anthropic(
                api_key=settings.anthropic_api_key.get_secret_value()
            ))
        else:
            from openai import OpenAI
            _llm_client = ("openai", OpenAI(
                api_key=os.environ.get("OPENAI_API_KEY", "local"),
                base_url=settings.doc_intel_llm_base_url or "https://api.openai.com/v1",
            ))
    return _llm_client


def _failure_to_question(failure: dict, domain_key: str | None) -> str:
    rule = failure["rule"]
    reason = failure["reason"]
    if domain_key == "cms1500":
        if rule == "icd10_lookup":
            return f"Is the following diagnosis code billable under standard health insurance policy? {reason}"
        if rule == "cpt_lookup":
            return f"Is the following procedure code covered? {reason}"
        if rule == "arithmetic":
            return f"What is the policy on charge discrepancies? {reason}"
    if domain_key == "xactimate":
        if rule == "arithmetic":
            return f"What is the policy on line-item total discrepancies in property estimates? {reason}"
        if rule == "acv_check":
            return f"What is the policy when actual cash value does not equal RCV minus depreciation? {reason}"
        if rule == "negative_amount":
            return f"What is the policy when a claim amount is negative? {reason}"
    if domain_key == "loan":
        if rule == "income_consistency":
            return f"What is the policy when net income exceeds gross revenue on a loan application? {reason}"
        if rule == "positive_amount":
            return f"What is the minimum loan amount required? {reason}"
        if rule == "signature_required":
            return f"What happens when a loan application is missing a signature? {reason}"
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
    except Exception as e:
        logger.error("Qdrant search failed: %s", e)
        return []


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=lambda rs: logger.warning("LLM call failed, retrying (attempt %d)", rs.attempt_number),
)
def _call_llm(prompt: str) -> str:
    provider, client = _get_llm_client()
    if provider == "anthropic":
        response = client.messages.create(
            model=settings.llm_model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    else:
        response = client.chat.completions.create(
            model=settings.doc_intel_model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""


def _synthesize(question: str, chunks: list[dict]) -> PolicyAnswer:
    if not chunks:
        return PolicyAnswer(question=question, answer="No relevant policy document found.", citations=[])

    reranker = _get_reranker()
    pairs = [(question, c["text"]) for c in chunks]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
    top = [c for _, c in ranked[:3]]

    context = "\n\n".join(f"[{i+1}] {c['text']}" for i, c in enumerate(top))
    prompt = RETRIEVAL_SYNTHESIS.format(question=question, context=context)
    citations = [f"policy excerpt [{i+1}]" for i in range(len(top))]

    logger.info("Synthesising policy answer (prompt_version=%s)", PROMPT_VERSION)
    try:
        answer = _call_llm(prompt)
    except Exception as e:
        logger.error("LLM synthesis failed after retries: %s", e)
        answer = "Policy lookup failed — manual review required."

    return PolicyAnswer(question=question, answer=answer, citations=citations)


def retrieve_node(state: ClaimState) -> dict:
    failures = state.get("validation_failures") or []
    if not failures:
        return {"policy_answers": []}

    domain_key = state.get("domain")
    answers: list[PolicyAnswer] = []
    seen: set[str] = set()
    for failure in failures:
        question = _failure_to_question(failure, domain_key)
        if question in seen:
            continue
        seen.add(question)
        chunks = _search(question)
        answers.append(_synthesize(question, chunks))

    return {"policy_answers": answers}
