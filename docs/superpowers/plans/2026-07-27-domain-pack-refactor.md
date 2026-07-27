# DomainPack Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn ClaimFlow's existing per-doc-type `Domain` registry (`src/claimflow/domains/base.py`) into a real `DomainPack` that owns everything currently scattered as `domain_key == "cms1500"` string-literal branches in `extract.py` and `retrieve.py`, add severity/policy-dependency to validation failures, replace the `approved/flagged/escalated` decision vocabulary with safe routing labels (`ready_for_processing/needs_review/blocked_or_incomplete`), and expose a read-only domain-pack inspector — without rebuilding anything that already works.

**Architecture:** `domains/base.py`'s `Domain` dataclass is extended in place (not replaced) with the fields today's node code hardcodes per string literal: `display_name`, an `extraction_hook: Callable[[ExtractionResult, str], None] | None` (post-extraction correction, e.g. today's EOB-payer/SBA-413-widget fixups), an `extract_fn: Callable[[str, SchemaSpec], ExtractionResult] | None` override (today's CMS-1500-region / Xactimate-page special extraction paths), `policy_collection: str`, `retrieval_mode: Literal["official_deterministic", "llm_synthesis"]`, `question_templates: dict[str, str]` (replacing the `if domain_key == "cms1500": if rule == ...` ladders), `confidence_threshold`/`escalation_threshold` (falling back to the current global `settings` values when unset — no domain sets them yet, so behavior is unchanged), and `reviewer_guidance: str`. `extract_node` and `retrieve.py` become table lookups against these fields instead of `if/elif` chains on `domain_key`. This is confirmed safe by the research pass: `ingest.py`, `validate.py`, `review.py`, and `api/main.py` already have **zero** domain-literal branches — only `extract.py` (5 branch sites) and `retrieve.py` (4 branch sites, plus the `_POLICY_DOMAINS` dict) need to change.

Routing rename is the one genuinely breaking change (touches `state.py`, `nodes/review.py`, `db.py` comment, `schemas/enums.py`, `api/main.py`'s `target_status` string comparison, Streamlit, frontend, and every test asserting the old labels) — it needs one Alembic data migration to rewrite existing `decisions.decision` rows, not a new table.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy + Alembic, LangGraph, pytest (mocked `doc_intel`/Qdrant throughout, per existing convention), Next.js/TypeScript (frontend label updates only), Streamlit (label updates only).

## Global Constraints

- Do not touch `src/claimflow/nodes/ingest.py` or `src/claimflow/nodes/validate.py` — confirmed domain-agnostic already; no task in this plan modifies them.
- Do not introduce a new database or a new top-level "broad domain" grouping (health/property/loan) above the existing per-doc-type `Domain` registry — `state["domain"]` is already the fine-grained doc_type key (`state.py:27`) and `Domain` is keyed the same way (`domains/base.py:22`); `DomainPack` extends that existing key, it does not add a new grouping layer.
- Do not build a rule-language interpreter, a generic no-code schema editor, or policy-to-executable-rule generation. The domain-pack "configuration" surface for this plan is read-only inspection (`GET /domain-packs`, `GET /domain-packs/{key}`) — editable admin config is explicitly out of scope per the spec's "read-only inspector, keep configuration file-based for now" fallback.
- Preserve `Domain.doc_type`, `.keywords`, `.spec`, `.validate`, `.supporting_types` exactly as-is (field names and positions) — every existing `register(Domain(...))` call in `health.py`/`property.py`/`loan.py` must keep working with only additive fields appended.
- `ValidationFailure` gains `severity: Literal["error","warning"]` and `policy_required: bool` — every domain's `_validate()` function must set both on every failure it returns; do not leave old call sites constructing 3-key dicts once the TypedDict requires 5 keys.
- New Alembic migration chains `down_revision = "0005"` → `"0006"`.
- Decision label migration is data-only (`UPDATE decisions SET decision = ... WHERE decision = 'approved'` etc.) — no schema/column change needed, `Decision.decision` is already a bare `String`.
- Every task that changes a response shape must update `test_openapi_contract.py`'s expectations in the same task, not a later one — that test currently pins the full schema/route count.
- Mock `doc_intel`, Qdrant, and any LLM/reranker calls in tests exactly as the existing suite does (see `tests/conftest.py` fixtures) — no task in this plan should add a test that makes a live network call.
- CMS-1500 stays the only pack with `retrieval_mode="official_deterministic"`; Xactimate/loan/EOB/etc. keep `retrieval_mode="llm_synthesis"` — do not attempt to build official-source retrieval for the other domains (PROGRESS.md Session N+8/N+9 already documented that their policy PDFs are self-authored/non-canonical; that's an honest limitation to document, not fix, in this plan).

---

### Task 1: Extend `Domain` → register `DomainPack` fields (additive, no behavior change)

**Files:**
- Modify: `src/claimflow/domains/base.py`
- Test: `tests/test_domain_pack.py` (new)

**Interfaces:**
- Produces: `Domain` dataclass with new optional fields `display_name: str`, `policy_collection: str | None`, `retrieval_mode: Literal["official_deterministic", "llm_synthesis"]`, `question_templates: dict[str, str]`, `extraction_hook: Callable[[Any, str], None] | None`, `extract_fn: Callable[[str, Any], Any] | None`, `confidence_threshold: float | None`, `escalation_threshold: float | None`, `reviewer_guidance: str`. All default so every existing `register(Domain(...))` call site keeps compiling unchanged.
- Consumes: nothing new — `doc_intel.schemas.base.SchemaSpec`, `claimflow.state.ValidationFailure` (already imported).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_domain_pack.py
from claimflow.domains.base import Domain, all_domains, get, register


def test_domain_pack_fields_have_safe_defaults():
    register(
        Domain(
            doc_type="_test_pack",
            keywords={"testword"},
            spec=None,
            validate=lambda data: [],
        )
    )
    pack = get("_test_pack")
    assert pack.display_name == ""
    assert pack.retrieval_mode == "llm_synthesis"
    assert pack.question_templates == {}
    assert pack.extraction_hook is None
    assert pack.extract_fn is None
    assert pack.confidence_threshold is None
    assert pack.escalation_threshold is None
    assert pack.reviewer_guidance == ""


def test_all_domains_includes_every_registered_pack():
    names = {d.doc_type for d in all_domains()}
    assert {"cms1500", "xactimate", "loan", "eob", "sba_form_413"} <= names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_domain_pack.py -v`
Expected: FAIL — `TypeError: Domain.__init__() got an unexpected keyword argument` is not the failure (spec/validate are required positional already); expect `AttributeError: 'Domain' object has no attribute 'display_name'`.

- [ ] **Step 3: Add the fields**

```python
# src/claimflow/domains/base.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_domain_pack.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/claimflow/domains/base.py tests/test_domain_pack.py
git commit -m "feat: extend Domain registry with DomainPack fields"
```

---

### Task 2: Populate DomainPack fields on every existing domain registration

**Files:**
- Modify: `src/claimflow/domains/health.py` (registrations for `cms1500`, `eob`, `medicare_summary_notice`)
- Modify: `src/claimflow/domains/property.py` (registrations for `xactimate`, `declarations_page`)
- Modify: `src/claimflow/domains/loan.py` (registrations for `loan`, `sba_form_413`, `sba_form_2202`)
- Test: `tests/test_domain_pack.py`

**Interfaces:**
- Consumes: `Domain` from Task 1.
- Produces: every `register(Domain(...))` call site now also sets `display_name`, `policy_collection` (`"health"`/`"property"`/`"loan"` — the exact values currently hardcoded in `retrieve.py:22-31`'s `_POLICY_DOMAINS`), and `retrieval_mode="official_deterministic"` for `cms1500` only (everything else stays the `"llm_synthesis"` default).

- [ ] **Step 1: Write the failing test**

```python
def test_cms1500_pack_is_the_official_source_domain():
    from claimflow.domains.base import get

    pack = get("cms1500")
    assert pack.display_name == "CMS-1500 Health Claim"
    assert pack.policy_collection == "health"
    assert pack.retrieval_mode == "official_deterministic"


def test_xactimate_and_loan_use_llm_synthesis():
    from claimflow.domains.base import get

    assert get("xactimate").retrieval_mode == "llm_synthesis"
    assert get("xactimate").policy_collection == "property"
    assert get("loan").retrieval_mode == "llm_synthesis"
    assert get("loan").policy_collection == "loan"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_domain_pack.py -v`
Expected: FAIL — `assert '' == 'CMS-1500 Health Claim'`

- [ ] **Step 3: Update each registration**

In `health.py`, find `register(Domain(doc_type="cms1500", ...))` and add the new kwargs (keep every existing kwarg untouched):

```python
register(
    Domain(
        doc_type="cms1500",
        keywords=_CMS1500_KEYWORDS,          # unchanged, use actual existing name
        spec=CMS1500_SPEC,                   # unchanged, use actual existing name
        validate=_validate,                  # unchanged
        supporting_types=_SUPPORTING_TYPES,  # unchanged
        display_name="CMS-1500 Health Claim",
        policy_collection="health",
        retrieval_mode="official_deterministic",
        reviewer_guidance=(
            "CMS-1500 is the primary, most-validated domain pack. Validation "
            "checks NPI format, ICD-10/CPT lookup membership, and arithmetic; "
            "policy citations come from official CMS manuals, not synthetic text."
        ),
    )
)
```

Do the same additive edit (display_name + policy_collection, `retrieval_mode` left at default) for `eob` and `medicare_summary_notice` in `health.py`, `xactimate` and `declarations_page` in `property.py`, and `loan`, `sba_form_413`, `sba_form_2202` in `loan.py`. Use `git grep -n "register(Domain(doc_type=" src/claimflow/domains/` to find every call site before editing so none are missed.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_domain_pack.py -v`
Expected: PASS

- [ ] **Step 5: Run the full existing domain test files to confirm no regression**

Run: `uv run pytest tests/test_new_domains.py tests/test_validate.py tests/test_lookups.py -v`
Expected: PASS (unchanged — these fields are additive only)

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/domains/health.py src/claimflow/domains/property.py src/claimflow/domains/loan.py tests/test_domain_pack.py
git commit -m "feat: populate DomainPack display name, policy collection, retrieval mode per domain"
```

---

### Task 3: Replace `retrieve.py`'s domain-literal branches with DomainPack lookups

**Files:**
- Modify: `src/claimflow/nodes/retrieve.py`
- Test: `tests/test_graph.py` (existing retrieval tests: `test_cms_policy_question_targets_billing_provider_npi`, `test_policy_search_filters_to_the_claim_domain`, `test_cms_policy_answer_is_deterministic_and_does_not_call_llm`, `test_policy_answer_citations_include_source_and_excerpt`)

**Interfaces:**
- Consumes: `get_domain(doc_type)` (already imported elsewhere in the codebase from `claimflow.domains.base` as `get`) to read `.policy_collection`, `.retrieval_mode`, `.question_templates`.
- Produces: `_failure_to_question`, `_search`, `_synthesize` keep their exact current signatures (`domain_key: str | None`) so `retrieve_node` (the only caller) needs zero changes — only their internal branching changes from string comparison to a `Domain` lookup.

- [ ] **Step 1: Write the failing test (a case the old `_POLICY_DOMAINS` dict couldn't express: adding a domain's policy_collection without touching retrieve.py)**

```python
def test_search_uses_domain_pack_policy_collection_not_hardcoded_dict(monkeypatch):
    from claimflow.domains import base as domains_base
    from claimflow.nodes.retrieve import _search

    fake_pack = domains_base.Domain(
        doc_type="_fake_domain", keywords=set(), spec=None, validate=lambda d: [],
        policy_collection="fake_collection",
    )
    domains_base.register(fake_pack)

    captured = {}

    class FakeQdrant:
        def query(self, **kwargs):
            captured["filter"] = kwargs["query_filter"]
            return []

    monkeypatch.setattr("claimflow.nodes.retrieve._get_qdrant", lambda: FakeQdrant())
    _search("question", "_fake_domain")
    assert "fake_collection" in str(captured["filter"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_graph.py -k domain_pack_policy_collection -v`
Expected: FAIL — `_POLICY_DOMAINS.get("_fake_domain")` returns `None`, filter has no `domain` condition, `"fake_collection" not in str(captured["filter"])`.

- [ ] **Step 3: Replace the branching**

Remove `_POLICY_DOMAINS` (`retrieve.py:22-31`). Change `_search` (`retrieve.py:119-137`):

```python
def _search(question: str, domain_key: str | None) -> list[dict]:
    from qdrant_client import models

    from claimflow.domains.base import get as get_domain

    qdrant = _get_qdrant()
    pack = get_domain(domain_key) if domain_key else None
    conditions = []
    if pack and pack.policy_collection:
        conditions.append(
            models.FieldCondition(
                key="domain", match=models.MatchValue(value=pack.policy_collection)
            )
        )
    if pack and pack.retrieval_mode == "official_deterministic":
        conditions.append(
            models.FieldCondition(
                key="authority", match=models.MatchValue(value="official_cms")
            )
        )
    query_filter = models.Filter(must=conditions) if conditions else None
    ...  # rest of function body (the try/except query block) unchanged
```

Change `_failure_to_question` (`retrieve.py:78-116`) to look up `pack.question_templates.get(rule)` first, falling back to the existing per-domain `if` ladder only for the two field-name-based special cases (NPI-suffix check) that a flat rule-keyed dict can't express:

```python
def _failure_to_question(failure: dict, domain_key: str | None) -> str:
    from claimflow.domains.base import get as get_domain

    rule = failure["rule"]
    reason = failure["reason"]
    if domain_key == "cms1500" and str(failure.get("field", "")).endswith("npi"):
        return (
            "What do CMS rules require for the billing provider National "
            "Provider Identifier (NPI) in CMS-1500 Item 33a, including the "
            f"10-digit numeric format? {reason}"
        )
    pack = get_domain(domain_key) if domain_key else None
    template = pack.question_templates.get(rule) if pack else None
    if template:
        return template.format(reason=reason)
    return f"What does policy say about: {reason}"
```

Then in Task 2's registration edits, add `question_templates` to each pack, e.g. for `cms1500`:
```python
question_templates={
    "icd10_lookup": "What CMS-1500 policy applies when Item 21 contains an unrecognized ICD-10-CM diagnosis code? {reason}",
    "cpt_lookup": "What CMS-1500 policy applies when Item 24D contains an unrecognized CPT/HCPCS procedure code? {reason}",
    "arithmetic": "What is the policy on charge discrepancies? {reason}",
},
```
(and the equivalent `xactimate`/`loan` dicts from the current `if domain_key == "xactimate": ...` / `if domain_key == "loan": ...` blocks, `retrieve.py:100-115`). Go back and add these `question_templates=` kwargs to Task 2's edits before running this task's tests.

Change `_synthesize` (`retrieve.py:219-267`) to branch on `pack.retrieval_mode` instead of `domain_key == "cms1500"` (two occurrences, lines 231 and 257):

```python
    pack = get_domain(domain_key) if domain_key else None
    official = pack is not None and pack.retrieval_mode == "official_deterministic"
    if official:
        ...  # unchanged body
    else:
        ...  # unchanged body
    ...
    if official and failure is not None:
        answer = _cms_policy_answer(failure, len(citations))
    else:
        ...  # unchanged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_graph.py -k domain_pack_policy_collection -v`
Expected: PASS

- [ ] **Step 5: Run every existing retrieval test to confirm no regression**

Run: `uv run pytest tests/test_graph.py -k "policy or retrieve or cms_policy" -v`
Expected: PASS (all 5 pre-existing retrieval tests plus the new one)

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/nodes/retrieve.py src/claimflow/domains/health.py src/claimflow/domains/property.py src/claimflow/domains/loan.py tests/test_graph.py
git commit -m "refactor: drive retrieve.py's domain behavior from DomainPack fields, not string literals"
```

---

### Task 4: Replace `extract.py`'s domain-literal dispatch with DomainPack hooks

**Files:**
- Modify: `src/claimflow/nodes/extract.py` (`extract_node`, lines 1044-1094)
- Modify: `src/claimflow/domains/health.py` (wire `extraction_hook=_correct_eob_payer` for `eob`)
- Modify: `src/claimflow/domains/loan.py` (wire `extraction_hook=_correct_sba_form_413_widgets` for `sba_form_413`)
- Modify: `src/claimflow/domains/health.py` (wire `extract_fn` for `cms1500`, wrapping `_cms1500_region_text` + `_extract_cms1500_text`)
- Modify: `src/claimflow/domains/property.py` (wire `extract_fn=_extract_xactimate_pages` for `xactimate`)
- Test: `tests/test_graph.py` (`test_extract_node_uses_regional_ocr_for_cms1500_image`, plus new dispatch test)

**Interfaces:**
- Consumes: `Domain.extract_fn`, `Domain.extraction_hook` from Task 1.
- Produces: `extract_node` no longer contains any `domain_key ==` comparison — every special-case is looked up from the resolved `domain` object.

- [ ] **Step 1: Write the failing test**

```python
def test_extract_node_has_no_hardcoded_domain_branches():
    import inspect

    from claimflow.nodes.extract import extract_node

    source = inspect.getsource(extract_node)
    assert 'domain_key ==' not in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_graph.py -k no_hardcoded_domain_branches -v`
Expected: FAIL — 5 matches currently present.

- [ ] **Step 3: Add a domain-pack-aware extract wrapper for CMS-1500, then rewrite `extract_node`**

In `health.py`, wrap the two existing CMS-1500-only functions (`_cms1500_region_text`, `_extract_cms1500_text` — both already exist in `extract.py`, imported into `health.py` is not required; instead define the wrapper in `extract.py` itself right above `extract_node` so it can close over the existing private helpers without new cross-module imports):

```python
# src/claimflow/nodes/extract.py, just above extract_node
def _cms1500_extract_fn(source: str, spec) -> "ExtractionResult":
    path = Path(source)
    if path.suffix.lower() in _CMS1500_IMAGE_SUFFIXES:
        regional_text = _cms1500_region_text(path)
        if regional_text:
            return _extract_cms1500_text(regional_text, spec)
    return extract(source, spec, classify_doc=True)
```

Then in `health.py`'s `cms1500` registration, add `extract_fn=_cms1500_extract_fn` — but since `_cms1500_extract_fn` lives in `extract.py` and `health.py` cannot import from `extract.py` without a circular import (`extract.py` already imports domain registrations via `get_domain`), instead assign it after both modules are loaded: add one line to `src/claimflow/domains/__init__.py` (which already runs after `health`/`property`/`loan` register) —

```python
# src/claimflow/domains/__init__.py, after the existing health/loan/property imports
from claimflow.domains.base import get as _get_domain


def _wire_extract_hooks() -> None:
    from claimflow.nodes import extract as _extract_node

    cms1500 = _get_domain("cms1500")
    if cms1500 is not None:
        cms1500.extract_fn = _extract_node._cms1500_extract_fn
    xactimate = _get_domain("xactimate")
    if xactimate is not None:
        xactimate.extract_fn = _extract_node._extract_xactimate_pages
    eob = _get_domain("eob")
    if eob is not None:
        eob.extraction_hook = _extract_node._correct_eob_payer
    sba_form_413 = _get_domain("sba_form_413")
    if sba_form_413 is not None:
        sba_form_413.extraction_hook = _extract_node._correct_sba_form_413_widgets


_wire_extract_hooks()
```

(This late-binding wiring step avoids a circular import between `claimflow.domains` and `claimflow.nodes.extract`, which itself imports from `claimflow.domains.base` for `get_domain`/`Domain`. Confirm the actual import direction with `grep -n "^from claimflow\|^import claimflow" src/claimflow/nodes/extract.py src/claimflow/domains/__init__.py` before writing this — if `extract.py` does NOT import `claimflow.domains` at module scope, the hooks can instead be set directly in `health.py`/`property.py`/`loan.py` via a lazy import inside each registration; prefer that simpler form if it doesn't circular-import.)

Rewrite `extract_node` (`extract.py:1044-1094`):

```python
def extract_node(state: ClaimState) -> dict:
    domain_key = state.get("domain")
    if not domain_key:
        return {
            "error": "No supported domain detected in package",
            "extraction_status": "error",
        }

    domain = get_domain(domain_key)
    if domain is None:
        return {"error": f"Unknown domain: {domain_key}", "extraction_status": "error"}

    claim_doc = next(
        (d for d in state["documents"] if d["doc_type"] == domain_key),
        None,
    )
    if claim_doc is None:
        return {
            "error": f"No {domain_key} document found in package",
            "extraction_status": "error",
        }

    try:
        source: str = claim_doc["path"]
        if domain.extract_fn is not None:
            result = domain.extract_fn(source, domain.spec)
        else:
            result = extract(source, domain.spec, classify_doc=True)
        _null_placeholder_fields(result)
        if domain.extraction_hook is not None and result.status != "error":
            domain.extraction_hook(result, source)
    except Exception as exc:
        return {"error": str(exc), "extraction_status": "error"}

    return {
        "extraction_data": result.data,
        "extraction_fields": [f.model_dump() for f in result.fields],
        "extraction_status": result.status,
        "extraction_overall_confidence": result.overall_confidence,
    }
```

Note: `_correct_eob_payer(result, source)` previously received `load_source(source).full_text` (`extract.py:1083`), not the raw path/text — check its actual signature (`grep -n "def _correct_eob_payer" -A5 src/claimflow/nodes/extract.py`) before wiring; if it needs the loaded text rather than the raw `source` string, keep that one call site's exact argument-construction line inside `extract_node` via a small per-hook adapter rather than forcing every `extraction_hook` to share an identical signature, e.g.:

```python
        if domain.extraction_hook is not None and result.status != "error":
            if domain_key == "eob":
                domain.extraction_hook(result, load_source(source).full_text)
            else:
                domain.extraction_hook(result, source)
```

(This is one narrow, explicit exception, not a reintroduction of general branching — document it with a one-line comment explaining why EOB's hook needs the loaded text instead of the path.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_graph.py -k no_hardcoded_domain_branches -v`
Expected: PASS

- [ ] **Step 5: Run every existing extraction test to confirm no regression**

Run: `uv run pytest tests/test_graph.py tests/test_new_domains.py -v`
Expected: PASS — pay particular attention to `test_extract_node_uses_regional_ocr_for_cms1500_image`, `test_extract_node_calls_doc_intel`, `test_sba_form_413_reads_named_acroform_totals`, `test_eob_payer_requires_an_explicit_payer_label`, `test_xactimate_native_rows_preserve_every_line_and_amount`.

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/nodes/extract.py src/claimflow/domains/__init__.py src/claimflow/domains/health.py src/claimflow/domains/property.py src/claimflow/domains/loan.py tests/test_graph.py
git commit -m "refactor: drive extract_node's domain-specific extraction from DomainPack hooks"
```

---

### Task 5: Add `severity` and `policy_required` to `ValidationFailure`

**Files:**
- Modify: `src/claimflow/state.py` (`ValidationFailure` TypedDict)
- Modify: `src/claimflow/domains/health.py`, `property.py`, `loan.py` (every `_validate()` function's return dicts)
- Modify: `src/claimflow/db.py` (`ValidationFailure` table, `create_validation_failures`)
- Modify: `alembic/versions/0006_validation_failure_severity.py` (new)
- Modify: `src/claimflow/schemas/review_write.py` (`ValidationFailureItem`)
- Modify: `api/main.py` (every place a `ValidationFailureItem`/validation-failure dict is constructed from a DB row or a fresh `_validate()` result)
- Test: `tests/test_validate.py`, `tests/test_migrations.py`, `tests/test_review_persistence.py`

**Interfaces:**
- Produces: `ValidationFailure` TypedDict = `{field, rule, reason, severity: Literal["error","warning"], policy_required: bool}`. `severity="error"` means the field's value is unusable as extracted (mandatory-missing, malformed ID, bad code lookup); `severity="warning"` means the value is present but should be double-checked (e.g. an arithmetic near-miss within rounding, from the domains that already distinguish this loosely by rule name). `policy_required=True` marks exactly the failures whose `_failure_to_question`/`question_templates` entry exists — i.e. this field replaces the previous implicit assumption that every failure triggers retrieval; going forward `retrieve_node` should skip failures with `policy_required=False` instead of running retrieval for all of them (a plain missing-required-field or arithmetic mismatch does not need a policy citation per the spec).

- [ ] **Step 1: Write the failing test**

```python
def test_validation_failures_carry_severity_and_policy_flag():
    from claimflow.domains.loan import _validate

    data = {
        "borrower_name": None,  # triggers a mandatory/required failure
    }
    failures = _validate(data)
    assert failures, "expected at least one failure from missing borrower_name"
    for f in failures:
        assert f["severity"] in ("error", "warning")
        assert isinstance(f["policy_required"], bool)
```

(Adapt the exact field name/trigger to whatever `loan.py`'s `_validate` actually requires to produce a failure — inspect `src/claimflow/domains/loan.py`'s `_validate` function first; use its real mandatory-field name.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_validate.py -k severity_and_policy_flag -v`
Expected: FAIL — `KeyError: 'severity'`

- [ ] **Step 3: Update the TypedDict**

```python
# src/claimflow/state.py
class ValidationFailure(TypedDict):
    field: str
    rule: str
    reason: str
    severity: Literal["error", "warning"]
    policy_required: bool
```

- [ ] **Step 4: Update every `_validate()` return site**

For each domain module, find every `ValidationFailure(field=..., rule=..., reason=...)` or equivalent dict-literal construction (`grep -n "rule=\|\"rule\":" src/claimflow/domains/health.py src/claimflow/domains/property.py src/claimflow/domains/loan.py`) and add the two new keys. Default `severity="error"` for mandatory/lookup/checksum failures (`mandatory`, `icd10_lookup`, `cpt_lookup`, `npi` format), `severity="warning"` for consistency/reconciliation checks that flag a discrepancy without proving the value is wrong (`arithmetic`, `income_consistency`, `acv_check`, `address_consistency`). Set `policy_required=True` exactly for the rules that have an entry in that domain's `question_templates` (from Task 3) or the field-name-based NPI special case; `policy_required=False` for everything else (plain `mandatory` missing-field, arithmetic-only checks with no policy angle). Example for one CMS-1500 site:

```python
ValidationFailure(
    field="billing_provider_npi",
    rule="mandatory",
    reason=f"{npi!r} does not look like a real NPI — treating as missing",
    severity="error",
    policy_required=True,   # NPI format has a question_template + field-name special case
)
```

- [ ] **Step 5: Update `db.py`**

Add columns to the table and the insert function:

```python
# src/claimflow/db.py, ValidationFailure class
class ValidationFailure(Base):
    __tablename__ = "validation_failures"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True
    )
    field: Mapped[str] = mapped_column(String)
    rule: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String, default="error")
    policy_required: Mapped[bool] = mapped_column(default=False)
    superseded: Mapped[bool] = mapped_column(default=False)
```

```python
# create_validation_failures
def create_validation_failures(
    session: Session, extraction_run_id: str, failures: list[dict]
) -> list[ValidationFailure]:
    rows = [
        ValidationFailure(
            extraction_run_id=extraction_run_id,
            field=f["field"],
            rule=f["rule"],
            reason=f["reason"],
            severity=f.get("severity", "error"),
            policy_required=f.get("policy_required", False),
        )
        for f in failures
    ]
    ...  # rest unchanged
```

- [ ] **Step 6: Write the Alembic migration**

```python
# alembic/versions/0006_validation_failure_severity.py
"""add severity and policy_required to validation_failures

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "validation_failures",
        sa.Column("severity", sa.String(), nullable=False, server_default="error"),
    )
    op.add_column(
        "validation_failures",
        sa.Column(
            "policy_required", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("validation_failures", "policy_required")
    op.drop_column("validation_failures", "severity")
```

(Confirm `down_revision` should be `"0005"` by checking `alembic/versions/0005_package_updated_at.py`'s own `revision =` value before writing this file — it must match exactly.)

- [ ] **Step 7: Update `ValidationFailureItem` and every construction site**

```python
# src/claimflow/schemas/review_write.py
class ValidationFailureItem(BaseModel):
    field: str
    rule: str
    reason: str
    severity: str
    policy_required: bool
```

Update every place `ValidationFailureItem(field=..., rule=..., reason=...)` is constructed in `api/main.py` (search `grep -n "ValidationFailureItem(" api/main.py`) to pass through `severity=f["severity"], policy_required=f["policy_required"]` (or `f.severity`/`f.policy_required` for ORM rows).

- [ ] **Step 8: Run migration and tests**

Run: `uv run alembic upgrade head && uv run pytest tests/test_migrations.py tests/test_validate.py tests/test_review_persistence.py tests/test_api.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/claimflow/state.py src/claimflow/domains/health.py src/claimflow/domains/property.py src/claimflow/domains/loan.py src/claimflow/db.py alembic/versions/0006_validation_failure_severity.py src/claimflow/schemas/review_write.py api/main.py tests/
git commit -m "feat: add severity and policy_required to validation failures"
```

---

### Task 6: Make policy retrieval conditional on `policy_required`, not "any failure exists"

**Files:**
- Modify: `src/claimflow/nodes/retrieve.py` (`retrieve_node`)
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: `ValidationFailure.policy_required` from Task 5.
- Produces: `retrieve_node` filters `failures` to `policy_required=True` ones before generating questions; if none qualify, returns `{"policy_answers": []}` without calling Qdrant at all (a plain missing-field or arithmetic-only failure set no longer triggers retrieval).

- [ ] **Step 1: Write the failing test**

```python
def test_retrieve_node_skips_policy_lookup_for_non_policy_failures(monkeypatch):
    from claimflow.nodes.retrieve import retrieve_node

    called = {"search": False}
    monkeypatch.setattr(
        "claimflow.nodes.retrieve._search",
        lambda *a, **k: called.update(search=True) or [],
    )
    state = {
        "domain": "loan",
        "validation_failures": [
            {
                "field": "loan_amount",
                "rule": "arithmetic",
                "reason": "totals do not match",
                "severity": "warning",
                "policy_required": False,
            }
        ],
    }
    result = retrieve_node(state)
    assert result == {"policy_answers": []}
    assert called["search"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_graph.py -k skips_policy_lookup_for_non_policy -v`
Expected: FAIL — current code calls `_search` for every failure regardless of a policy flag (the flag doesn't exist yet at the call site).

- [ ] **Step 3: Update `retrieve_node`**

```python
def retrieve_node(state: ClaimState) -> dict:
    failures = state.get("validation_failures") or []
    policy_failures = [f for f in failures if f.get("policy_required")]
    if not policy_failures:
        return {"policy_answers": []}

    domain_key = state.get("domain")
    answers: list[PolicyAnswer] = []
    seen: set[str] = set()
    for failure in policy_failures:
        question = _failure_to_question(failure, domain_key)
        if question in seen:
            continue
        seen.add(question)
        chunks = _search(question, domain_key)
        answers.append(
            _synthesize(question, chunks, domain_key=domain_key, failure=failure)
        )

    return {"policy_answers": answers}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_graph.py -k skips_policy_lookup_for_non_policy -v`
Expected: PASS

- [ ] **Step 5: Run the full graph test file**

Run: `uv run pytest tests/test_graph.py -v`
Expected: PASS — check `test_retrieve_node_skipped_when_no_failures` still passes (it should, unaffected) and update it if it hardcodes failure dicts without the new keys (add `"policy_required": True` to its fixture failures so it still exercises the "has failures, still retrieves" path it was meant to test).

- [ ] **Step 6: Commit**

```bash
git add src/claimflow/nodes/retrieve.py tests/test_graph.py
git commit -m "feat: skip policy retrieval for failures that don't depend on written guidance"
```

---

### Task 7: Rename routing labels (`approved/flagged/escalated` → `ready_for_processing/needs_review/blocked_or_incomplete`)

**Files:**
- Modify: `src/claimflow/state.py` (`ClaimState.decision` Literal)
- Modify: `src/claimflow/nodes/review.py` (`review_node`)
- Modify: `src/claimflow/schemas/enums.py` (`DecisionType`)
- Modify: `src/claimflow/db.py` (`Decision.decision` comment only — column stays `String`)
- Modify: `api/main.py` (`target_status = "completed" if decision.decision == "approved" else "review_ready"` and any other literal comparisons — search `grep -n '"approved"\|"flagged"\|"escalated"' api/main.py src/claimflow/*.py src/claimflow/**/*.py`)
- Modify: `alembic/versions/0007_rename_decision_labels.py` (new, data-only migration)
- Modify: `streamlit_app.py` (decision label rendering)
- Modify: `frontend/src/components/workspace/*.tsx` and `frontend/src/lib/api-types.ts` (wherever `DecisionType`/decision strings are rendered — grep first)
- Test: every test file currently asserting `"approved"`/`"flagged"`/`"escalated"` (search first: `grep -rln '"approved"\|"flagged"\|"escalated"' tests/`)

**Interfaces:**
- Produces: the only three valid decision values anywhere in the system become `"ready_for_processing"`, `"needs_review"`, `"blocked_or_incomplete"`. Mapping from old logic: old `"approved"` → `"ready_for_processing"`, old `"flagged"` → `"needs_review"`, old `"escalated"` → `"blocked_or_incomplete"`.

- [ ] **Step 1: Write the failing test**

```python
def test_review_node_uses_safe_routing_labels():
    from claimflow.nodes.review import review_node

    clean = {"extraction_overall_confidence": 0.95, "validation_failures": []}
    assert review_node(clean)["decision"] == "ready_for_processing"

    flagged = {
        "extraction_overall_confidence": 0.95,
        "validation_failures": [
            {"field": "x", "rule": "mandatory", "reason": "missing", "severity": "error", "policy_required": False}
        ],
    }
    assert review_node(flagged)["decision"] == "needs_review"

    low_confidence = {"extraction_overall_confidence": 0.1, "validation_failures": []}
    assert review_node(low_confidence)["decision"] == "blocked_or_incomplete"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_graph.py -k safe_routing_labels -v`
Expected: FAIL — `assert 'approved' == 'ready_for_processing'`

- [ ] **Step 3: Update `review_node`**

```python
# src/claimflow/nodes/review.py
from claimflow.config import settings
from claimflow.state import ClaimState


def review_node(state: ClaimState) -> dict:
    if state.get("error") or state.get("extraction_status") == "error":
        return {
            "decision": "blocked_or_incomplete",
            "review_reasons": [state.get("error", "extraction failed")],
        }

    confidence = state.get("extraction_overall_confidence") or 0.0
    failures = state.get("validation_failures") or []

    if confidence < settings.escalation_threshold:
        return {
            "decision": "blocked_or_incomplete",
            "review_reasons": [f"Overall confidence {confidence:.0%} below escalation threshold"],
        }

    reasons = [f"{f['field']}: {f['reason']}" for f in failures]

    if failures or confidence < settings.confidence_threshold:
        if confidence < settings.confidence_threshold:
            reasons.append(f"Overall confidence {confidence:.0%} below review threshold")
        return {"decision": "needs_review", "review_reasons": reasons}

    return {"decision": "ready_for_processing", "review_reasons": []}
```

- [ ] **Step 4: Update `state.py` and `enums.py`**

```python
# src/claimflow/state.py
decision: Literal["ready_for_processing", "needs_review", "blocked_or_incomplete"] | None
```

```python
# src/claimflow/schemas/enums.py
class DecisionType(str, Enum):
    READY_FOR_PROCESSING = "ready_for_processing"
    NEEDS_REVIEW = "needs_review"
    BLOCKED_OR_INCOMPLETE = "blocked_or_incomplete"
```

- [ ] **Step 5: Update `api/main.py`'s literal comparison**

```python
target_status = (
    "completed" if decision.decision == "ready_for_processing" else "review_ready"
)
```

Grep for any other `"approved"`/`"flagged"`/`"escalated"` string literal in `api/main.py` and update each one the same way.

- [ ] **Step 6: Write the data-migration Alembic revision**

```python
# alembic/versions/0007_rename_decision_labels.py
"""rename decision labels to safe routing vocabulary

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_RENAME = {
    "approved": "ready_for_processing",
    "flagged": "needs_review",
    "escalated": "blocked_or_incomplete",
}


def upgrade() -> None:
    conn = op.get_bind()
    decisions = sa.table("decisions", sa.column("decision", sa.String))
    for old, new in _RENAME.items():
        conn.execute(decisions.update().where(decisions.c.decision == old).values(decision=new))


def downgrade() -> None:
    conn = op.get_bind()
    decisions = sa.table("decisions", sa.column("decision", sa.String))
    for old, new in _RENAME.items():
        conn.execute(decisions.update().where(decisions.c.decision == new).values(decision=old))
```

- [ ] **Step 7: Update Streamlit and frontend label maps**

In `streamlit_app.py`, find the decision-color/label dict (grep `grep -n "approved\|flagged\|escalated" streamlit_app.py`) and update keys + add a human-readable label map:

```python
_DECISION_LABEL = {
    "ready_for_processing": "Ready for processing",
    "needs_review": "Needs manual review",
    "blocked_or_incomplete": "Blocked or incomplete",
}
```

In `frontend/`, grep for the same three old strings (`grep -rn "approved\|flagged\|escalated" frontend/src`) and update every rendering site plus `frontend/src/lib/api-types.ts` if it hand-declares the `DecisionType` union instead of importing it from a generated OpenAPI type (regenerate via whatever script the repo already uses if one exists — check `frontend/package.json` for a codegen script before hand-editing the generated file).

- [ ] **Step 8: Update every test asserting the old labels**

Run `grep -rln '"approved"\|"flagged"\|"escalated"' tests/` and replace each occurrence per the `_RENAME` mapping above. Expect hits at minimum in `test_graph.py`, `test_api.py`, `test_lifecycle.py`, `test_review_persistence.py`, `test_dashboard.py`, `conftest.py`.

- [ ] **Step 9: Run migration and full backend test suite**

Run: `uv run alembic upgrade head && uv run pytest tests/ -v`
Expected: PASS, 0 failures. This is the highest-regression-risk task in the plan — do not proceed to Task 8 until this is fully green.

- [ ] **Step 10: Commit**

```bash
git add src/claimflow/state.py src/claimflow/nodes/review.py src/claimflow/schemas/enums.py api/main.py alembic/versions/0007_rename_decision_labels.py streamlit_app.py frontend/ tests/
git commit -m "refactor: replace approved/flagged/escalated with safe routing recommendation labels"
```

---

### Task 8: Verify reviewer-correction revalidation/rerouting still works end to end with new labels

**Files:**
- Test only: `tests/test_lifecycle.py`, `tests/test_review_persistence.py`

**Interfaces:**
- Consumes: `POST /packages/{id}/validation/re-run` (unchanged endpoint, `api/main.py:870-950`) — already calls `review_node` as a pure function and persists a new `Decision` row; this task only re-verifies that flow under the new label vocabulary, since Task 7 already changed `review_node`'s output values.

- [ ] **Step 1: Run the existing full-lifecycle test**

Run: `uv run pytest tests/test_lifecycle.py -v`
Expected: PASS. This test (per the research pass) already exercises upload → process → validation failure → review → rerun → decision → audit → export → delete; if it references old decision strings anywhere in its assertions, Task 7 Step 8 should already have fixed it — if this fails, the fix belongs in Task 7, not here.

- [ ] **Step 2: Add one explicit regression test for decision-change detection under the new labels**

```python
def test_rerun_validation_reports_decision_changed_with_new_labels(client, tmp_path):
    # Adapt to this file's existing fixture/helper conventions (check test_lifecycle.py's
    # existing upload/process helper functions and reuse them rather than reimplementing).
    package_id = _upload_and_process_cms1500_with_missing_npi(client)  # use existing helper
    response = client.get(f"/packages/{package_id}/status")
    assert response.json()["status"] == "review_ready"

    rerun = client.post(
        f"/packages/{package_id}/validation/re-run",
        json={"corrected_fields": {"billing_provider_npi": "1234567893"}},
    )
    body = rerun.json()
    assert body["decision"] in ("ready_for_processing", "needs_review", "blocked_or_incomplete")
    assert isinstance(body["decision_changed"], bool)
```

- [ ] **Step 3: Run it**

Run: `uv run pytest tests/test_lifecycle.py -k decision_changed_with_new_labels -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_lifecycle.py
git commit -m "test: lock in reviewer-correction revalidation/rerouting under new decision labels"
```

---

### Task 9: Add read-only domain-pack inspector endpoints

**Files:**
- Create: `src/claimflow/schemas/domain_packs.py`
- Modify: `api/main.py`
- Test: `tests/test_api.py`, `tests/test_openapi_contract.py`

**Interfaces:**
- Produces: `GET /domain-packs` → `list[DomainPackSummary]` (`key`, `display_name`, `document_types` — the doc_type key itself plus its `supporting_types` keys), `GET /domain-packs/{key}` → `DomainPackDetail` adding `required_fields`/`optional_fields` (derived from the pack's `spec.model` Pydantic field `required`/not), `enabled_validators` (the distinct `rule` values the domain's `_validate` function is known to emit — since there's no registry of rule names, hardcode this as a `known_rules: list[str]` field the domain module already implicitly documents via its `question_templates` keys plus a manually-listed non-policy rule set per domain, OR — simpler and more honest — omit `enabled_validators` as a distinct list and instead return `reviewer_guidance` prose, which already exists from Task 2), `confidence_threshold`/`escalation_threshold` (falling back to global `settings` values), `policy_collection`, `retrieval_mode`.

- [ ] **Step 1: Write the failing test**

```python
def test_list_domain_packs_includes_cms1500(client):
    response = client.get("/domain-packs")
    assert response.status_code == 200
    keys = {pack["key"] for pack in response.json()}
    assert "cms1500" in keys


def test_get_domain_pack_detail_for_cms1500(client):
    response = client.get("/domain-packs/cms1500")
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "CMS-1500 Health Claim"
    assert body["retrieval_mode"] == "official_deterministic"
    assert "confidence_threshold" in body
    assert "required_fields" in body


def test_get_domain_pack_detail_404_for_unknown_key(client):
    response = client.get("/domain-packs/does_not_exist")
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py -k domain_pack -v`
Expected: FAIL — 404 on `/domain-packs` (route doesn't exist yet).

- [ ] **Step 3: Add the schema**

```python
# src/claimflow/schemas/domain_packs.py
from pydantic import BaseModel


class DomainPackSummary(BaseModel):
    key: str
    display_name: str
    document_types: list[str]


class DomainPackDetail(BaseModel):
    key: str
    display_name: str
    document_types: list[str]
    required_fields: list[str]
    optional_fields: list[str]
    confidence_threshold: float
    escalation_threshold: float
    policy_collection: str | None
    retrieval_mode: str
    reviewer_guidance: str
```

- [ ] **Step 4: Add the endpoints**

```python
# api/main.py — near the other GET endpoints, after imports add:
# from claimflow.domains.base import all_domains, get as get_domain
# from claimflow.schemas.domain_packs import DomainPackDetail, DomainPackSummary

@app.get(
    "/domain-packs",
    response_model=list[DomainPackSummary],
    tags=["domain-packs"],
    summary="List available domain packs",
)
def list_domain_packs():
    return [
        DomainPackSummary(
            key=d.doc_type,
            display_name=d.display_name or d.doc_type,
            document_types=[d.doc_type, *sorted(d.supporting_types.keys())],
        )
        for d in all_domains()
    ]


@app.get(
    "/domain-packs/{key}",
    response_model=DomainPackDetail,
    tags=["domain-packs"],
    summary="Inspect a single domain pack's configuration",
    responses=ERROR_RESPONSES,
)
def get_domain_pack(key: str):
    domain = get_domain(key)
    if domain is None:
        raise AppError(404, "DOMAIN_PACK_NOT_FOUND", f"No domain pack registered for {key!r}")
    model_fields = domain.spec.model.model_fields
    required = [name for name, f in model_fields.items() if f.is_required()]
    optional = [name for name, f in model_fields.items() if not f.is_required()]
    return DomainPackDetail(
        key=domain.doc_type,
        display_name=domain.display_name or domain.doc_type,
        document_types=[domain.doc_type, *sorted(domain.supporting_types.keys())],
        required_fields=required,
        optional_fields=optional,
        confidence_threshold=domain.confidence_threshold or settings.confidence_threshold,
        escalation_threshold=domain.escalation_threshold or settings.escalation_threshold,
        policy_collection=domain.policy_collection,
        retrieval_mode=domain.retrieval_mode,
        reviewer_guidance=domain.reviewer_guidance,
    )
```

(Confirm `domain.spec.model` is the actual attribute name on `SchemaSpec` holding the Pydantic model class — per the research pass it's `SchemaSpec.model: type[BaseModel]` in `doc_intel/schemas/base.py:59-68` — and that `model_fields` entries expose `.is_required()` in the installed Pydantic version; check with `uv run python -c "from pydantic import BaseModel; help(BaseModel.model_fields)"` if uncertain.)

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_api.py -k domain_pack -v`
Expected: PASS

- [ ] **Step 6: Update the OpenAPI contract test**

Run: `uv run pytest tests/test_openapi_contract.py -v` — it will fail because route count/schema changed; update its expected route list/count to include the two new endpoints (find the exact assertion it makes first with `grep -n "route" tests/test_openapi_contract.py`).

- [ ] **Step 7: Commit**

```bash
git add src/claimflow/schemas/domain_packs.py api/main.py tests/test_api.py tests/test_openapi_contract.py
git commit -m "feat: add read-only domain-pack inspector endpoints"
```

---

### Task 10: Frontend domain-pack inspector panel (read-only)

**Files:**
- Modify: `frontend/src/lib/api.ts` / `api-types.ts` (add `listDomainPacks`/`getDomainPack` client calls + types matching Task 9's response shapes)
- Modify: `frontend/src/app/settings/page.tsx` (or wherever the existing settings page lives per the research pass)
- Test: whichever Vitest file already covers the settings page (check `frontend/src/app/settings/` or `frontend/src/components` test directory for the existing pattern before adding a new one)

**Interfaces:**
- Consumes: `GET /domain-packs`, `GET /domain-packs/{key}` from Task 9.
- Produces: a read-only panel listing each domain pack's display name, document types, required/optional fields, thresholds, policy collection, and retrieval mode — no edit affordance, matching the spec's "read-only inspector, keep configuration file-based for now" fallback.

- [ ] **Step 1: Inspect the existing settings page and its test file**

Run: `cat frontend/src/app/settings/page.tsx` and find its existing test (e.g. `frontend/src/app/settings/page.test.tsx` or under `frontend/src/components/__tests__/`) to match its existing query/render conventions (TanStack Query hook naming, component structure) exactly — do not introduce a second data-fetching pattern alongside the one already used for `/settings`.

- [ ] **Step 2: Write the failing test** (adapt to the file's actual existing test structure — this is illustrative of intent, not literal)

```tsx
it("renders the CMS-1500 domain pack with its retrieval mode", async () => {
  server.use(
    http.get("/domain-packs", () =>
      HttpResponse.json([{ key: "cms1500", display_name: "CMS-1500 Health Claim", document_types: ["cms1500"] }])
    )
  );
  render(<SettingsPage />);
  expect(await screen.findByText("CMS-1500 Health Claim")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run --reporter=verbose -t "domain pack"`
Expected: FAIL — no such text rendered yet.

- [ ] **Step 4: Add the query hook and panel component**

Add a `useDomainPacks()` hook in `frontend/src/lib/queries.ts` following the exact pattern of whatever existing hook fetches `/settings` (same file, same conventions — read it first), and a `DomainPackPanel` component rendered from the settings page listing each pack's `display_name`, `document_types`, and (for the detail view, fetched on expand/click) `required_fields`, `confidence_threshold`, `retrieval_mode`, `reviewer_guidance` — plain read-only text/badges, no form inputs.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run --reporter=verbose -t "domain pack"`
Expected: PASS

- [ ] **Step 6: Run full frontend test suite + lint + build**

Run: `cd frontend && npx vitest run && npx eslint . && npx tsc --noEmit && npm run build`
Expected: all pass — README claims 28/28 tests, clean lint/TS, passing build prior to this change; this task must not regress any of those.

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "feat: add read-only domain-pack inspector panel to settings page"
```

---

### Task 11: Update `README.md` positioning and documentation

**Files:**
- Modify: `README.md`
- Modify: `TODO.md` (prune the stale pre-Next.js UI planning section, lines ~128-338 per the research pass — confirm the exact current line range before deleting)

**Interfaces:** none (documentation only).

- [ ] **Step 1: Rewrite the README's opening framing**

Replace the current opening paragraph with: "ClaimFlow is a configurable document-review and exception-routing system with a CMS-1500 reference implementation." Add sections (in this order, matching the spec's documentation checklist) covering: the customer problem; the stable seven-stage workflow (upload → classify → OCR/extract → structured extraction with evidence → deterministic validation → conditional policy retrieval → routing recommendation → human review/audit); the DomainPack concept (link to `src/claimflow/domains/base.py`'s `Domain` dataclass fields, explicitly naming it as the mechanism); what an administrator can inspect today via `GET /domain-packs` vs. what still requires code (new validators, new extraction hooks, new document types); why validation is deterministic (checksum/lookup/arithmetic don't need an LLM and must not silently hallucinate); when policy retrieval fires (`policy_required=True` failures only, never on a plain missing-field or arithmetic mismatch); how human review + revalidation work (`POST /packages/{id}/validation/re-run` recomputes both, per Task 6/7/8); the CMS-1500 demo flow (the exact 10 numbered steps from the "CMS-1500 reference implementation" section of the original request); evaluation methodology, explicitly distinguishing mocked-unit / local-integration / live-model layers (already true of the existing test suite + `eval/real_public`, per the research pass — just state it plainly); known limitations (carry forward the existing honest limitations list — nested-field UI gaps, non-canonical Xactimate/loan policy PDFs per PROGRESS.md Session N+8/N+9, ICD/CPT lookups not date-versioned, no HIPAA compliance, no auth/RBAC).

Do not claim CMS-1500 policy citations are legally authoritative beyond "cited from official CMS manuals" (already true and already the honest framing in the current README's `_cms_policy_answer` text) and do not claim the system makes final approval/coverage/lending/medical decisions anywhere in the new copy — routing labels are recommendations, say so explicitly in the Routing section.

- [ ] **Step 2: Prune `TODO.md`**

Read the current file in full first. Delete the section describing building the product UI from scratch (it predates the shipped Next.js app and contains at least one factually wrong current-state claim — "preserve current `POST /claims`" when the real route is `POST /packages`, per the research pass). Keep the "Backend completion — DONE" section and any still-open items (e.g. the unverified live health-evidence-accuracy root cause). Add one new line noting this refactor's completion date and scope.

- [ ] **Step 3: Commit**

```bash
git add README.md TODO.md
git commit -m "docs: reposition ClaimFlow as a configurable domain-pack system, prune stale UI-build TODO"
```

---

### Task 12: Full-suite verification pass

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend test suite**

Run: `uv run pytest tests/ -v`
Expected: PASS, 0 failures, 0 unexpected skips.

- [ ] **Step 2: Run lint**

Run: `uv run ruff check src tests && uv run ruff format --check src tests`
Expected: clean.

- [ ] **Step 3: Run the frontend suite**

Run: `cd frontend && npx vitest run && npx eslint . && npx tsc --noEmit`
Expected: clean, matching README's pre-existing 28/28 baseline (now possibly 29+ with Task 10's new test).

- [ ] **Step 4: Confirm no remaining domain-literal branches**

Run: `grep -rn 'domain_key ==' src/claimflow/nodes/`
Expected: no matches (all replaced by DomainPack lookups in Tasks 3-4; the one narrow documented EOB-hook-signature exception from Task 4 Step 3 uses `if domain_key == "eob":` — confirm that is the *only* remaining hit and it's the one explicitly justified in that task).

- [ ] **Step 5: Confirm no remaining old decision labels**

Run: `grep -rn '"approved"\|"flagged"\|"escalated"' src/ api/ streamlit_app.py frontend/src/`
Expected: no matches outside the Alembic migration file itself (which legitimately references the old strings as migration source values).

- [ ] **Step 6: Live smoke test against the real CMS-1500 sample**

Run the exact e2e sequence used earlier in this session (Qdrant up, migrations, API up, upload `CMS1500-1-791x1024.png`, poll status, fetch `/packages/{id}/review`) and confirm: `decision` is one of the three new labels, `insurance_id` is still correctly nulled (the earlier bug fix in `extract.py`'s `_correct_cms1500_result` must survive Task 4's refactor — that function is untouched by this plan, only `extract_node`'s dispatch changes), and `GET /domain-packs/cms1500` returns a 200 with `retrieval_mode: "official_deterministic"`.
