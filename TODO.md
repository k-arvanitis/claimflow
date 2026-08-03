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

No authentication or authorization anywhere — the FastAPI API and the
frontend are both open. Needed before any real deployment: user accounts, role
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

## Health source-evidence accuracy — measured (2026-08-02), was 85%, now 92.6%

A full clean `make eval` run (post the extraction/evidence fixes below)
measured this directly rather than hypothesizing: 92.6% for health vs.
95.5–98.9% for property/loan. The gap is real but smaller than the old
~85% estimate suggested — CMS-1500's dense form layout (values split across
adjacent sub-boxes, e.g. date of birth as separate MM/DD/YY cells) still
plausibly explains the residual gap, but this is no longer unverified.

## Domain-pack refactor — DONE (2026-07-27)

DomainPack fields (`retrieval_mode`, `question_templates`, per-domain
thresholds, `reviewer_guidance`), `policy_required`-gated retrieval, the
`ready_for_processing`/`needs_review`/`blocked_or_incomplete` routing rename,
and read-only `GET /domain-packs` inspection endpoints are implemented and
merged. Frontend inspector panel (originally planned) was skipped by request
— no admin UI exists for domain packs yet, inspection is API-only. Editing a
domain pack still means editing the Python module that registers it; no
schema editor or rule-language interpreter was added, by design.

## Workflow authority, decision-model split, BYOK LLM settings — DONE (2026-07-27, uncommitted)

Selected workflow is now authoritative end-to-end (`POST /packages` `domain`
form field, `ingest_node` never overwrites a caller-supplied domain,
reprocess carries it forward, mismatch is a warning not a silent override).
`decisions` rows now distinguish system recommendation from reviewer outcome
(`source`/`is_override` columns, migration `0009`) and both are surfaced
separately in the queue, dashboard, and workspace overview. Policy answers
are now linked to the validation finding they support (`field`/`rule`,
migration `0008`). New BYOK Settings card (Groq/OpenRouter/OpenAI + model,
`src/claimflow/llm_credentials.py`). Also fixed live: a Xactimate arithmetic
false-positive, a stale-panel-after-processing frontend bug, black-on-black
warning-tone text in three places, and Fields/Validation tab layouts that
required horizontal scrolling. See PROGRESS.md Session N+11 for full detail.
**Nothing from this is committed to git yet.**

## Per-document extraction for multi-document packages — DONE (2026-08-03)

Every document in a package with its own registered domain pack now gets its own
extraction and validation, not just the one matching the package's primary
domain (`extract_node`/`validate_node` in `src/claimflow/nodes/`, new
`secondary_extractions` state key — additive, rides in the existing
`result_json` blob, no DB migration). `document-list.tsx`'s badge now reflects
this (`extractedDocTypes` — primary + every non-error secondary doc_type).
Verified live: a real 2-document package (CMS-1500 + EOB) produced independent
extraction for both, real OpenAI call, EOB validated cleanly against its own
schema. 266 tests pass (5 new).

**Not covered — cross-document reconciliation.** Each document's extraction is
validated independently; nothing compares one document's values against
another's (e.g. does the EOB's `plan_paid`/`patient_responsibility` match the
CMS-1500's billed amount and diagnosis codes). This is the part of "multi-document
processing" that's actually differentiating for a buyer — extraction alone is
"more JSON," reconciliation is what catches real discrepancies. Would need:
a cross-doc validator keyed on domain pairs (e.g. cms1500+eob), run after both
extractions complete, producing its own tagged `ValidationFailure` entries.
Not built. Structured per-document audit trail is also not extended —
`persist_extraction_result`/`extracted_fields` table stays primary-doc-only;
secondary results are only in the JSON blob, not individually queryable.

## PaddleOCR-VL never actually worked — FIXED (2026-08-03)

Root cause, not flaky infra: `pyproject.toml` requested doc-intel's `[ocr]`
extra (`unstructured[pdf]`, unrelated to PaddleOCR-VL) instead of
`[paddleocr]` (the actual `paddleocr`/`paddlepaddle`/`paddlex` client
package). This means every image-classification/extraction call silently
fell to the tesseract fallback on every machine that ever ran this repo,
not just this session's box — "PaddleOCR-VL backend is selected but the
PaddleOCR-VL package is not available" was always the real error, just
never diagnosed as a wrong-extra bug before.

Fixed: `doc-intel[ocr,paddleocr]`, new
`CLAIMFLOW_DOC_INTEL_PADDLEOCR_VL_SERVER_URL` setting wired through the
same passthrough pattern as the other `DOC_INTEL_*` config in
`nodes/extract.py`. Verified live: a CMS-1500 sample image that previously
failed classification now classifies correctly with zero manual override.
The GPU-served container (doc-intel's `make paddleocr-vllm-up`) is not
running by default — bring it up before relying on PaddleOCR-VL locally;
it reserves ~22GB via vLLM's utilization ceiling regardless of the model
being small, so don't leave it running unattended on a shared GPU.

## EOB multi-claim extraction — column/totals mapping is nondeterministic

The claims-list schema change (2026-08-02) fixed claim-boundary detection — the
LLM no longer mixes values across separate claims on one EOB page. What's still
unreliable: which of two valid-looking totals rows it pulls `plan_paid` /
`patient_responsibility` from when a claim has both a top-of-page summary strip
and its own line-item "Column Totals" row — two runs on the same file produced
different (both plausible) values. Prompt tuning narrowed but didn't kill this.
Real fix: a deterministic regex/table-parsing correction pass on the claim's
Column Totals row, same pattern as CMS-1500's `_correct_cms1500_result` in
`src/claimflow/nodes/extract.py` — not built, would need real EOB template
samples to generalize beyond the 2 test documents this was diagnosed against.

## Row-level evidence is per-row, not per-field-within-row

For `list[Model]` schema fields (`service_lines`, `claims`), doc-intel computes
ONE evidence match per row by concatenating all the row's field values into a
single fuzzy-match string — there's no per-field bbox inside a row. On a row
with several distinct dollar amounts spread across a wide table, the combined
string often only partially matches one OCR block (e.g. just the provider name),
so the highlight can look unrelated to whatever field you're actually
inspecting, or come back null entirely. This is doc-intel's row-scoring design
(`src/doc_intel/confidence.py`'s `score()`), not a bug — flagging as a possible
future improvement (per-field-within-row evidence lookup) if it matters enough
to justify the added matching complexity.

## Qdrant policy collection repeatedly emptying itself — FIXED (2026-08-02)

Root-caused, not external: `policy_index.reindex()` deleted the live
`claimflow_policies` collection first, then rebuilt it in place. Confirmed
directly in the Qdrant container's own request log — `DELETE
/collections/claimflow_policies` followed by nothing, no rebuild, 4 of the
last 5 times it ran. Anything failing between delete and rebuild (an
embedding-model fetch hiccup, any exception) left the collection permanently
empty until the next successful run.

Fixed by building the replacement under a fresh physical collection name
first, then atomically repointing `claimflow_policies` — now a Qdrant alias,
not a real collection — to it via `update_collection_aliases`, only once the
build is confirmed complete. The real collection is never gone with nothing
ready to replace it. Verified live: ran `reindex()` twice in a row against
the real corpus (579 chunks, 5 PDFs), confirmed the alias swap and old-
generation cleanup both work, confirmed a real retrieval query resolves
through the alias exactly like a normal collection name (`retrieve.py`
needed no changes). Regression test added in `test_policy_index.py`
asserting the build happens before the old collection is ever deleted.

## Still open after Session N+11

- **Commit the session's work.** Large uncommitted diff across backend,
  frontend, migrations, tests — needs to land before anything else builds on
  top of it.
- **Confidence-signal exposure in the UI.** The Fields tab shows a single
  confidence percentage; the underlying grounding/validation/presence signal
  breakdown (doc-intel's `confidence.py`) is not surfaced per-field. Real
  data exists (`grounded`, `valid`, `field_status`, `evidence.grounding_score`
  when present) but there's no popover/tooltip exposing it — verify
  `grounding_score` is actually populated before building UI around it, per
  the earlier live check where CMS-1500 evidence bboxes came back null on
  some fields.
- **No recommendation-version tracking.** A reviewer override records
  `is_override` and the reason, but not which specific system-recommendation
  run it responded to (no `responds_to_decision_id`/version link). Fine for
  a single-recommendation-per-run model; would matter if a package can be
  reprocessed and reviewed against a stale recommendation.
- **Dashboard "Recently processed packages" dropped its Confidence column**
  to fit the new System rec./Reviewer outcome split without horizontal
  overflow. Confidence is one click away (package workspace) but no longer
  visible at a glance from the dashboard.
- **Mismatch UX is warn-only, not reprocess-assisted.** When a selected
  workflow doesn't match the detected domain, the user sees a warning and
  must manually create a new package under the correct workflow — there's no
  in-place "reprocess under a different workflow" action yet.
- **Extraction misassignment spot-check was a one-time manual sample.** One
  real CMS-1500 misassignment (adjacent-box value copied at high confidence)
  was found and did not reproduce on 2 more samples — treated as inherent
  LLM noise in the doc-intel dependency, not chased further. No systematic
  eval added to catch this failure class going forward.
