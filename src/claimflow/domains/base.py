from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from doc_intel.schemas.base import SchemaSpec

from claimflow.state import ValidationFailure


@dataclass
class Domain:
    doc_type: str
    keywords: set[str]
    spec: SchemaSpec
    validate: Callable[[dict], list[ValidationFailure]]
    supporting_types: dict[str, set[str]] = field(default_factory=dict)

    # DomainPack fields — all additive, all default to today's implicit behavior.
    display_name: str = ""
    policy_collection: str | None = None
    retrieval_mode: Literal["official_deterministic", "llm_synthesis"] = "llm_synthesis"
    question_templates: dict[str, str] = field(default_factory=dict)
    extraction_hook: Callable[[Any, str], None] | None = None
    extract_fn: Callable[[str, Any], Any] | None = None
    confidence_threshold: float | None = None
    escalation_threshold: float | None = None
    reviewer_guidance: str = ""
    client_name_field: str | None = None


_REGISTRY: dict[str, Domain] = {}


def register(domain: Domain) -> None:
    _REGISTRY[domain.doc_type] = domain


def all_domains() -> list[Domain]:
    return list(_REGISTRY.values())


def get(doc_type: str) -> Domain | None:
    return _REGISTRY.get(doc_type)
