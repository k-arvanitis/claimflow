# TODO

Deferred production-hardening items — deliberately out of scope for the
current work, not forgotten.

## Auth / RBAC

No authentication or authorization anywhere — the FastAPI API and Streamlit
UI are both open. Needed before any real deployment: user accounts, role
separation (reviewer vs admin), and auth on `/claims` endpoints.

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

## UI



The ClaimFlow product UI

The polished UI belongs here.

Main screens

1. Dashboard

Show:

packages received;
awaiting review;
approved;
flagged;
escalated;
processing errors;
straight-through rate;
average review time;
validation failures by category.

Keep it operational, not a decorative analytics dashboard.

2. Review queue

Columns:

package ID;
claimant/applicant/insured;
domain;
received date;
number of documents;
confidence;
validation failures;
assigned reviewer;
current decision;
status.

Filters:

domain;
status;
confidence range;
failure type;
reviewer;
received date.
3. Package workspace

This is the most important screen.

┌───────────────────────────────────────────────────────────────┐
│ Package header: ID · domain · status · confidence · actions   │
├──────────────┬──────────────────────────┬─────────────────────┤
│ Documents    │ Original document        │ Review panel        │
│              │                          │                     │
│ claim.pdf    │ page image               │ Extracted fields    │
│ eob.pdf      │ bbox highlight           │ Validation failures │
│ policy.pdf   │ zoom / page navigation   │ Policy evidence     │
│              │                          │ Review history      │
├──────────────┴──────────────────────────┴─────────────────────┤
│ Approve package · Flag · Escalate · Reject                   │
└───────────────────────────────────────────────────────────────┘
4. Batch processing

Show:

uploaded package;
processing progress;
classified files;
OCR/native route;
extraction status;
errors;
retry action.
5. Audit history

Show:

extraction completed;
validation failed;
reviewer edited field;
validation rerun;
package approved/escalated;
export downloaded.
6. Settings

Initially:

confidence threshold;
escalation threshold;
enabled domains;
policy collection;
model/provider status.

Auth and user management can come later.

Recommended implementation order
Phase 1 — Product models and API contract

Before UI coding:

define Package, Document, Field, ValidationFailure, ReviewAction, and Decision models;
add package/review API endpoints;
add database persistence;
preserve current POST /claims as a compatibility/demo endpoint.
Phase 2 — Frontend shell

Create:

/dashboard
/review
/packages/[packageId]
/batches
/audit
/settings

Use Next.js and shadcn/ui.

Phase 3 — Review queue

Use typed fixture data first.

Do not wait for all backend endpoints before validating the table, filters, statuses, and navigation.

Phase 4 — Package workspace

Build the document viewer and field review panel with fixtures.

This screen should demonstrate:

bbox highlighting;
confidence;
field editing;
validation failures;
policy evidence;
package-level decision.
Phase 5 — Connect real APIs

Replace fixtures with ClaimFlow backend responses.

Phase 6 — Persistence and audit

Save review edits and decisions, rerun validation, and generate final reviewed exports.

Phase 7 — Demo polish

Create one strong property or health package walkthrough.

For the public portfolio demo, property insurance is probably the cleanest hero workflow because it demonstrates documents, estimates, arithmetic validation, policy windows, and source evidence without putting the focus on PHI/HIPAA concerns.

Health and loan can remain selectable additional domains.

What not to build now

Do not prioritize:

multi-tenancy;
enterprise SSO;
a distributed worker cluster;
Kubernetes;
advanced VLM damage assessment;
full HIPAA architecture;
a new extraction engine;
another synthetic dataset;
more domains.

The core portfolio product needs:

persistent packages

+ review APIs
+ Next.js review UI
+ document evidence viewer
+ reviewer corrections
+ validation rerun
+ decision history
  README assessment

The README is technically impressive but too long for the eventual repository landing page.

Because it is a GitHub README, detailed evaluation is appropriate, but I would eventually move the largest sections into:

docs/evaluation.md
docs/public-evaluation.md
docs/validation-rules.md
docs/architecture.md

The top README should retain:

what ClaimFlow does;
screenshot/demo;
pipeline;
domain support;
one example;
headline eval table;
setup;
architecture and limitations links.

The long public-source descriptions and detailed individual failures can live in evaluation documents.

Final verdict

ClaimFlow is ready to enter the product UI phase.

The backend is not finished for production, but it is already strong enough to support frontend development. The next work should not be more extraction or validation research.

The correct next milestone is:

Create persistent package/review APIs, then build the Next.js + shadcn operational interface around them.
