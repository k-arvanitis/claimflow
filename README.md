# ClaimFlow

A production-style document-intelligence and validation pipeline for messy, multi-document claim packages. It ingests a folder of PDFs (born-digital or scanned), OCRs pages with no text layer, extracts structured fields with confidence and source evidence, validates the result against deterministic domain rules, and routes each package to an `approved`, `flagged`, or `escalated` decision. Human review is triggered by validation failures, low-confidence or conflicting extractions, and configured high-risk conditions.

For any field that fails validation, ClaimFlow also retrieves cited policy passages to support the reviewer's decision — a secondary step, not the point of the pipeline.

Unlike a plain "PDF to JSON" extractor, ClaimFlow is built for workflows where extracted values have to be auditable and safe to act on downstream — not just plausible-looking.

Supports three claim domains out of the box: **CMS-1500 health**, **Xactimate property damage**, and **SBA loan applications**.

**Supported inputs:** born-digital PDFs, scanned/image-only PDFs (OCR fallback via [doc-intel](../doc-intel), tesseract by default), standalone images (PNG/JPG/WEBP/TIFF/BMP), DOCX (converted to PDF via LibreOffice so it goes through the same page-based pipeline as everything else), and multi-document packages mixing any of these.

![Architecture](assets/architecture.svg)

## Best fit

ClaimFlow is best suited for:

- OCR + structured extraction from claim/application packages
- deterministic validation of extracted values
- human-in-the-loop review workflows
- claim/application triage: approved / flagged / escalated
- cited policy support for failed validation rules

It is not a production HIPAA/compliance system as-is.

## Pipeline

| Node | Type | What it does |
|------|------|--------------|
| Ingest | Deterministic | Reads PDFs, images, and DOCX from the package directory; text-layer detection and OCR fallback via [doc-intel](../doc-intel)'s `build_artifact()`; classifies every document by type |
| Extract | LLM | Structured field extraction via [doc-intel](../doc-intel); confidence + source evidence per field |
| Validate | Deterministic | Domain-specific rule checks (arithmetic, lookup tables, date windows) |
| Retrieve | Hybrid / LLM-assisted | Qdrant vector search + cross-encoder rerank (deterministic) + LLM synthesis (generative) for each failing rule |
| Review | Deterministic | Confidence + failure thresholds → routing decision; human review is triggered by validation failures, low-confidence or conflicting extractions, and configured high-risk conditions |

The Retrieve node is skipped when Validate finds no failures.

## Document classification

Every document in a package is classified, not just the primary claim form — a package is treated as messy by default. Classification is deterministic keyword matching (same mechanism used to detect a package's domain), so it's fast and has no LLM cost.

**Deep extraction** means a document type has its own schema, field-level confidence/evidence, and deterministic validator. **Classification-only** means the document is recognized and routed for manual triage — no structured extraction is attempted.

| Domain | Deep extraction | Classification-only |
|--------|-----------------|----------------------|
| Health | `cms1500`, `eob`, `medicare_summary_notice` | `medical_bill`, `insurance_policy`, `denial_letter`, `clinical_note`, `lab_report`, `discharge_summary`, `referral_letter`, `prior_authorization_letter`, `eligibility_benefits_verification`, `ub04_cms1450`¹ |
| Property | `xactimate`, `declarations_page` | `loss_report`, `contractor_invoice`, `adjuster_notes`, `roof_inspection_report`, `damage_photo`², `material_receipt`, `fire_report`, `police_report` |
| Loan | `loan`, `sba_form_413`, `sba_form_2202` | `tax_return`, `bank_statement`, `balance_sheet`, `income_statement`, `id_document`, `supporting_exhibit`, `profit_loss_statement`, `debt_schedule`, `business_license`, `articles_of_incorporation`, `payroll_report`, `w2_1099_paystub` |

¹ UB-04/CMS-1450 is classified but not deep-extracted — production-grade support needs licensed NUBC/AHA data specs, not shipped here.
² Damage photos are classified but not reasoned about — real damage assessment needs a vision-language model, not implemented yet (tracked as a TODO, not claimed as working).

Anything that matches no known pattern is labeled `unknown` rather than silently dropped, so it's still visible for manual triage.

Classification is deterministic keyword matching, so every result carries a **reason** (which keyword matched, and for which type) — surfaced via `GET /packages/{package_id}/documents`. A reviewer can override a misclassified document with `POST /packages/{package_id}/documents/{document_id}/reclassify`, then `POST /packages/{package_id}/process` to reprocess it — the new type's schema and validators run on the next pass, and the package's detected domain is re-derived from the overridden classification.

## Source evidence

Every extracted field carries where it came from, not just its value:

```json
{
  "name": "patient_name",
  "value": "John Smith",
  "confidence": 0.91,
  "grounded": true,
  "evidence": {
    "page": 1,
    "text": "Patient's Name: John Smith",
    "bbox": [120.0, 244.0, 310.0, 260.0],
    "block_type": "paragraph"
  },
  "field_status": "found"
}
```

`bbox` is populated for born-digital pages (from PDF layout) and for most OCR'd pages (from OCR element coordinates); it's `null` when a page has no recoverable coordinates. The Streamlit review UI renders the source page with the evidence region highlighted, so a reviewer can check a value against the original document without opening the PDF separately.

## OCR proof

Scanned pages don't get a black-box "trust the model" treatment:

- **Side-by-side page viewer** — the review UI renders the original page image next to its extracted text (native text layer, or on-demand OCR for scanned pages), with page navigation and a "jump to this field's evidence" shortcut.
- **Low-quality scan detection** — a density heuristic (extracted characters vs. a normal text page) flags likely-failed scans. It is not a real per-word OCR confidence score — doc-intel's OCR backends don't expose one — so it's surfaced as a detection signal, not a confidence metric.
- **OCR fallback log** — every page that triggers OCR (no text layer) is logged, with a distinct low-quality-scan warning when OCR yields very little text.

## Human review queue

The Streamlit UI is a functional review prototype used to validate workflow behavior, not a read-only report — the product interface is being implemented separately in Next.js:

- Per-field **approve / edit / reject**, with an editable corrected value
- **Nested/list fields are editable tables** — `diagnosis_codes`, `service_lines`, `line_items` (and any future table-like field) support adding, editing, and deleting rows, not just read-only display
- **Suggested correction** — surfaces the deterministic validator's own failure reason next to the field it flagged (e.g. "line sum $412.00 does not match total charge $450.00")
- **Re-run validation** — after edits, re-runs the domain's real deterministic validator against the reviewer's corrected values, not a reimplementation
- **Export** — reviewed fields, scalar and nested/list alike (original value, action taken, final value, confidence) download as JSON, ready for downstream handoff

## Validation rules

Deterministic, not LLM self-verification — the same numbers, codes, and dates get the same result every run.

| Domain | Example checks |
|--------|----------------|
| Health (CMS-1500) | missing mandatory field, malformed NPI (not exactly 10 digits), invalid ICD-10 code, invalid CPT code, service-line total ≠ claimed total, future date of service |
| Health (EOB / MSN) | provider charges ≥ allowed charges, non-negative amounts, `is_bill` must be False (an EOB/MSN is informational by design), placeholder-pattern claim number, future service date |
| Property (Xactimate) | missing mandatory field, line-item sum ≠ replacement cost total, ACV/RCV inconsistency, date of loss outside policy window, negative dollar amounts |
| Property (declarations page) | policy period start ≤ end, non-negative coverage limits/deductibles/premium, placeholder-pattern policy number |
| Loan (SBA application) | missing mandatory field, placeholder-pattern tax ID, business name where a person's name is expected, non-positive loan amount, net income exceeds gross revenue, missing signature |
| Loan (SBA Form 413) | total assets − total liabilities = net worth (within tolerance), non-negative amounts, future as-of date, business name where a person's name is expected |
| Loan (SBA Form 2202) | sum of current balances = reported total, current balance ≤ original amount (unless revolving/deferred), maturity date ≥ origination date |

## Example: one package end to end

A real run against `data/synthetic/health/package_004` (one input file, `claim.pdf` — a born-digital CMS-1500 form with a genuinely invalid injected diagnosis code):

**1. Classified documents**

| File | Classified as | Text layer |
|------|---------------|------------|
| `claim.pdf` | `cms1500` | born-digital |

**2. Extracted fields** (excerpt, with source evidence)

```json
{
  "name": "patient_name",
  "value": "TAYLOR MICHAEL",
  "confidence": 1.0,
  "grounded": true,
  "field_status": "found",
  "evidence": { "page": 1, "block_type": "paragraph", "bbox": [19.84, 83.09, 89.63, 94.08] }
}
```

**3. Validation failures**

```json
[{ "field": "diagnosis_codes", "rule": "icd10_lookup", "reason": "'XXXXX' is not a recognized ICD-10-CM code" }]
```

**4. Final decision**

```
decision: flagged
review_reasons:
  - "diagnosis_codes: 'XXXXX' is not a recognized ICD-10-CM code"
```

**5. Reviewer export** (after approving the scalar fields in the Streamlit review queue)

```json
{
  "decision": "flagged",
  "domain": "cms1500",
  "fields": {
    "patient_name": { "original_value": "TAYLOR MICHAEL", "action": "approve", "final_value": "TAYLOR MICHAEL", "confidence": 1.0 },
    "total_charge": { "original_value": 121.0, "action": "approve", "final_value": 121.0, "confidence": 1.0 }
  }
}
```

`diagnosis_codes` (the field the validator actually flagged) is a list, not a scalar — the review UI renders it as an editable table (add/edit/delete rows), and the export includes per-row action, original/final value, confidence, and evidence, same as scalar fields.

## Setup

```bash
# 1. Clone and install
git clone <repo>
cd claimflow
uv sync

# 2. Configure
cp .env.example .env
# edit .env — set ANTHROPIC_API_KEY at minimum

# 3. Start Qdrant
make docker-up

# 4. Generate and seed policy documents
uv run python scripts/generate_policies.py
make seed

# 5. (Optional) Generate synthetic claim packages for eval
make generate

# 6. Start the API
make api
# or the Streamlit UI:
make ui
```

## Commands

| Command | Description |
|---------|-------------|
| `make api` | Start FastAPI on port 8010 |
| `make ui` | Start Streamlit review UI on port 8011 |
| `make test` | Run test suite |
| `make lint` | ruff check + format check |
| `make eval` | Run 3-domain eval against `data/synthetic/` |
| `make docker-up` | Start Qdrant |
| `make docker-down` | Stop Qdrant |
| `make seed` | Index policy PDFs into Qdrant |
| `make generate` | Generate synthetic claim packages |

## API

### Packages
```
POST   /packages                         Upload one or more files, returns {package_id, status}; processing runs in the background
GET    /packages                        List all packages (id, status, created_at)
GET    /packages/{package_id}            Full package detail (status, decision, extracted fields, validation failures, error)
DELETE /packages/{package_id}            Delete a package (cascades to its documents/fields/failures/evidence/decisions; keeps its audit trail)
POST   /packages/{package_id}/process    (Re)trigger processing on an existing package
GET    /packages/{package_id}/status     Lightweight status poll (package_id, status only)
```

### Documents and evidence
```
GET  /packages/{package_id}/documents                                     List documents in a package (includes doc_type, classification_reason, manually_overridden)
GET  /packages/{package_id}/documents/{document_id}                        One document's detail
GET  /packages/{package_id}/documents/{document_id}/pages/{page}           PNG render of one page (optional ?bbox=x0,y0,x1,y1 to highlight evidence)
POST /packages/{package_id}/documents/{document_id}/reclassify              Override a document's classified type; call POST .../process afterward to reprocess with it
GET  /packages/{package_id}/fields/{field_id}/evidence                     Source evidence for one extracted field
```

### Review
```
GET  /reviews/queue                                    Packages currently flagged or escalated, across the whole system
GET  /packages/{package_id}/review                     Fields + validation failures for one package's review
POST /packages/{package_id}/fields/{field_id}/review    Submit a reviewer action (approve/edit/reject) for one field
POST /packages/{package_id}/validation/re-run           Re-run the domain's real validator against corrected field values
POST /packages/{package_id}/decision                    Record a final decision (approved/flagged/escalated)
```

### Policy support and audit
```
GET /packages/{package_id}/policy-evidence    Cited policy answers for the package's failed validation rules
GET /packages/{package_id}/audit               Audit log (upload, extract, validate, review_edit, decision events)
GET /packages/{package_id}/export               Full package export (decision, fields, failures, policy answers)
```

Example:
```bash
curl -X POST http://localhost:8010/packages \
  -F "files=@data/synthetic/health/package_001/claim.pdf"
```

## Configuration

All settings are in `src/claimflow/config.py` and read from `.env`. See `.env.example` for the full list.

Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Required for LLM extraction and retrieval |
| `DOC_INTEL_PROVIDER` | `anthropic` | Use `openai` + `DOC_INTEL_LLM_BASE_URL` for local vLLM |
| `DOC_INTEL_TEMPERATURE` | `0.0` | Extraction defaults to greedy decoding for reproducibility, not creativity |
| `QDRANT_URL` | `http://localhost:6339` | Qdrant endpoint |
| `CONFIDENCE_THRESHOLD` | `0.75` | Below this → flagged |
| `ESCALATION_THRESHOLD` | `0.50` | Below this → escalated |
| `LANGFUSE_ENABLED` | `false` | Set `true` to enable tracing |

## Eval

Run the full 3-domain evaluation (requires a model up):

```bash
make eval
# or with a specific domain:
uv run python scripts/run_eval.py --domain health
```

Results are written to `output/eval_results.json`. Model: `qwen3-32b`, self-hosted via vLLM (AWQ-quantized), `max_num_seqs=1`.

| Domain | Packages | Field accuracy | Validation catch rate | False positive rate | Source evidence accuracy | Straight-through |
|--------|---------|---------------|------------------------|----------------------|---------------------------|-------------------|
| Health (CMS-1500) | 30 | ~92% | ~81.5% | 0.0% | ~85% | ~40-43% |
| Property (Xactimate) | 30 | 98.1% | 100.0% | 0.0% | 100.0% | 40.0% |
| Loan (SBA) | 30 | 96.7% | 100.0% | 0.0% | 93.8% | 30.0% |

Field accuracy by type (date / code / currency / text) and the scanned-vs-born-digital split are in `output/eval_results.json` — all synthetic packages in this run were born-digital, so that split isn't informative yet.

The eval process surfaced several real pipeline issues — schema nullability, placeholder-pattern fabrication, retired ICD-10 codes in the synthetic generator, evidence-box grounding, and model nondeterminism at temperature 0. The fixes and root-cause notes are documented in [`docs/eval-notes.md`](docs/eval-notes.md).

## Real/Public Evaluation

The synthetic eval above remains the controlled, end-to-end benchmark — it's the one with gold-labeled injected errors and known ground truth. `eval/real_public/` adds a second, additional layer: domain-specific validation and extraction tested against real, publicly available data, to prove the pipeline holds up beyond synthetic packages.

- **[CMS SynPUF](https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files), [CDC/CMS ICD-10-CM](https://www.cdc.gov/nchs/icd/icd-10-cm/files.html) (74,720 codes), [HCPCS Level II](https://www.cms.gov/medicare/coding-billing/healthcare-common-procedure-system/quarterly-update) (9,068 codes), [NPPES](https://npiregistry.cms.hhs.gov/api-page)** — health validation against real Medicare-like claims and a real, currently-active provider registry
- **[FEMA IHP disaster registrations](https://www.fema.gov/openfema-data-page/individuals-and-households-program-valid-registrations-v2)**, 3 public sample Xactimate estimate PDFs ([1](https://www.empireestimators.com/wp-content/uploads/2015/05/Sample-Estimate-I.pdf), [2](https://hhhroofing.com/wp-content/uploads/2022/01/Xactimate-Estimate-Example.pdf), [3](https://workflowsolutionsllc.com/wp-content/uploads/2021/05/Roof-Example-3.pdf)) — property validation and extraction against real (PII-scrubbed or pre-redacted) disaster/estimate data
- **[SBA 7(a)/504 FOIA](https://data.sba.gov/en/dataset/7-a-504-foia)** (1 file, 373,984 rows), **[SBA PPP FOIA](https://data.sba.gov/en/dataset/ppp-foia)** (1 file), official **[SBA Form 1919](https://www.sba.gov/document/sba-form-1919-borrower-information-form)** template — loan validation and blank-template abstention testing
- **FUNSD (OCR/layout) and RVL-CDIP (classification)** — these are domain-agnostic, "core mechanism" benchmarks and live in **doc-intel's own eval** instead (see its `TODO.md`), since they test OCR/classification quality independent of any ClaimFlow business domain

**No PHI or private borrower/patient data is used anywhere.** Public structured datasets (SynPUF, FEMA IHP, SBA FOIA) are used for validation realism — real codes, amounts, and dates — not as stand-ins for completed private application packages. CPT validation is deliberately not shipped (AMA-licensed content); it's pluggable, and a licensed CPT dataset would be required for production use.

### Public structured-data validation checks

These checks evaluate deterministic validators and structured-data sanity rules against public datasets; they are not full document-extraction accuracy numbers.

Large-sample public structured-data validation checks:

| Domain | Source | Files | n | Result |
|---|---|---|---|---|
| Health | [CMS SynPUF outpatient claims](https://www.cms.gov/research-statistics-data-and-systems/downloadable-public-use-files/synpufs/downloads/de1_0_2008_to_2010_outpatient_claims_sample_1.zip) (HCPCS/NPI/date checks) | 1 file | 500 claims sampled | 98.9–100% |
| Health | [NPPES NPI Registry](https://npiregistry.cms.hhs.gov/api-page) (format + fabrication check) | 30 API records | 30 NPIs | 100% |
| Property | [FEMA IHP Valid Registrations](https://www.fema.gov/openfema-data-page/individuals-and-households-program-valid-registrations-v2) (amount/date/consistency) | 50 API records | 50 records | 100% |
| Loan | [SBA 7(a)/504 FOIA](https://data.sba.gov/en/dataset/7-a-504-foia) | 1 file (373,984 rows total) | 2,000 loans sampled | 100% |
| Loan | [SBA PPP FOIA](https://data.sba.gov/en/dataset/ppp-foia) | 1 file | 282 loans | 100% |

### Public document extraction case studies

n=1–3, illustrative not statistical — these are real document extraction results, not validation-rule checks:

- Official [CMS-1500 template](https://www.cms.gov/medicare/cms-forms/cms-forms/downloads/cms1500.pdf) (1 file, blank) — 33% field-abstention on a genuinely empty form (model echoes the form's own printed labels as data — a real, root-caused finding, not fixed since it needs schema changes, not a prompt fix).
- Official [SBA Form 1919](https://www.sba.gov/document/sba-form-1919-borrower-information-form) (1 file, blank) — ~90% blank-field abstention.
- Official [SBA Form 413](https://www.sba.gov/document/sba-form-413-personal-financial-statement) Personal Financial Statement (1 file, blank) — 92% blank-field abstention (2 of 25 numeric fields, `cash_on_hand` and `savings_accounts`, echoed as `0.0` instead of `null`. The form's own `total_assets`/`total_liabilities`/`net_worth` fields aren't blank — verified directly against the PDF's AcroForm widgets, they carry a literal `0` default baked in by SBA, so the model reading `0` there is correct, not fabricating.).
- CMS's own [sample Explanation of Benefits](https://www.cms.gov/files/document/11819-sample-explanation-benefits-508.pdf) (1 file) — 10/11 fields correct (11/11 once a list-vs-string metric-comparison artifact is discounted — see `failures.md`). Started at 3/11: the model was reading the document's first service line instead of its own "Total" row; fixed with a prompt clarification, re-verified. One real, still-unresolved gap: `patient_name` returns the document's literal `"XXXXXX"` redaction placeholder instead of null.
- A public sample [homeowners declarations page](https://www.myfloridacfo.com/docs-sf/consumer-services-libraries/consumerservices-documents/understanding-coverage/sample-declarations-page.pdf) (1 file) — 15/15 fields correct, after correcting one gold-annotation error (an agent's name field wrongly included a license number).
- The 3 real Xactimate PDFs (linked above) started with 2 real extraction bugs (an insured/adjuster name swap, an ACV-definition ambiguity) — both root-caused and fixed via a prompt clarification, individually verified correct after the fix.

SBA Form 2202 (schedule of liabilities) is implemented (schema, classifier, validator, unit tests) but has no downloaded real/public fixture yet — deferred, see `failures.md`.

Full detail, including every number and every fix, in `eval/real_public/failures.md`.

Run it:

```bash
make download-real-public   # fetch and cache all datasets (gitignored, not committed)
make eval-real-public       # health + property + loan validation, plus Xactimate extraction
```

Every downloaded artifact is tracked in `eval/real_public/manifest.json` — source URL, sha256, accessed-at timestamp, license notes, and PII status. Results land in `eval/real_public/results/`; honest failure analysis (including several real bugs this process found and fixed, in both ClaimFlow and doc-intel) is in `eval/real_public/failures.md`.

## Known limitations

- **No real private claim-package evaluation yet.** The controlled end-to-end package eval uses synthetic generated packages with gold-labeled injected errors. The real/public eval layer uses public structured datasets, official blank templates, and a small number of public estimate PDFs for validation realism and selected extraction case studies — not private patient, claimant, or borrower packages.
- **No production HIPAA compliance.** ClaimFlow records application-level workflow audit events (`GET /packages/{id}/audit`), but does not yet provide compliance-grade, tamper-evident audit logging, PHI-specific access auditing, encryption at rest, or a retention policy — don't point this at real patient/claimant data as-is.
- **No production auth/RBAC.** The API and Streamlit UI have no authentication — anyone who can reach the port can submit and review claims.
- **MedCaseFlow is not implemented.** Medical/legal case-file intelligence (timeline reconstruction, contradiction detection, missing-evidence detection) is a separate, not-yet-built idea.
- **Scan quality is a heuristic, not real OCR confidence** — a character-density proxy computed by ClaimFlow over the text doc-intel returns; doc-intel's OCR backends don't expose true per-word confidence (see [OCR proof](#ocr-proof)).
- **Nested/list field row confidence and evidence are inherited from the parent field, not computed per row.** `diagnosis_codes`, `service_lines`, and `line_items` are individually reviewable (add/edit/delete rows, exported with action/original/final value) — see [Human review queue](#human-review-queue) — but doc-intel scores a list field as one whole, so every row in the export shares the same confidence/evidence rather than having its own.
- **Field accuracy is exact-match**, normalized for dates/currency but not names/addresses — minor OCR spelling variance counts as wrong even if a human reviewer would accept it.
- **Blank-field hallucination risk.** A model can fabricate a value for a blank field even when the schema allows null and the prompt says not to guess. Deterministic pattern checks catch this for `tax_id`, `applicant_name`, `billing_provider_npi`, and `claim_number` — generalizable, real-world rules, not synthetic-data hacks. `insurance_id` is mitigated by making the field nullable. `signature_on_file` remains unresolved — it's fundamentally a visual question, and needs vision-based verification, not another prompt tweak.
- **Health source-evidence accuracy (~85%) is lower than property/loan (~96–100%)** due to CMS-1500's dense form layout — values are often split across adjacent sub-boxes (e.g. date of birth as separate MM/DD/YY cells), which can push fuzzy-match grounding below threshold even when the extracted value itself is correct.
- **`temperature=0` doesn't guarantee bit-exact reproducibility.** Verified directly — the identical package, through identical code, produced a correctly-null `insurance_id` in some runs and a fabricated one in others. A known GPU-inference characteristic (floating-point non-associativity, batching effects), not a ClaimFlow bug.

### Production hardening still required

Before using ClaimFlow with real regulated data, the following are required:

- authentication and RBAC
- compliance-grade immutable audit logging, access-event capture and retention controls
- encryption at rest / secure object storage
- PHI/PII retention and deletion policy
- per-row confidence and evidence for nested/list fields
- production deployment profile
- real private-domain pilot testing under appropriate agreements

## Tech stack

Python 3.13 · LangGraph · FastAPI · Streamlit · Qdrant · sentence-transformers · PyMuPDF · pydantic-settings · doc-intel (editable dep)
