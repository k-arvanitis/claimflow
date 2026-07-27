# TODO

## Backend completion — DONE (2026-07-13)

All 10 items below are implemented and merged to main. Plans for each are in
`docs/superpowers/plans/2026-07-12-*.md` and `docs/superpowers/plans/2026-07-13-*.md`.
Backend was ready for Next.js UI work, which has since shipped (see
`frontend/`, README's Product UI section). Not touched: real reviewer
auth/RBAC, object storage, Celery/Redis (all explicitly deferred).

## Backend completion — must finish before calling backend complete

1. Freeze and document the API contract — Pydantic req/resp models everywhere,
   standard error shape `{error:{code,message,details}}`, ISO 8601 timestamps,
   consistent ID types, explicit nullable fields, shared enums (status,
   decision, review action, document type), OpenAPI matches every response,
   frontend can generate/maintain a typed client.

2. Add DB migrations + integrity constraints — Alembic migrations, FK
   enforcement, indexes (package status, created date, reviewer state, doc
   package ID), uniqueness constraints, verified delete cascades, intentional
   package-delete-vs-audit-events behavior, clean DB init command. No
   startup-only auto-create-tables.

3. Harden the processing state machine — `POST /packages/{id}/process`
   reliable + idempotent. States: uploaded → queued → processing →
   review_ready → completed; failures: processing_error, validation_error,
   retrieval_error. No concurrent runs per package, retry on error, no
   duplicate fields/failures/evidence on reprocess, store extraction-run
   version, recover stale processing after restart, preserve prior results,
   log every transition to audit. Local background executor OK (document
   limits), no Celery/Redis needed.

4. Verify review persistence semantics — keep machine value, reviewer
   correction, final approved value distinct; review action never overwrites
   machine extraction. Per field: original value/confidence/evidence,
   reviewer action, corrected value, reviewer note, reviewer identity,
   timestamp, extraction version. Revalidation uses corrected values,
   persists new result, retains old failures for audit, records whether
   decision changed. No duplicate review actions on repeat requests.

5. Finalize the evidence contract + nested field identity — evidence
   response: field_id, document_id, filename, page, quote, bbox,
   coordinate_system, block_type. Consistent page numbering, bbox matches
   rendered page endpoint, invalid bbox rejected/clamped, missing geometry →
   bbox null, exact stored quote returned, evidence stays correct after
   reprocess version bump. Nested rows (service-line/diagnosis-code/line-item):
   stable row IDs, independent review actions per row, separate
   original/corrected row values, row-specific evidence where possible,
   explicit `evidence_unavailable` otherwise.

6. Add server-side filtering + pagination — list endpoints support page,
   page_size, status, domain, decision, sort, search. `GET /reviews/queue`
   supports status, domain, decision, confidence range, validation rule,
   assigned reviewer, date range, sort, pagination. Return
   `{items, page, page_size, total}`.

7. Add `GET /dashboard/summary` — total_packages, processing,
   awaiting_review, approved, flagged, escalated, processing_errors,
   straight_through_rate, top_validation_failures. Only metrics derivable
   from stored package data now.

8. Harden upload + storage handling — filename sanitization, path-traversal
   prevention, MIME/extension checks, max file size, max package file count,
   unique internal storage names, cleanup on package delete, no raw fs paths
   exposed, no orphaned records on failed upload, safe DOCX conversion
   timeouts, rendered pages scoped to own package, temp file cleanup. Local
   fs storage OK for portfolio.

9. Add full lifecycle integration tests — main flow: upload → process →
   classified docs → extracted fields+evidence → validation failure → review
   queue → edit field → rerun validation → decision → audit history → export
   → delete. Also: processing failure+retry, duplicate /process calls,
   classification override+reprocess, nested/list field review, invalid
   field/package/document IDs, evidence page/bbox rendering, package
   deletion, persistence across restart, concurrent review update conflict,
   missing Qdrant/LLM provider, export before/after review. Mock
   DocIntel/LLM/Qdrant in CI, one optional real-stack smoke test outside
   default suite.

10. Fix README audit-logging language — clarify "No PHI-specific access
    control, audit logging..." vs documented persisted audit events /
    `GET /packages/{id}/audit`. State ClaimFlow has application-level
    workflow audit events but not compliance-grade tamper-evident audit
    logging or PHI-specific access auditing. Under production hardening,
    replace "audit logs" with "compliance-grade immutable audit logging,
    access-event capture and retention controls".

Deferred production-hardening items — deliberately out of scope for the
current work, not forgotten.

## Auth / RBAC

No authentication or authorization anywhere — the FastAPI API and Streamlit
UI are both open. Needed before any real deployment: user accounts, role
separation (reviewer vs admin), and auth on `/packages` endpoints.

## VLM path (signature / checkbox / photo verification)

Extraction is text-grounded only (doc-intel scores confidence against
extracted text/OCR, not pixels). Fields like signatures, checkbox
states, and damage photos need a vision-capable model to verify visually
rather than just parse text near them. Not implemented; `damage_photo` is
currently classification-only (see `src/claimflow/domains/property.py`).

## Secure storage / encryption at rest

Uploaded files and the SQLite DB (`data/uploads/`, `data/claimflow.db` —
see `src/claimflow/config.py`) are plain, unencrypted local disk. Needed:
encryption at rest, a retention/deletion policy for PII-bearing documents
(patient names, SSNs, account numbers), and probably a move off local disk
to object storage with access controls.

## Health source-evidence accuracy (~85%) — root cause unverified live

Code-level read of doc-intel's evidence matcher (`find_evidence`/
`text_grounding` in `confidence.py`, plus `inputs/pdf.py`'s table-skip
fallback) points at CMS-1500's dense form layout: after the outer form-grid
table is skipped (>80% page area), fitz's font/paragraph-based block
clustering isn't cell-grid-aware, so there's no structural signal
separating a field's label from its value slot. Plausible, matches the
existing README hypothesis, but never confirmed against a live extraction
run — attempted twice, vLLM (Qwen3-32B-AWQ on :8005) OOM'd both times and a
root-owned LightOnOCR process kept auto-respawning and competing for
GPU/disk. Needs: get vLLM stable, capture real `extraction_fields` with
`evidence=null` for a few health packages, inspect actual failed matches.

## Domain-pack refactor — DONE (2026-07-27)

DomainPack fields (`retrieval_mode`, `question_templates`, per-domain
thresholds, `reviewer_guidance`), `policy_required`-gated retrieval, the
`ready_for_processing`/`needs_review`/`blocked_or_incomplete` routing rename,
and read-only `GET /domain-packs` inspection endpoints are implemented and
merged. Frontend inspector panel (originally planned) was skipped by request
— no admin UI exists for domain packs yet, inspection is API-only. Editing a
domain pack still means editing the Python module that registers it; no
schema editor or rule-language interpreter was added, by design.
