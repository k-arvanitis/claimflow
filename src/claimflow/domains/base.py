from dataclasses import dataclass, field
from typing import Callable

from doc_intel.schemas.base import SchemaSpec

from claimflow.state import ValidationFailure


@dataclass
class Domain:
    doc_type: str
    keywords: set[str]
    spec: SchemaSpec
    validate: Callable[[dict], list[ValidationFailure]]
    supporting_types: dict[str, set[str]] = field(default_factory=dict)


_REGISTRY: dict[str, Domain] = {}


def register(domain: Domain) -> None:
    _REGISTRY[domain.doc_type] = domain


def all_domains() -> list[Domain]:
    return list(_REGISTRY.values())


def get(doc_type: str) -> Domain | None:
    return _REGISTRY.get(doc_type)
