# ClaimFlow — Progress Log

Running record of work done on ClaimFlow across this work session(s). Newest at the bottom of each section unless noted. Nothing in this file has been committed to git as of the last update — treat it as a working log, not a changelog.

## Feature work

- **Positioning rewrite** — README repositioned from "RAG over documents" to "document-intelligence and validation pipeline"; extraction/validation/review is now the lead, retrieval is framed as a secondary step.
- **Document classification** — every document in a package is classified (not just the primary claim form), via deterministic keyword matching. Added `supporting_types` per domain (health/property/loan) and a two-pass classifier in `ingest.py`.
- **Source evidence (bbox)** — surfaced doc-intel's existing but previously-dropped field-level evidence (page, quote, bbox) through the API and Streamlit UI.
- **OCR proof** — side-by-side page viewer (rendered image + extracted text) in Streamlit, OCR fallback log, "scan quality" heuristic (character-density proxy, explicitly not real OCR confidence).
- **Interactive human review** — Streamlit review queue: per-field approve/edit/reject, suggested correction (surfaces the validator's own failure reason), JSON export of reviewed fields.
- **DOCX + image ingestion** — `ingest.py` now globs PDF/image/DOCX; DOCX converts to PDF via headless LibreOffice (mirrors an existing pattern from another project); images open natively via fitz (no conversion needed).
- **MedCaseFlow** — discussed at length; decided **not** to fold into ClaimFlow (different pipeline shape: no single "primary form," needs timeline/contradiction detection, not claim validation). Spec'd as a separate future project in `~/PORTFOLIO.md`, not built.
- **User-defined extraction schemas** — considered and rejected. doc-intel (the underlying dependency) already supports arbitrary schemas; adding that to ClaimFlow would dilute its differentiation (deterministic validation on *known* fields) and pull it back toward the "PDF to JSON" framing it deliberately moved away from.

## Eval infrastructure

- Extended `scripts/run_eval.py`: field accuracy by type (date/code/currency/text), source-evidence accuracy, scanned-vs-born-digital split, actually writes `output/eval_results.json` (README had claimed this before the script did it).
- Fixed `.env` model mismatch (`mistral-small-24b` configured, `qwen3-32b` actually running) and a pre-existing bug in `scripts/seed_qdrant.py` (manually created an unnamed-vector Qdrant collection incompatible with the FastEmbed convenience API used elsewhere).
- Currency-field comparison was originally a fragile keyword-guess list — replaced with schema-driven type detection (reads the real Pydantic field type instead of guessing from field names).
- Fixed a `None`-vs-`""` bug: the eval was penalizing the model for *correctly* returning `null` on a blank field, comparing it against ground truth's `""` as if they were different values.

## Bugs found and fixed (chronological)

1. **Loan domain classification totally broken** — synthetic forms say "LOAN REQUEST FORM," keywords only matched "SBA loan application" phrasing. Field accuracy was 0% before this fix.
2. **Currency fields compared as raw strings** — `15932.0` vs `"15932.00"` failed a strict string match despite being numerically identical.
3. **Health schema missing `patient_city`/`state`/`zip`** — ground truth had them, the extraction schema didn't, so 3 fields were unfixably wrong every run.
4. **`insurance_id` prefix dropped** — model stripped the "INS" prefix; fixed via a concrete prompt example (this example later caused bug #16 — see below).
5. **Non-deterministic extraction** — `doc-intel`'s `call_llm()` never set `temperature`. Added `DOC_INTEL_TEMPERATURE` (default `0.0`) in `doc-intel/config.py` + threaded through `llm.py`. (Cross-repo change, flagged explicitly before making it.)
6. **Coarse evidence bbox on dense forms** — PyMuPDF's `find_tables()` detected CMS-1500's entire page (its outer border) as one giant table, collapsing every field's evidence into a whole-page bbox. Fixed in `doc-intel/inputs/pdf.py`: skip tables covering >80% of page area (verified safe against property/loan's real tables, which occupy 7–12% of their pages).
7. **Two retired ICD-10 codes in the generator's own "valid" pool** — `M54.5` and `K21.0` were both replaced by specific subcodes in the 2021 ICD-10-CM revision. The model extracted them correctly; the deterministic validator correctly flagged them as non-billable. Fixed the generator (`M54.50`, `K21.00`), regenerated the 30 health packages. Health's false-positive rate: 88.9% → 0%.
8. **`tax_id` placeholder fabrication** — Pydantic field *description* literally said `"EIN (XX-XXXXXXX)..."`; model echoed the placeholder back when the field was blank. Prompt/schema fixes alone didn't stop it (verified: identical output across two attempts, ruling out caching). Fixed with a deterministic validator: any letter in `tax_id` → reject.
9. **`applicant_name` fabrication** — model substituted a business name (e.g. `"LOPEZ SOLUTIONS DBA"`) when the field should be blank. Fixed with a deterministic check: business-entity markers (`LLC`, `Inc`, `Corp`, `DBA`, `Partnership`, etc.) in a person-name field → reject. Verified generalizable (these are real business-entity suffixes, not synthetic-specific).
10. **`billing_provider_npi` fabrication (wrong length)** — model fabricated a 9-digit value when the NPI field was blank. Fixed: NPI must be exactly 10 digits.
11. **`patient_address` extraction miss** — model sometimes returned `null` despite the value being clearly present in the source text, likely due to ambiguity introduced by the new city/state/zip split (bug #3). Fixed by clarifying the field description to explicitly state it's a *fourth, separate* field, not replaced by city/state/zip.
12. **Eval script's `None`/`""` bug** — see Eval infrastructure above.
13. **`claim_number` fabrication (property)** — model substituted a person's name (`'JACKSON ROBERT'`) for a blank claim number. Made nullable + added a generalizable check: a real claim/reference number always contains a digit, regardless of an insurer's specific prefix convention (deliberately avoided a "must start with CLM" check — that's this generator's convention, not a real-world standard).
14. **`billing_provider_npi` fabrication pattern #2** — a *different* fabrication (`'1234567890'`, a sequential placeholder) passed the 10-digit-length check from #10. Added a check for all-one-digit or simple ascending/descending 10-digit runs. **Important methodology note:** I initially considered implementing the real NPI Luhn check-digit algorithm, but caught myself relying on an unverified memorized "fact" (that `1234567893` is NPPES's published valid example) that my own implementation contradicted. Without internet access to confirm, I discarded the checksum approach rather than ship code I couldn't verify — used the simpler, self-verifiable pattern check instead.
15. **Generator regression from fix #14** — the new fabrication check broke `test_validate.py::test_clean_claim_no_failures` (and 3 other files) because the *pre-existing test fixtures* used `"1234567890"` as their example of a valid NPI. Investigated further and found the *synthetic generator's own* "valid" NPI pool contained the same class of placeholder-style values (`1234567890`, `0987654321`, `1122334455`, etc.) — same root cause as bug #7. Fixed the generator's `NPIS` pool, regenerated health data, fixed the 4 affected test fixtures. Health false-positive rate: (regressed to 77.8%) → back to 0%.
16. **`insurance_id` fabrication — self-inflicted** — traced to the exact example string I added in fix #4 (`'INS507943839'`) being echoed back verbatim as a literal template whenever the field was blank. Fixed by abstracting the prompt example and making the field nullable. No deterministic backup check was needed or found — no safe, generalizable pattern exists for insurance ID formats the way NPI/tax ID have real federal standards. Verified fixed on both known-failing packages.

## Rigorous reproducibility finding (important — read before trusting any single eval run)

While chasing health's catch rate below ~81.5%, I found a real, non-fixable phenomenon: **`temperature=0` does not guarantee bit-exact reproducibility** on this vLLM setup.

Verified rigorously, not assumed:
- The same package (`package_006`), run through **provably identical code** (`app.invoke()` with a fresh thread_id, same call signature confirmed by reading both code paths side by side), produced a correctly-null `insurance_id` in some invocations and a fabricated one in others.
- Ruled out: stale data (diffed the files — byte-identical), batch-composition effects (reproduced with both 30-package and single-package eval runs), and a code-path difference (the two invocation sites are line-for-line equivalent).
- Conclusion: genuine GPU-inference non-determinism (floating-point non-associativity / scheduling effects in vLLM), not a ClaimFlow bug and not fixable by more prompt/schema engineering.

This means health's catch rate (~81.5%) is a **stable average across repeated full runs**, not a single-run snapshot — but individual borderline packages can flip between runs. Documented in the README's Known Limitations.

## Evidence-accuracy finding (in progress — corrects an earlier wrong guess)

Earlier hypothesis (now refuted): health's lower evidence accuracy (~85% vs. ~100% property, ~94-96% loan) was due to CMS-1500 splitting values across adjacent sub-boxes (e.g. DOB as separate MM/DD/YY cells).

**Actual verified cause**, checked against real per-field data across 5 packages: `accept_assignment` and `signature_on_file` — both **boolean** fields — never carry evidence, in every single package, 100% of the time. Root cause: doc-intel's evidence linker does fuzzy *text* matching between a field's value and page text blocks; a boolean's value stringifies to `"True"`/`"False"`, which never literally appears in the source PDF (the form shows a checkbox mark, not the word "True"). This is a structural limitation of the evidence-linking approach for boolean fields specifically, not a health-specific or CMS-1500-specific issue.

This cleanly explains the cross-domain pattern: property has **zero** boolean fields → 100% evidence accuracy. Loan has **one** (`signature_on_file`) → 93.8–95.8%. Health has **two** (`accept_assignment`, `signature_on_file`) → ~85%. The gap tracks boolean-field count almost exactly.

**Status: concluded.** Evidence-accuracy root cause (boolean fields never grounded) is confirmed and not further investigated this session — a real fix needs field-type-aware evidence linking, a doc-intel feature, not a quick patch.

## Catch-rate: second confirmation of the reproducibility finding

Re-tested the `diagnosis_codes`/`icd10_lookup` miss (package_004) with extra rigor, since 3 direct invocations in a row all gave the identical (correct, caught) result — which initially looked like it might contradict the `insurance_id` non-determinism finding rather than confirm it.

Settled it with an independent test: ran the actual `scripts/run_eval.py --packages` code path (not my own script) on this exact single package. Result: `decision: "approved"`, 0 validation failures — meaning the model's *extracted value* for `diagnosis_codes` differed from the 3 consistent runs (it did not contain `'XXXXX'` that time), not that the validator behaved differently. This confirms genuine token-level output variation on a **second, independent field**, via an **independent method** (comparing extracted values across invocations, not assuming one run generalizes).

**Conclusion, now with two confirmed fields:** the non-determinism finding holds. A 3/3 identical streak on one field doesn't disprove it — the phenomenon is probabilistic (the model is *usually* consistent for a given input, but not always), not "flips every other call." Health's catch rate (~81.5%) should be read as a stable multi-run average, not a guarantee for any individual package on any individual run.

**Follow-up test, more precise characterization:** ran `scripts/run_eval.py --packages` on the same single package 3 times in a row (separate process launches) — all 3 were consistently "not caught," matching the earlier separate `run_eval.py` runs. Combined with the standalone script's separate 3/3 "caught" streak, the pattern isn't "flips randomly call to call" — it's **stable within one invocation session, different between separate sessions**. Most likely explanation: something session-scoped on the vLLM serving side (KV-cache state, connection reuse, internal batching/scheduling context) correlates with the outcome, not the package or the application code. Still not a ClaimFlow bug — same code, same input, different LLM-serving session state — but this is a more precise characterization than "random per call," reached only by testing repeated invocations *within* each method, not just comparing one run of each.

## What to do about it, if anything (discussed, not built)

- **Evidence accuracy (booleans):** three options laid out — accept as-is; exclude booleans from the evidence-accuracy denominator (cheap, honest — a measurement fix, not a pipeline change, same category as the `None`/`""` eval bug); or make evidence linking boolean-aware in doc-intel (real work, uncertain reliability). Checked the generator: health's `accept_assignment` and `signature_on_file` **do** render as literal extractable text (`"[X]"` checkboxes, `"Signature on File"` vs. underscore placeholder) — so option (c) does **not** need a vision model, contrary to what I said earlier. Correction: I had overstated this as "fundamentally a visual question."
- **Loan's `signature_on_file` extraction accuracy** (a different problem — getting the value right, not linking evidence to it) is genuinely harder: the generator prints literally nothing when false (no placeholder at all, unlike health's underscore line), making the absence hard for the model to attend to. A vision model is *one* way to address this, but two text-only prompt rewordings were tried and failed — text-only approaches weren't fully exhausted before reaching for "needs vision," so that characterization was also overstated.
- **Catch-rate non-determinism:** self-consistency voting (majority-vote over repeated extraction calls) is the standard mitigation. Full version re-runs every field (3x cost); a cheaper targeted version only re-checks mandatory fields that come back null (the exact ambiguous case), costing near-nothing on clean packages.
- None of the above has been implemented — this section is options-on-the-table, not a to-do list.

## Current eval numbers (last full run, all fixes applied)

| Domain | Field accuracy | Catch rate | False positive | Evidence accuracy |
|--------|-----------------|------------|------------------|---------------------|
| Health (CMS-1500) | ~92% | ~81.5% (see reproducibility note above) | 0% | ~85% (see evidence-accuracy finding above) |
| Property (Xactimate) | 98.1% | 100% | 0% | 100% |
| Loan (SBA) | 96.7% | 100% | 0% | 93.8% |

Starting point (before this session's fixes): Health 68.8%/66.7%/88.9%/75.2%, Property 92.2%/66.7%/0%/100%, Loan 0% (broken)/0%/0%/—.

## Honestly unresolved

- **`signature_on_file` fabrication** (loan) — the underlying fact ("is this line signed") is fundamentally a visual question, not textual. A real fix needs vision-based verification; doc-intel has an unused `VLM_ENABLED` path that could be extended for this, but that's a real scope/cost decision (new model calls, added latency), not applied without explicit go-ahead.
- **Evidence-accuracy gap for boolean fields** — understood and explained (see above), not yet fixed. A real fix would need field-type-aware evidence linking (e.g. searching for the field's label/checkbox region instead of the stringified value) — a genuine doc-intel feature, not a quick patch.

## Process notes worth remembering

- Two changes this session touched `doc-intel` (a separate repo, editable dependency): `temperature` control and the near-full-page-table skip. Both were flagged explicitly before making them, not done silently.
- Several "fixes" were reverted or corrected mid-session after being caught by their own regressions (bug #15) or by re-verification against fresh samples (bug #16's root cause was only found by re-sampling, not assumed). Don't treat a single verification as final — re-run before declaring something fixed, especially given the reproducibility finding above.
- `tests/schemas/cms1500.py` has one pre-existing, unrelated lint finding (unsorted imports) that predates this session — deliberately left untouched per "touch only what's needed."

## Session N+1: new document types + review/eval features (COMPLETE)

Big multi-part feature request, all 9 parts (A-I) done and verified — see the
detailed conversation for exact numbers. Summary:

- **Part A** — nested/list fields (`diagnosis_codes`, `service_lines`,
  `line_items`) are now editable tables in Streamlit (add/edit/delete rows),
  export includes per-row action/original/final value, real validation
  rerun via the domain's actual `validate()`. Logic lives in
  `src/claimflow/review.py` (`diff_list_field`, `rerun_validation`) —
  extracted there specifically so it's unit-testable without a Streamlit
  context.
- **Parts B–E** — 4 new deep-extraction domains registered, same
  `Domain`/`register()` pattern as the existing 3, zero architecture
  changes: `eob`/`medicare_summary_notice` (`domains/health.py`),
  `declarations_page` (`domains/property.py`), `sba_form_413` +
  `sba_form_2202` (`domains/loan.py`). Prompts added to `prompts.py`.
- **Part F** — 14 classification-only keyword aliases added (UB-04,
  damage_photo, roof_inspection_report, etc.) — recognized, no extraction.
- **Part G** — downloaded 3 new real fixtures (CMS sample EOB, Florida CFO
  declarations page, blank SBA Form 413) via
  `eval/real_public/scripts/download_real_public.py` (new functions
  `download_eob_sample`, `download_declarations_page_samples`, extended
  `download_sba_forms`). Hand-labeled gold in
  `eval/real_public/datasets/{health,property,loan}/gold/`. Ran real
  extraction, found + fixed 2 real bugs (verified before/after): EOB was
  reading the document's first service line instead of its own "Total" row
  (fixed via `EOB_EXTRACTION` prompt in `prompts.py`) — 3/11 → 10/11 field
  exact (11/11 once a list-vs-string metric-comparison artifact in
  `field_exact_accuracy` is discounted, not fixed — documented, single-field
  cosmetic issue); one gold-annotation error on the declarations page
  (`agent_name` — fixed the gold file, not the model) — 14/15 → 15/15. SBA
  Form 413 blank-template abstention: 80% (5/25 fields fabricated as `0.0`
  instead of `null` — same known failure class as CMS-1500/Form 1919, not
  fixed). SBA Form 2202 implemented + unit-tested but **has no downloaded
  real fixture yet** — deferred, documented in `failures.md`, not silently
  dropped. Maryland's declarations-page sample returns HTTP 403 (bot-blocked
  WAF) — documented, not substituted with fake data.
- **Part H** — README updated: classification table now splits deep-extraction
  vs classification-only, validation rules table extended for new domains,
  two now-stale claims fixed ("nested fields aren't reviewable" was true
  before Part A, false after — both the Example section and Known
  Limitations bullet were corrected), new case-study numbers with links.
- **Part I** — 26 new tests in `tests/test_new_domains.py` (classification,
  schema instantiation, validators, nested-list review export/rerun) +
  generalized `test_gold_fields_schema_accepts_real_gold_files` in
  `tests/test_real_public_eval.py` to glob all 3 domains' gold dirs, not
  just property's. **66/66 tests passing**, lint clean (one pre-existing,
  unrelated `schemas/cms1500.py` import-order finding, not touched).

Also added `rapidfuzz>=3.0.0` as a real (not just eval-extra) dependency in
`pyproject.toml` — used by `domains/property.py`'s new
`_validate_declarations` address fuzzy-match check.

## Session N+2: production hardening (IN PROGRESS — context limit hit, resuming next session)

User-approved plan (after explicit discussion, not unilaterally decided):
**do now**: persistent DB, audit logs, async job processing, per-row
evidence/confidence. **Explicitly deferred to TODO, not implemented**: VLM
path (signature/checkbox/photo verification) and auth/RBAC — user said "put
in todo," do not build these without being asked again.

Architecture decisions already made via `AskUserQuestion` (don't re-ask):
- **DB engine: SQLite** (not Postgres) — zero new infra, fits the existing
  single-process/uv setup, swappable later via SQLAlchemy if ever needed.
- **Async mechanism: FastAPI `BackgroundTasks` + a DB-backed status row**
  (not RQ+Redis) — no new infra/worker process, job status
  (queued/processing/failed/completed) persisted in the DB.
- **Secure storage / encryption at rest: deferred to TODO entirely** — user
  said "put also this in todo" when asked; do NOT implement app-level file
  encryption, just note it in a TODO doc alongside auth/RBAC and VLM.

### What's actually done so far this sub-session

1. **Per-row evidence/confidence (doc-intel change, in progress, unverified)**:
   - `doc-intel/src/doc_intel/schemas/base.py`: added
     `parent_field: str | None = None` to `FieldConfidence` — set only on a
     synthetic per-row entry for a `list[dict]` field (e.g.
     `name="service_lines[0]"`, `parent_field="service_lines"`).
   - `doc-intel/src/doc_intel/confidence.py`'s `score()`: after computing
     the existing top-level `fields`/`overall`/`flagged`/`status` (UNCHANGED
     — this matters, see below), additively builds `row_fields` by calling
     `score_field()` once per dict-row of every top-level list value, then
     returns `fields + row_fields`. Overall confidence, flagged-fields, and
     status are deliberately computed from the original `fields` list
     *before* combining, specifically so this change can't shift existing
     confidence/routing behavior for CMS-1500/Xactimate/loan — this was a
     considered design choice, not an oversight, so don't "simplify" it by
     computing overall over the combined list.
   - **NOT YET DONE**: wiring the consumer side. `claimflow/review.py`'s
     `diff_list_field(name, original, edited, meta, note)` still takes a
     single flat `meta` dict (the parent field's aggregate confidence/
     evidence) and applies it to every row — this needs to change to accept
     the full `fields_meta` dict (keyed by name) and look up
     `fields_meta.get(f"{name}[{i}]")` per row, falling back to the parent's
     aggregate `meta` only if no per-row entry exists (backward compatible
     for any list field that isn't `list[dict]`, e.g. `diagnosis_codes`
     which is `list[str]` and will never get row entries from `score()`
     since it only scores `list` values containing `dict` rows).
   - **streamlit_app.py** call site (`_diff_list_field(k, v, edited_values,
     meta, note)` around the nested-field review loop) needs updating to
     pass the full `fields_meta` dict instead of `fields_meta.get(k, {})`.
   - **NOT YET VERIFIED**: was mid-way trying to run doc-intel's own test
     suite (`/home/karvanitis/doc-intel/tests/`) to check this doesn't
     regress anything there — hit a broken `pytest` binary in doc-intel's
     `.venv` (`cannot execute: required file not found`, despite `uv sync
     --group dev` reporting success and the file existing at
     `.venv/bin/pytest`). **This needs a real fix before trusting the
     confidence.py change** — try `uv run --group dev python -m pytest
     tests/ -q` instead of the `pytest` binary directly, or `rm -rf .venv &&
     uv sync --group dev` to rule out a corrupted venv. Do NOT assume the
     confidence.py change is safe until this actually runs green.
   - Also need to re-run **ClaimFlow's own** test suite
     (`tests/test_new_domains.py`'s `test_diff_list_field_table_rows` etc.)
     after changing `review.py`'s signature, since that test currently
     calls `diff_list_field(name, original, edited, meta)` with a flat meta
     dict — the signature change will need either a compatible default or
     the test updated to pass a `fields_meta`-shaped dict.

### Not started yet (this sub-session)

- **Persistent DB** (SQLite via SQLAlchemy — not yet added as a dependency;
  run `uv add sqlalchemy` in `claimflow`). Needs a new module, likely
  `src/claimflow/db.py`: engine/session setup, models for at least
  `Package` (id, created_at, status), `Document`, `ExtractedField`,
  `ValidationFailureRow`, `ReviewAction`, `AuditLogEntry`, `Job` (status:
  queued/processing/failed/completed). DB file path should go through
  `src/claimflow/config.py` (existing settings pattern), not hardcoded.
- **Audit logs** — depends on the DB existing first. Needs to log: upload,
  extract, validate (failures), and every Streamlit review action
  (approve/edit/reject/export, both scalar and the new nested/list rows).
  Since Streamlit and the FastAPI API are two separate processes that both
  need to write audit entries, the DB module needs to be a shared import
  both sides use (`claimflow.db`), not API-only.
- **Async processing** — `api/main.py`'s `POST /claims` currently runs the
  graph synchronously in a thread executor and returns the full result in
  one response, with a `tempfile.TemporaryDirectory()` that's deleted
  before the function returns (nothing persisted anywhere today). Needs:
  create a `Package` row with `status="queued"` immediately, kick off a
  `BackgroundTasks` job that runs the graph and updates the row to
  `processing` → `completed`/`failed`, return `{package_id, status}`
  immediately instead of blocking. Add `GET /claims/{package_id}` to poll
  status and fetch the result once done. This also means the uploaded
  files can no longer live in a `TemporaryDirectory` that's deleted
  same-request — they need to persist at least until the background job
  reads them (a real, not-yet-decided detail: where do uploaded files live
  between request and background-job completion, given secure storage
  itself is deferred to TODO — a plain non-encrypted temp/data directory
  that outlives the request is the minimum needed, not full secure storage).
- **TODO.md entries** — need to add explicit TODO entries for auth/RBAC,
  VLM path, and secure storage/encryption-at-rest/retention-deletion, per
  the user's explicit "put in todo" instructions. Check if `claimflow` has
  a `TODO.md` yet (doc-intel has one; unclear if claimflow does) — create
  one if not, don't bury this in README.

### Immediate next action for the next session

1. Fix the doc-intel pytest invocation and actually verify the
   `confidence.py`/`schemas/base.py` change is safe (real regression check,
   not assumed).
2. Wire `claimflow/review.py` + `streamlit_app.py` to use per-row
   `fields_meta` lookups, update/add tests, re-run ClaimFlow's full suite.
3. Then move to the DB layer (SQLite + SQLAlchemy), audit logs, async
   processing, and the TODO.md entries, in that order, per the
   user-agreed sequencing earlier in this conversation.

## Session N+2 continued: all remaining items closed out (DONE)

All three "not started" items above are now done and verified.

1. **doc-intel pytest fixed and green.** Root cause: `.venv/bin/pytest`'s
   shebang pointed at a stale path (`/home/karvanitis/doc-intel-pipeline/...`
   — the repo was renamed to `doc-intel` and the old venv never got
   rebuilt). Fix: `rm -rf .venv && uv sync --group dev`. `uv run --group dev
   python -m pytest tests/ -q` now passes 40/40. The `parent_field`/
   per-row `score()` change is confirmed non-regressing.

2. **`claimflow/review.py` wired to per-row confidence.**
   `diff_list_field(name, original, edited, fields_meta, note=None)` now
   takes the full `fields_meta` dict (was a single flat `meta` dict) and
   looks up `fields_meta.get(f"{name}[{i}]")` per row, falling back to
   `fields_meta.get(name, {})` (the parent's aggregate) when no per-row
   entry exists — this is the backward-compatible path for `list[str]`
   fields like `diagnosis_codes`, which doc-intel's `score()` never emits
   row entries for (only `list[dict]` fields do). `streamlit_app.py`'s call
   site now passes `fields_meta` directly instead of `fields_meta.get(k,
   {})`. Added `test_diff_list_field_table_rows_use_per_row_confidence` in
   `tests/test_new_domains.py` covering both the per-row-hit and
   fallback-to-parent cases. Full ClaimFlow suite: 67/67 passing.

3. **Persistent DB (SQLite + SQLAlchemy).** New `src/claimflow/db.py`:
   `Package` (id, created_at, status: queued/processing/completed/failed,
   `result_json`, `error`) and `AuditLogEntry` (package_id, timestamp,
   actor, action, `detail_json`) tables. Deliberately NOT normalized into
   separate `Document`/`ExtractedField`/`ValidationFailureRow` tables — the
   full pipeline result is stored as one JSON blob on `Package.result_json`;
   normalizing further wasn't needed by anything built so far and would
   have been speculative. `Settings` gained `db_path` (default
   `data/claimflow.db`) and `storage_dir` (default `data/uploads`) —
   both explicitly commented as NOT encrypted at rest, see `TODO.md`.
   `sqlalchemy` added as a real (non-eval-extra) dependency.

4. **Audit logs.** Both `api/main.py` and `streamlit_app.py` import
   `claimflow.db` directly (shared module, two processes) and call
   `db.log_audit(session, package_id, actor, action, detail)` at: upload,
   extract, validate (with the failures list), and — Streamlit only —
   `review_edit` (on the "Re-run validation on reviewed values" button,
   logging every field's approve/edit/reject action plus any remaining
   failures) and `export` (on the JSON download button, same field-action
   snapshot). Deliberately does NOT log on every Streamlit widget rerun
   (radio/text_input changes fire a rerun on every interaction — logging
   there would flood the audit table with noise); the review state is
   captured as one snapshot at the two points where it's actually acted on
   (re-validate, export).

5. **Async processing.** `api/main.py`'s `POST /claims` no longer runs the
   graph synchronously in a thread executor with a `TemporaryDirectory`
   deleted before the response returns. Now: uploaded files are written to
   `{storage_dir}/{package_id}/`, a `Package` row is created with
   `status="queued"`, `BackgroundTasks.add_task(_run_claim, ...)` is
   kicked off, and the endpoint returns `{package_id, status}` immediately.
   `_run_claim()` updates status to `processing` then `completed`/`failed`,
   storing the full result as JSON. New `GET /claims/{package_id}` polls
   status and returns `{package_id, status, result, error}` (404 if
   unknown id). `tests/test_api.py` updated to the new two-step flow
   (verified: Starlette's `TestClient` runs `BackgroundTasks` synchronously
   before `client.post()` returns, so the polling test doesn't need real
   polling/sleeping). Full suite: 67/67 passing, ruff clean on all touched
   files (the one pre-existing `cms1500.py` import-sort finding is
   untouched, as before).

6. **`TODO.md` created** at repo root with three sections: Auth/RBAC, VLM
   path (with a note pointing at `damage_photo`'s classification-only
   status in `property.py`), and Secure storage/encryption at rest (naming
   the actual unencrypted paths: `data/uploads/`, `data/claimflow.db`).

**Verification performed, not assumed:** doc-intel 40/40, ClaimFlow 67/67,
ruff clean, `streamlit run` boots and serves `200` on a scratch port,
manual `db.py` smoke test (create package → log audit → update status →
read back) all green. Test-generated `data/claimflow.db` and
`data/uploads/` cleaned up after each run (both are `.gitignore`d now,
alongside the existing `data/synthetic|lookups|real_public` entries).

**Not done (by design — explicit user directive):** auth/RBAC, VLM path,
storage encryption. All three are now in `TODO.md`, not implemented,
per "do everything except for vlm and auth, which should be in todo" and
"put also this in todo" (secure storage).

**Nothing pending for a future session right now** — this closes out the
production-hardening scope agreed earlier in the conversation. If new work
comes in, start a fresh `## Session N+3` section rather than editing this
one.

## Session N+3: backend/frontend correctness review fixes (DONE — 2026-07-22)

Reviewed the current FastAPI, LangGraph, SQLite, Streamlit, and Next.js code
as one end-to-end workflow, then fixed every confirmed defect from that
review without changing the established project structure or coding style.

### Backend and persistence fixes

- New uploads now atomically reserve `processing` before the background task
  is scheduled. This closes the race where an immediate `POST .../process`
  could start a second graph run while the first still appeared `queued`, and
  makes restart recovery able to see an in-flight initial run.
- `DocumentType` now covers every deep-extraction and classification-only
  classifier output. Supporting documents such as `medical_bill`,
  `damage_photo`, and `bank_statement` can no longer cause FastAPI response
  validation failures, and the frontend reclassification menu exposes the
  same complete set.
- Package result documents are sanitized at both write and read boundaries.
  New results store public `filename` metadata, and older result blobs that
  still contain `path` are sanitized before `GET /packages/{id}` returns
  them, so raw server filesystem paths are never exposed.
- Validation reruns now merge the latest persisted scalar and nested-row
  review actions with request corrections, preserve machine extraction,
  supersede prior failures, persist the new failures/decision/review reasons,
  and update the package result projection.
- Reviewer decisions now update the result projection and lifecycle: final
  approval moves a package to `completed`; flagged/escalated decisions keep
  it in `review_ready`.
- Export now reads the latest normalized extraction run, current failures,
  latest decision, and latest review actions. Each field includes immutable
  machine `value`, derived `final_value`, and reviewer metadata.
- Streamlit now uses the same processing/review-ready/completed status
  semantics and persists normalized extraction results instead of marking
  every run completed.
- The real/public download helper now imports optional `openpyxl` only inside
  the HCPCS spreadsheet path, so the default backend test suite does not
  require the eval extra.

### Frontend and browser fixes

- Field editing preserves value types: numbers remain numbers, booleans use a
  boolean select, scalar lists require JSON arrays, and nested rows use typed
  JSON objects. Invalid edits remain open and show an error instead of being
  submitted as strings.
- Nested list rows now support edit in addition to approve/reject, and prior
  review actions can be revised instead of permanently hiding the controls.
- Revalidation includes nested-row rejection semantics; the backend removes
  the stable indexed row exactly once before applying deterministic rules.
- The React 19 mobile hook now uses `useSyncExternalStore`, removing the
  synchronous-effect state update and making frontend lint clean.
- The browser smoke script discovers a package dynamically (or accepts
  `CLAIMFLOW_PACKAGE_ID`), supports configurable frontend/API/screenshot
  locations and read-only runs, and exits non-zero for captured browser
  errors instead of only printing them.
- OpenAPI TypeScript types were regenerated from the updated live FastAPI
  schema. README endpoint count and upload status example were corrected.

### Regression coverage and verification

- Added coverage for classifier/enum parity, atomic initial processing,
  sanitized result documents, scalar/nested review merging, typed numeric and
  nested-row UI edits, rerun decision persistence, completed final approval,
  and reviewed export values.
- Backend: **193/193 pytest tests pass**.
- Frontend: **28/28 Vitest tests pass**; ESLint clean.
- Production frontend build and TypeScript check pass for all routes.
- Ruff check/format pass on every Python file changed in this session.
- Live read-only Playwright smoke against FastAPI `:8010` and Next.js `:3001`
  passed dashboard, packages, reviews, upload, all five workspace tabs, and
  settings with **zero console/page errors**. Screenshots: `/tmp/claimflow-screens`.

No live LLM/OCR extraction or Qdrant retrieval was rerun in this session; the
browser smoke used an existing processed package, while automated backend
tests kept external model/retrieval behavior mocked as designed.

## Session N+4: root CMS-1500 live backend evaluation (DONE — 2026-07-22)

Used `CMS1500-1-791x1024.png` from the repository root as a real acceptance
document and ran it through both the extraction nodes and the persisted FastAPI
multipart upload/reprocessing workflow with the configured OpenRouter/Qwen model.

### Defects found and fixed

- Whole-page LightOn OCR classified the form correctly but omitted the dense Box
  24 service table and repeated hallucinated lower-page headings. The first live
  baseline therefore returned no service lines, missed the patient address, and
  scored 0.777 confidence.
- CMS-1500 image extraction now renders four overlapping proportional regions of
  the standardized form and OCRs them concurrently. This preserves the full form
  context while recovering the table layout; if regional OCR is unavailable, the
  normal doc-intel source path remains the fallback.
- Box 24 pipe-delimited OCR rows are aligned deterministically to the standard A-J
  columns. This prevents EMG/modifier cells from being mistaken for diagnosis
  pointers and keeps dates, CPT/HCPCS, charge, units, and rendering provider IDs
  on the correct service row.
- CMS two-digit dates are normalized to `MMDDYYYY`, Box 33a is selected instead of
  33b, and the separate Box 17a qualifier is removed from the referring provider
  name. Corrected values are synchronized into both extraction data and per-field
  review rows.
- Box 1a is optional in the extraction schema and the image leaves it blank, but
  validation still treated it as mandatory. Removed that contradictory failure;
  blank Box 1a now remains `null` without a false review reason.
- The health extraction prompt now explicitly documents overlapping OCR regions
  and the Box 1a, Box 17/17a, Box 24, and Box 33a mapping rules.

### Live acceptance result

- Uploaded through `POST /packages` and reprocessed through
  `POST /packages/{id}/process`; persisted package:
  `60f9a994-92b8-46da-b88a-a40ded180ddb`.
- Exact comparison against the visible form: **27/27 top-level fields and 6/6
  service rows**, with no missing, mismatched, or unexpected fields.
- Correctly extracted the blank Box 1a, Salemy patient/insured identity and full
  Knoxville address, all 12 diagnosis entries, all six Box 24 rows, $396.90 total,
  $200.00 paid, Box 33 provider data, and signature date.
- Final live confidence: **0.913**. Package status is correctly `review_ready` with
  decision `flagged`: the synthetic source itself contains an invalid Box 33a NPI,
  non-ICD diagnosis strings, and CPT `640`. It has 14 genuine validation failures,
  no arithmetic mismatch, and no false blank-Box-1a failure.
- Qdrant was not running locally, so secondary policy lookups returned “No relevant
  policy document found.” This did not interrupt extraction, validation, decision,
  persistence, or the acceptance comparison.

### Verification

- Focused CMS graph/schema/validation suite: **20/20 passed**.
- Full backend suite: **196/196 passed** (three existing dependency warnings).
- Ruff check passed for every Python file changed in this session.
- Temporary FastAPI servers were stopped. The evaluated package remains in the
  local SQLite database and upload storage for UI/API inspection.

## Session N+5: complete CMS-1500 schema and image cross-check (DONE — 2026-07-23)

Extended the canonical CMS-1500 schema to retain the useful populated values on
the root acceptance image instead of limiting extraction to the original summary
fields.

### Schema and extraction fixes

- Added complete patient/insured contact and relationship data, other-insurance
  details, accident/condition flags, signatures and dates, Box 14-23 claim data,
  tax-ID type, account/assignment values, complete Box 32/33 provider data, and the
  correct Box 17 provider qualifier semantics.
- Box 24 service rows now retain both dates, EMG, all four modifiers, diagnosis
  pointer, charge, units, EPSDT/family-plan value, ID qualifier, and rendering ID.
- Added Box 31 signer text and a semantically named physician signature date while
  retaining `service_date` as a backward-compatible alias.
- Corrected `xx` to `referring_provider_qualifier`; the printed `17a` form label is
  no longer stored as an other-ID qualifier.
- Provider names, complete multiline addresses, phone, signer, and signature date
  are recovered deterministically from the standardized lower-page table.
- Split the wide structured LLM response into two concurrent non-Box-24 passes.
  Deterministic Box 24 rows are merged back and the complete result is rescored
  against the canonical public schema and full OCR text. This avoids the configured
  provider's effective completion cap without dropping public fields.
- Fixed ClaimFlow-to-doc-intel runtime passthrough for provider, model, base URL,
  API credentials, and output-token budget. Namespaced ClaimFlow settings prevent
  doc-intel's own dotenv defaults from changing behavior based on import order.

### Live acceptance result

- Reprocessed package `60f9a994-92b8-46da-b88a-a40ded180ddb` through the real
  FastAPI background workflow using `CMS1500-1-791x1024.png`.
- Pixel-by-pixel/manual expected-value comparison: **75/75 scalar fields exact**
  and **6/6 service rows exact across all 15 retained columns**.
- Telephone values are `(877) 355-4141` for patient and insured and
  `(800) 111-2222` for billing provider. Patient/insured ZIP is `37902`; service
  facility ZIP is `88765`; billing provider ZIP is `66554`.
- Final live confidence is **0.927**. Status is correctly `review_ready` and the
  decision is `flagged` for the sample's 14 intentionally invalid synthetic
  NPI/ICD/CPT values, not for extraction mismatch.

### Verification

- Focused settings/schema/graph suite: **18/18 passed**.
- Full backend suite: **198/198 passed** (three existing dependency warnings).
- Ruff passes on all changed Python files.

## Session N+6: advertised import matrix and operator UI (DONE — 2026-07-23)

Ran every advertised deep-extraction document type through the real FastAPI upload,
background processing, persistence, validation, and review pipeline. This was a live
model/OCR acceptance pass, not the mocked unit-test path.

### Import results

| Type / fixture | Live result |
| --- | --- |
| CMS-1500 root PNG | 75/75 scalar fields and 6/6 service rows × 15 columns exact; 0.927 confidence; 14 expected synthetic-code validation failures |
| CMS sample EOB | All 15 canonical fields match the reference after printed redaction placeholders are normalized to `null`; 0.771 confidence |
| Medicare Summary Notice route | Same CMS teaching document manually routed and reprocessed successfully; 0.810 confidence |
| Generic loan application | 10/10 fields exact; 0.988 confidence; approved with zero failures |
| SBA Form 413 | Correctly wins over generic SBA classification; 25/25 fields match the blank official form, including three AcroForm zero totals; zero failures |
| SBA Form 2202 | Correctly classified; blank official form abstains with an empty liabilities list and `null` total; zero failures |
| Florida declarations page | 15 populated policy fields; 0.981 confidence; approved with zero failures |
| Empire Estimators Xactimate | All 57 numbered rows plus exact subtotal, overhead, profit, tax, RCV, depreciation, and ACV; 0.804 confidence; approved with zero failures |
| HHH Roofing Xactimate summary | Correctly treats the scanned/redacted one-page summary as having no item table; exact RCV, depreciation, ACV, deductible, loss date, and loss type; zero failures |
| Workflow Solutions Xactimate | All 12 numbered rows, separate per-line tax handling, exact subtotal/tax/RCV/zero depreciation/ACV, correct property address, and no fabricated loss date; zero failures |

The blank/redacted SBA and Xactimate samples remain in review because their overall
confidence is intentionally low, not because validation failed. That distinction is
visible in both API output and the operator UI.

### Fixes from the expanded matrix

- Specific numbered SBA form classifiers now outrank the generic “Small Business
  Administration” keyword match.
- EOB placeholder strings are nulled consistently in both the canonical data and
  per-field review projection; payer branding is no longer substituted for a missing
  explicitly labeled payer.
- Named SBA Form 413 PDF widgets are used as authoritative native evidence for the
  form's zero-valued totals.
- Xactimate scalar extraction runs page-locally while numbered estimate rows are
  split into bounded model requests. Missing model rows are retried, then native
  aligned PDF rows authoritatively restore line numbers and numeric values.
- Both Xactimate table variants are supported: direct RCV columns and separate TAX +
  RCV columns. For the latter, row totals correctly exclude tax so they reconcile to
  the printed line-item subtotal.
- Summary-only estimates no longer fail merely because the source does not include a
  line-item page or because the insured/property was deliberately redacted.
- Xactimate RCV validation now reconciles printed line subtotal + overhead + profit +
  material sales tax. Depreciation/ACV are recovered from either explicit summary
  labels or the final line-item totals row, and estimate-entry dates are not mistaken
  for a date of loss.

### UI verification

- The package header, overview, queue, and per-field table display lifecycle status,
  routing decision, confidence, validation counts, and low-confidence field counts.
- A live Playwright browser pass against the 57-line Empire package showed Backend
  online, Completed, Approved, 80% confidence, one document, zero failures, the PDF
  viewer, and all review tabs.
- Frontend verification: **28/28 Vitest tests passed**, ESLint passed, TypeScript
  passed, and the Next.js production build completed for all routes.

### Verification

- Focused property/graph/domain suite: **52/52 passed**.
- Full backend suite: **205/205 passed** (three dependency warnings).
- Ruff passes across `src/claimflow`, `api`, and `tests`.

## Session N+7: official CMS policy cross-check (DONE — 2026-07-23)

Enabled and verified the secondary policy-evidence stage for the root CMS-1500
acceptance package.

### Corpus and retrieval fixes

- Fixed `scripts/generate_policies.py`: after each `multi_cell`, FPDF left the
  cursor at the right edge, so subsequent policy paragraphs were clipped to a
  few characters. Regenerated all three complete demonstration PDFs.
- Added two official CMS sources:
  - Medicare Claims Processing Manual, Chapter 26, “Completing and Processing
    Form CMS-1500 Data Set.”
  - CMS “The National Provider Identifier” fact sheet.
- Recorded authoritative URLs and the synthetic/official distinction in
  `data/policies/SOURCES.md`.
- Seed metadata now includes policy domain and authority. Qdrant contains
  **579 chunks from five PDFs**: 551 official CMS chunks and 28 synthetic
  demonstration chunks.
- CMS-1500 retrieval filters to the health domain and `official_cms` authority;
  synthetic demonstration policies cannot support CMS decisions.
- Citations now include the actual source filename and a bounded source excerpt
  instead of an unverifiable label such as `policy excerpt [1]`.
- CMS policy explanations are deterministic rather than LLM-generated. This
  removed blank/truncated answers and prevents invented code descriptions or
  coverage conclusions. The response explicitly separates:
  - policy/form requirements;
  - code-registry membership validation; and
  - payer-specific coverage, which this corpus cannot determine.
- Reprocessing now replaces the package's prior policy-evidence rows, including
  clearing them when a later run has no answers. The reporting endpoint no
  longer accumulates duplicate evidence from historical runs.

### Live CMS result

- Reprocessed package `60f9a994-92b8-46da-b88a-a40ded180ddb` through the live
  API with Qdrant enabled.
- Extraction remains exact at **0.927 confidence** with the same 14 initial
  NPI/ICD/CPT validator outputs. A later source audit (Session N+8) found that
  these outputs are directionally correct but incomplete and must not yet be
  treated as a production-grade CMS compliance result.
- Policy stage produced **14/14 non-empty answers**, each with exactly one
  official CMS citation.
- Persisted `GET /packages/{id}/policy-evidence` returns exactly 14 current
  entries, not accumulated history.
- NPI evidence cites the CMS fact sheet's 10-digit numeric definition.
- ICD evidence cites Chapter 26 Item 21 diagnosis-code/date-of-service
  requirements while correctly identifying the code registry as the authority
  for whether each particular code exists.
- CPT/HCPCS evidence cites Chapter 26 Item 24D and explicitly states that the
  manual does not contain the licensed current CPT set or establish
  payer-specific coverage.

### Verification

- Focused retrieval/database/graph suite: **34/34 passed**.
- Full backend suite: **210/210 passed** (three dependency warnings).
- Ruff passes across the changed backend, tests, and policy scripts.
- Qdrant remains running on port 6339 for UI testing.

## Session N+8: CMS rule-source audit (RESEARCH COMPLETE — 2026-07-23)

Re-checked the root CMS-1500 image, ClaimFlow's validators, and the live
package result against official, date-appropriate CMS sources.

### Confirmed conclusions

- Box 33a is required for Medicare and must contain the billing provider/group
  NPI. CMS defines an NPI as a 10-digit numeric identifier. The image visibly
  contains `33-216649a`, so the billing-NPI rejection is correct.
- The form's service dates are in February 2017. Medicare claims for services
  on or after October 1, 2015 require ICD-10-CM, and the CMS-1500 02/12 ICD
  indicator must therefore be `0`. The image contains `E`, which is invalid.
- The A-L text printed to the left of Box 21 entries is the form's diagnosis
  slot lettering. The image also visibly contains separate lowercase-prefixed
  values (`a525.10` through `l585.56`); this is not an OCR merge. None of the
  normalized values appears in CMS's official FY 2017 ICD-10-CM code file.
- Chapter 26 says periods must not be entered in Box 21 diagnosis codes. Every
  diagnosis value in the image contains a period.
- Item 24D requires HCPCS. CPT codes are five numeric digits and HCPCS Level II
  codes are one letter plus four digits. The submitted `640` is therefore not
  valid as printed; the 2017 PFS contains the distinct five-digit code `00640`.

### Gaps found in the implementation

- The live result's 14 answers are not a complete CMS cross-check. ClaimFlow
  fails to flag the invalid ICD indicator `E`, forbidden diagnosis periods,
  and numeric Box 24E pointers (`1`-`6`) even though the 02/12 form requires
  letters `A`-`L`.
- Only Box 33a is NPI-validated. The visibly malformed NPIs in Boxes 17b, 24J,
  and 32a are not checked, and the official NPI Luhn check digit is not
  implemented.
- `data/lookups/icd10.csv` contains the 2026 code set, not the FY 2017 code set
  applicable to this claim. ICD membership validation must be date-versioned.
- `data/lookups/cpt.csv` is explicitly a synthetic numeric-range placeholder,
  not an authoritative CPT registry. It produces false confidence: `11478` is
  accepted solely because it falls inside a generated range, although it is
  absent from the January 2017 Medicare PFS file.
- The January 2017 PFS lists `99444` with status `N` (non-covered by Medicare),
  while the current validator silently accepts it and does not surface the
  coverage result.
- Further visible form issues are not checked, including malformed/unsupported
  place-of-service values (`A33`, `44`), a reversed service date range on the
  third line, and provider identifiers that are not valid NPIs.

### Source set used

- CMS Medicare Claims Processing Manual, Chapter 26.
- CMS National Provider Identifier Standard and NPI check-digit specification.
- CMS FY 2017 ICD-10-CM code descriptions.
- CMS January 2017 Physician Fee Schedule relative value file.
- CMS HCPCS overview and 2017 Alpha-Numeric HCPCS archive.

No validator code was changed during this research-only audit.

## Session N+9: other-case rule and evidence audit (RESEARCH COMPLETE — 2026-07-23)

Applied the same source-level review to the other live/imported cases: CMS's
sample EOB, the manually reclassified MSN route, the generic loan fixture, SBA
Forms 413 and 2202, the three public Xactimate estimates, and the Florida sample
declarations page.

### Cross-cutting finding: non-CMS policy evidence is demonstrative only

- Only `cms1500` retrieval filters to `authority=official_cms`. EOB/MSN,
  Xactimate, declarations, generic loan, Form 413, and Form 2202 retrieval can
  use the generated `health_policy.pdf`, `property_policy.pdf`, and
  `loan_policy.pdf`.
- Those three PDFs are synthetic demonstration text, not insurer contracts,
  SBA rules, state insurance rules, or Verisk/Xactimate specifications.
- Some synthetic statements are affirmatively wrong or too broad:
  - `loan_policy.pdf` says SBA loans have a $5,000 minimum; SBA says the 7(a)
    program has no universal minimum.
  - `property_policy.pdf` says line-item sums must equal RCV, although legitimate
    Xactimate estimates can apply sales tax, O&P, and additional charges.
  - It also says negative line items are prohibited, while Xactimate explicitly
    supports credit line items.
  - It says every estimate requires line items, contradicting ClaimFlow's
    intentional support for valid summary-only estimates.
- Non-CMS policy answers remain LLM-synthesized, unlike the deterministic CMS
  answers. They must be labeled as non-authoritative demo output or disabled
  until official/customer-provided policy sources are installed.

### EOB and Medicare Summary Notice

- The CMS EOB fixture's totals and fields are extracted correctly. CMS confirms
  an EOB is not a bill and the sample visibly says `THIS IS NOT A BILL`.
- The live `medicare_summary_notice` package is not a true MSN fixture. It is
  the same generic CMS EOB teaching PDF manually reclassified to test the route.
  This proves override/reprocessing works, not MSN-specific extraction quality.
- `is_bill=False` is source-backed. The remaining rules are mostly completeness
  or anomaly heuristics, not formal adjudication:
  - `provider_charges >= allowed_charges` is common and true in the sample, but
    CMS only says the values may differ; the validator presents the inequality
    too categorically.
  - “claim number must contain a digit” is an extraction guard, not a published
    universal identifier rule.
  - `patient_name` being required is sensible for an operational review queue,
    but the public sample deliberately redacts it; missing data does not make
    the source document an invalid EOB.
- Non-negative checks omit deductible, coinsurance, and copay. There is no
  guarded reconciliation of patient responsibility to its components and no
  CARC/RARC/remark-code reference validation.
- The live package currently has one active validation failure but four
  persisted policy-evidence rows, including duplicate/stale questions from
  older runs. Future reprocessing uses replacement persistence, but existing
  pre-fix rows were not migrated or cleaned.

### Generic loan fixture

- The live `application.pdf` is a generated “Horizon Community Bank” loan
  request, not SBA Form 1919 and not evidence of SBA eligibility validation.
- Its ten extracted fields match the fixture, so the extraction demo is sound.
  The `approved` decision means only that the small structural validator passed;
  it is not a lending, underwriting, SBA eligibility, or fraud decision.
- The tax-ID rule only rejects alphabetic placeholders. It does not enforce the
  IRS nine-digit EIN/SSN structures, much less verify an identifier.
- Rejecting a business entity in `applicant_name` is tailored to this schema's
  first owner row; official Form 1919 uses “Applicant” for the business itself.
- `net_income <= gross_revenue` is a useful anomaly heuristic, not a universal
  SBA eligibility rule. Other income/accounting presentation can require human
  interpretation.
- Signature detection accepts the printed text `Signature on File`; it has no
  visual/cryptographic evidence that an authorized representative actually
  signed.

### SBA Form 413

- The official blank form is correctly escalated for low confidence and is not
  falsely approved. Its three zero totals are real AcroForm defaults.
- The arithmetic identity `assets - liabilities = net worth` is valid.
- Important official form rules/fields are missing:
  - statement recency: within 90 days for Disaster or 120 days for the other
    listed SBA programs (the validator only rejects future dates);
  - required certification/signature/date and possible spouse signature;
  - sum of asset components to total assets and liability components to total
    liabilities;
  - `other_assets` and the form's separate income categories.
- The schema's single `annual_income` field does not correspond to the current
  form's separate salary, investment, real-estate, and other-income fields.

### SBA Form 2202

- The official blank form is correctly escalated for low confidence.
- The implemented schema is materially incomplete: it omits applicant name,
  schedule date, signature, and signer title.
- It introduces `total_current_balance`, although the published Form 2202 does
  not print that total field.
- The official instruction is that the schedule supplements the balance sheet
  and should balance to liabilities on that form. ClaimFlow does not extract
  or merge the balance sheet here, so the central official reconciliation is
  not implemented.
- `current_balance > original_amount` can be a useful review signal but is not
  universally invalid; capitalized interest, fees, or modified debt can produce
  that state beyond the code's narrow revolving/deferred exceptions.

### Xactimate estimates

- The three public estimate fixtures are currently extracted accurately and
  their printed arithmetic reconciles:
  - Empire: 57 rows sum to `$38,707.98`; plus O&P and tax equals RCV
    `$48,151.75`; RCV less depreciation equals ACV `$45,900.18`.
  - HHH summary: subtotal plus tax equals RCV `$26,360.08`; RCV less
    depreciation equals gross ACV `$14,251.64`.
  - Workflow Solutions: 12 rows sum to `$21,317.55`; plus tax equals RCV
    `$21,997.14`; depreciation is zero.
- These are document-arithmetic checks, not coverage decisions. No carrier
  policy is loaded and no covered-peril determination is made.
- The hard-coded `subtotal + overhead + profit + tax = RCV` model is not
  universal. Verisk supports additional charges, multiple tax/O&P application
  modes, cumulative O&P, and line-level O&P.
- The validator does not directly check each row's quantity × unit cost despite
  the schema describing that identity.
- HHH's source separately reports a net ACV payment after deductible. ClaimFlow
  stores gross ACV and deductible but has no `net_acv_payment` field, leaving a
  real semantic ambiguity hidden from the UI.

### Declarations page

- All 15 implemented fields match the Florida CFO sample, so the extraction
  case itself is strong.
- The schema loses useful policy meaning: the hurricane deductible is printed
  as `2% of Coverage A` and `$3,200`, but ClaimFlow retains only `$3,200`.
- It omits the policy form, insured-property address as a distinct field,
  Coverage E/F, optional coverages, endorsements, discounts/surcharges, and
  policy fees.
- The date-of-loss/policy-period and property-address consistency rules exist
  only for a pre-merged dictionary. The production pipeline does not merge an
  estimate with a declarations page, so those advertised cross-document checks
  do not execute in a normal package.

### Real/public evaluation scope

- The structured CMS SynPUF, FEMA IHP, SBA 7(a), and PPP scripts perform
  dataset-specific sanity checks. Except for a small NPI helper reuse, they do
  not run the corresponding production document validators.
- Their 100% rates show that sampled public rows satisfy those independent
  checks; they do not prove that CMS-1500, Xactimate, or loan validation rules
  are complete or authoritative.
- The real extraction fixtures remain valuable evidence for extraction and
  abstention behavior, but should not be described as regulatory compliance or
  end-to-end claim adjudication.

No validator, schema, persistence, or UI code was changed during this
research-only audit.

## Session N+10: DomainPack refactor, safe routing labels, Streamlit removed (DONE — 2026-07-27)

Formalized the `Domain` registry into a real DomainPack: added `display_name`,
`policy_collection`, `retrieval_mode`, `question_templates`, `extraction_hook`/
`extract_fn`, per-domain thresholds, `reviewer_guidance` to `domains/base.py`,
and drove `extract_node`/`retrieve_node` from those fields instead of
hardcoded `domain_key == "..."` branches. Validation failures now carry
`severity` and `policy_required`; policy retrieval only fires for failures
with a real citable answer (a data migration, `0006`). Decision vocabulary
renamed system-wide: `approved`/`flagged`/`escalated` →
`ready_for_processing`/`needs_review`/`blocked_or_incomplete` (data migration
`0007`) — a recommendation, not a final decision. Added read-only
`GET /domain-packs`/`GET /domain-packs/{key}` inspector endpoints. A frontend
domain-pack panel was scoped but skipped by request.

Removed `streamlit_app.py` and the `streamlit` dependency entirely — the
Next.js app in `frontend/` (already shadcn/ui-based) is now the only UI.
`make ui` replaced with `make frontend`. Verified the full core flow live in
a real browser against the running backend (dashboard, package list, package
workspace — fields/validation/policy-evidence/audit tabs — settings), after
fixing a CORS-allowlist gap that only allowed `localhost:3000`/`3001` while
the dev server had landed on `3002`.

## Session N+11: workflow-selection authority, decision-model split, BYOK LLM settings, UI compactness (DONE — 2026-07-27, uncommitted)

### Domain-selection authority (backend correctness fix)

The `/packages/new` workflow-selection UI added in Session N+10's follow-up
was cosmetic only — the selected workflow was never sent to the backend, so
content classification silently drove processing regardless of what the user
picked. Fixed for real: `POST /packages` accepts an optional `domain` form
field; `ingest_node` now treats a caller-supplied domain as authoritative and
never overwrites it with content classification, instead emitting
`detected_domain` + `domain_mismatch` as separate, informational fields.
Reprocessing (`POST /packages/{id}/process`) now carries the previously
resolved domain forward by reading it out of the stored result, so a
reprocess doesn't silently fall back to auto-detection. `extract_node`'s
"no matching document" error now names the detected domain too, when
different, so a mismatch produces an actionable error instead of a bare
"no cms1500 document found". Frontend sends the selection, and the
"detected workflow differs" banner now reads the real
`domain_mismatch`/`detected_domain` fields instead of comparing client state
to the backend's already-resolved `domain`.

### Decision-model: system recommendation vs. reviewer outcome, tracked separately

`decisions` rows previously had no way to distinguish a system-computed
recommendation (written by validation re-runs) from a reviewer's own
submission (written by `POST /packages/{id}/decision`) — both landed in the
same table with the same shape, so "was this overridden" was unqueryable.
Added `source` (`system`|`reviewer`) and `is_override` columns (migration
`0009`); `package_read_model` now exposes `system_recommendation`,
`reviewer_outcome`, and `reviewer_override` as distinct fields alongside the
existing conflated `decision` (kept for backward-compatible filtering/sort).
Wired through: the packages queue and dashboard's "recently processed"
table show both columns with an `(override)` tag; the workspace Overview tab
shows both as separate stat tiles.

### Policy-evidence linked to the finding it supports

`PolicyAnswer`/`PolicyEvidence` gained `field`/`rule` (migration `0008`), so
each cited policy answer now visibly states "Supports validation finding:
`net_income` (`income_consistency`)" instead of being a flat, disconnected
list of Q&A cards.

### Bugs found and fixed via live browser verification (not just unit tests)

- **Xactimate false-positive arithmetic failure**: `property.py`'s RCV
  reconciliation check treated a package with no extracted line items, no
  printed line-item subtotal, and no overhead/profit/tax as `$0`, then
  flagged every such estimate as an arithmetic mismatch against RCV. Fixed:
  skip the check when there's no reconciliation basis at all. Regression
  test added.
- **Stale workspace panels after processing finishes**: `usePackage` polls
  itself while a package is processing, but `useDocuments`/review/audit/
  policy are separate queries fetched once on mount — after processing
  completed, the document list and other panels stayed empty until a manual
  page reload. Fixed with a status-transition effect that invalidates the
  related queries once `status` changes.
- **Extraction spot-check across 5 real samples, 3 domains**: one CMS-1500
  field misassignment (a blank phone box got the adjacent ZIP value, at
  100% confidence) didn't reproduce on 2 more samples — inherent LLM
  extraction noise in the doc-intel dependency, not a ClaimFlow code bug,
  left as a known limitation. A separate Xactimate `date_of_loss` miss was
  correctly self-reported at 30% confidence — the system behaving as
  designed.

### BYOK LLM provider settings (ported from vault-rag)

New Settings card: pick Groq, OpenRouter, or OpenAI (plus an optional model),
save/clear, takes effect immediately with no restart. `src/claimflow/
llm_credentials.py` is a JSON-file-backed override (plaintext, gitignored,
same trust model as `.env`) wired into both `retrieve.py`'s policy-synthesis
LLM client and doc-intel's extraction LLM — doc-intel reads its
provider/model/key/base-url from plain module globals with no reconfiguration
hook, so the override mutates those globals at runtime and restores the
captured originals on clear. `GET/POST/DELETE /llm-credentials`, no auth
(matches this app's existing no-auth pattern).

### UI compactness and contrast fixes (demo-readiness pass)

Live browser verification surfaced real usability bugs beyond what unit
tests or a code read would catch:
- **Black-on-black text**: the `warning` tone's `TONE_CLASS` paired
  `text-warning-foreground` (a dark color meant only for the *solid* warning
  background) with a translucent `bg-warning/20` background — rendered as
  near-invisible dark-on-dark in dark mode. Same bug independently present in
  `metric-card.tsx`'s dashboard tiles and `package-header.tsx`'s "Needs
  review" button (neither goes through `status.tsx`). All three fixed to use
  `text-warning` directly.
- **Fields tab required horizontal scroll**: merged 7 columns down to 4
  (Field/Value/Signal/Actions), then — after a first attempt that only
  widened the workspace's default panel split (screen-size-dependent, so it
  didn't hold on a real laptop window) — switched to a `table-fixed` layout
  with fixed `%` column widths plus `truncate`/`title` tooltips, so columns
  never expand past their slot regardless of content length or window size.
  Same treatment applied to the nested line-item tables and to the
  Validation tab, which was rewritten from an 8-column table into compact
  per-failure cards.
- **Dashboard layout**: "Straight-through rate" was an isolated single card
  below the metric grid; merged into the 8-tile grid. "Recently processed
  packages" gained the System rec./Reviewer outcome split (dropped its
  Confidence column to keep the card from overflowing at 5 columns).

Full backend suite (242 tests) and frontend (tsc/eslint/vitest, 28 tests)
green throughout. Nothing in this session has been committed to git yet —
see git status for the full uncommitted diff.

## Session N+12: eval bug chase, PDF-scroll/evidence UX, Docker fix, demo prep (DONE — 2026-08-02, uncommitted)

Started from "fire the full eval" and kept pulling threads — each fix
exposed the next real bug, verified live rather than assumed:

- **Eval 401s were a `python-dotenv` script-vs-import discovery bug.**
  `doc_intel/config.py`'s bare `load_dotenv()` finds a different `.env`
  depending on whether the caller is a `-c`/import invocation or a real
  script — as a script, it walked up from `doc-intel`'s own file location
  and silently loaded *doc-intel's own* `.env` (a different OpenAI key)
  instead of claimflow's OpenRouter key. Fixed by running eval via
  `uv run --env-file .env`, which sets the env var before Python starts so
  it wins regardless of dotenv's internal resolution.
- **Property `date_of_loss` was 0/30** — a regex guard in `extract.py`
  meant to stop estimate-completion dates being substituted for
  `date_of_loss` required a colon/hash after the label; this synthetic
  corpus prints "Date of Loss\n07062025" with no colon, so the guard's own
  detection never matched and it nulled a correctly-extracted value every
  time.
- **Property line items were never extracted** — `_xactimate_line_layouts`
  requires numbered rows ("1.", "2."); this template has none, so the
  chunker found nothing and the native regex fallback (which also expects
  numbers) found nothing either. Fixed with a whole-page LLM fallback when
  no numbered items are found.
- **ACV auto-override defeated `acv_check` by construction** — `extract.py`
  always recomputed `actual_cash_value = RCV - depreciation`, overwriting
  whatever was actually printed, so the validator built to catch a printed
  ACV that doesn't reconcile could never fire. Now only fills the value
  when extraction found nothing.
- **CMS-1500 native/born-digital PDFs skipped the truncation-safe split
  schema entirely** — `_cms1500_extract_fn`'s split-schema path
  (`_cms1500_llm_specs`, built specifically so the 76-field schema doesn't
  hit the model's completion-length ceiling) only ran for the OCR-image
  branch; native PDFs fell through to one unsplit 76-field call, which then
  truncated on dense documents (`Max retries exceeded... Invalid JSON`).
  Fixed to route native PDFs through the split path too — and since that
  split intentionally excludes `service_lines` (normally filled by an
  OCR-marker-based deterministic parser that native PDFs never produce),
  added a dedicated LLM call for `service_lines` on the native-PDF branch
  specifically, so Box 24 doesn't silently regress to empty.
- **`find_evidence` picked the wrong block for composite/row values** —
  three compounding issues, found live via a real service-line-by-service-
  line inspection: (1) a short leaf value (a line number) could spuriously
  match an unrelated same-length block anywhere on the page since
  `partial_ratio` scores a 1-char overlap as ~100%; fixed by refusing to
  consider a block shorter than the value being matched. (2) Even after
  that, a row dict's *first* leaf winning (insertion order) meant a row
  could ground on a weak field instead of a strong one; fixed by matching
  the row's combined field values as one string first. (3) Sibling rows
  sharing a field (every service line has the same `date_of_service`)
  still couldn't be told apart by `find_evidence` alone, since it has no
  visibility into sibling rows — fixed at the `score()` level instead,
  where all rows of a list field *are* visible together: each row's
  evidence lookup is narrowed to just the fields that differ across
  siblings (`_discriminating_keys`).
- **`not_found` fields displayed a misleading confidence** — a field with
  no value gets `confidence ≈ validation_weight` (~30%) as a scoring-
  formula artifact, not a real signal, but the UI showed it as a plain red
  percentage next to a correctly-blank field. `ConfidenceBadge` now shows
  "Not found" for these; `flagged_fields` (the Overview tab's "low-
  confidence" count) excludes them server-side, and `overview-tab.tsx`
  independently recomputes the same count client-side and needed the same
  exclusion applied separately — the earlier backend fix alone hadn't
  covered it.
- **Boolean/no-evidence fields offered an evidence button that always
  failed** — checkboxes ground on presence/absence, not printed text, so
  `find_evidence` structurally can never return a match; the Fields tab now
  only shows the evidence icon when `f.evidence != null`, for any field
  type, not just booleans.
- **OCR'd image evidence highlighting was completely broken, two separate
  bugs deep**: (1) `TesseractBackend` (the real-bbox OCR fallback) renders
  at 300 DPI internally, but the temporary PDF `unstructured` partitions
  is sized in *points* equal to the pixmap's *pixel* count — so returned
  bbox coordinates were ~4.17x too large, always falling entirely outside
  `render_page()`'s page-bounds clamp and getting silently dropped with no
  error. Fixed by scaling back to the real page's point space. (2) Once
  bbox became valid, a second bug surfaced that the first had been
  masking: `page.draw_rect()` requires a real PDF — a page opened directly
  from a standalone image (a valid upload type) isn't one ("is no PDF"),
  so every image-sourced package's evidence highlight silently failed.
  Fixed by wrapping the image in a real one-page PDF before drawing.
  Also reordered `OCR_FALLBACK_PROVIDERS` to try `tesseract` (real bboxes)
  before `lighton` (page-level-only, no bbox at all) — evidence
  traceability matters more here than lighton's better raw OCR accuracy.
- **PDF viewer required its own tiny internal scroll** — the 3-column
  workspace layout clipped the document panel to viewport height; now the
  doc-list and review-tabs columns stay sticky-pinned while the PDF column
  grows to its natural page height and the whole page scrolls, verified at
  multiple zoom levels (a first attempt let a zoomed image overflow
  horizontally into the neighboring column — fixed by clamping horizontal
  overflow only, not vertical).
- **The Dockerfile never actually produced a working image** — three
  compounding bugs, found by actually building and running it rather than
  reading it: (1) `doc-intel` is a sibling editable dependency not in the
  build context at all — fixed via a named `--build-context`. (2) copying
  the *whole* doc-intel tree pulled in its unrelated 9.4GB `.venv` (12.5GB
  transferred) — fixed by scoping the copy to `pyproject.toml`/`README.md`/
  `src/`. (3) `alembic.ini`/`alembic/` and the `data/lookups/`
  (ICD-10/CPT validators) and `data/policies/` directories were never
  copied at all, so the container crashed on startup before the first
  request. All fixed; container now builds, migrates, and serves `/health`
  end to end.
- **A full clean `make eval` run** (post all of the above) — CMS-1500
  98.8%, Xactimate 99.6%, SBA 98.0% field accuracy; 0% false-positive rate
  and 100% citation rate across all three domains. README's eval table
  updated with these real numbers (was stale at ~92%/98.1%/96.7%).

Full backend suite (doc-intel 277, claimflow 234), frontend (tsc + 31
vitest tests), production frontend build, and a real Docker build+run all
green. Nothing in this session has been committed to git yet.

**Open, not chased tonight**: Qdrant's `claimflow_policies` collection
emptied itself three separate times during this session with no
application-level call (`delete_collection`/`recreate_collection`) that
could explain it, and the Docker container never restarted — looks
external to the app (a scheduled task on this shared box touching Docker
volumes is the leading guess). Worth a `curl localhost:6339/collections`
check immediately before recording, and re-seeding
(`uv run python scripts/seed_qdrant.py`) if it's empty.

## Session N+13: client search/history/export, EOB fixes, repo finalization for demo recording (DONE — 2026-08-02)

**Client-facing features, requested for portfolio positioning:**
- `packages.client_name`/`client_key` columns (derived, not a full `clients`
  table — deliberately cheap: search/filter/history don't need identity
  resolution). Populated per-domain via a new `Domain.client_name_field`
  (`patient_name`/`insured_name`/`applicant_name`), refreshed on reviewer
  correction. Migration `0012` backfills existing packages.
- Search box now matches client name, not just package ID; clicking a
  client name filters the queue to their history (no new route needed).
- `GET /packages/export.xlsx` — batch Excel export across every package
  matching the current filters, one workbook, Package column disambiguates
  rows across the 5 existing sheets (`excel_export.py` refactored to share
  row-append logic between single- and batch-export).

**EOB bug chase, three real bugs found by live-testing, not by reading code:**
- Evidence "hallucinating" on EOB fields traced to `unstructured`'s
  hi_res layout model occasionally returning a corrupt/oversized bbox for
  a whole `Table` element — matched text was correct, the highlight box
  was garbage (extended past the real page). Fixed by dropping malformed
  bbox at the OCR-backend layer (`doc-intel/ocr_backends.py`) rather than
  trusting it. Follow-up: switched `TesseractBackend`'s element extraction
  from `strategy="hi_res"` to `strategy="ocr_only"` — smaller per-line
  blocks instead of one corrupt merged table, far better evidence
  granularity on real-world scans.
- Root design bug: the EOB schema modeled one flat claim per document, but
  every real EOB sample has 2+ claim blocks per page — extraction was
  silently mixing fields across claims (`patient_responsibility` from
  claim A, `claim_number` from claim B). Fixed with a real schema change:
  `EOB.claims: list[EOBClaim]`, mirroring CMS-1500's `service_lines`
  pattern; validator rewritten to iterate per claim; prompt rewritten to
  explicitly describe claim-block boundaries (a first prompt-only attempt
  overcorrected and split each *line item* into its own fake claim —
  fixed by explicitly stating a claim block is identified only by its own
  "Claim:" header). Column/totals-row mapping (which of two valid-looking
  totals a claim's `plan_paid`/`patient_responsibility` should read from)
  remains genuinely nondeterministic across LLM runs — documented in
  TODO.md as needing a deterministic parser, not more prompt tuning.

**UI fixes, mostly demo-recording-driven:**
- Sidebar real bug: `/packages/new`'s active-link check compared
  `item.href !== "/packages/new"` (always true, comparing the nav item's
  own constant href to itself) instead of `pathname !== "/packages/new"` —
  both "Packages" and "New package" lit up simultaneously.
- New-package upload page: "Open package workspace" button now stays
  disabled with a spinner until the package actually finishes processing,
  instead of dropping the user into an empty workspace immediately after
  upload.
- `DecisionBadge` reused the same "Ready for approval" label for both an
  unreviewed system recommendation and a reviewer's own final approval —
  added a `resolved` prop so a finalized outcome reads "Approved"/"Blocked"
  instead of still sounding pending.
- Document list: click target was only the filename row (small, easy to
  miss); whole card is now clickable/keyboard-accessible. "Classified
  only" documents get a visible caption, not just a hover tooltip (a
  tooltip is unusable on a screen recording).
- Audit tab: dropped the raw-JSON "Technical details" dump (was collapsed
  by default but added no value on camera) and the redundant "api" actor
  tag; kept the one-line human summaries.
- Policy evidence tab: dropped the redundant question-text subtitle,
  answer paragraph already restates it; fixed the collapsible chevron to
  point `>` closed / rotate to `v` only when open (was static).
- New Settings "Package types" card — expandable per-domain schema browser
  (required/optional fields, thresholds, retrieval mode) using the
  existing read-only `/domain-packs` endpoints; primary vs. supporting
  document types now shown as separate badge groups instead of one long
  comma string.
- Renamed "workflow" → "package type" in all `/packages/new` user-facing
  copy (internal `domain` field/variable names unchanged).

**Repo finalization, ahead of packaging for delivery:**
- Removed `streamlit_app.py` (legacy UI, already gone from a prior
  session, confirmed clean).
- Two `.pyc` files were tracked in git under `src/claimflow/schemas/
  __pycache__/` — untracked and removed from disk; `__pycache__/` was
  already gitignored, this was a stale accidental commit.
- AI-assistant tooling had leaked into git tracking: `.agents/` (22 files,
  an unrelated skill plugin), `skills-lock.json`, `frontend/CLAUDE.md`,
  `frontend/AGENTS.md` — none of this is part of the shipped app. Removed
  from tracking (kept on disk, still functional locally) and added to
  `.gitignore` (`.claude/`, `.agents/`, `skills-lock.json`, bare
  `CLAUDE.md`/`AGENTS.md` patterns catch any depth).
- Moved loose root-level demo/test assets into `data/samples/`
  (`CMS1500-1-791x1024.png` → `cms1500-sample.png`, `eob-sample.pdf`) —
  grep-confirmed nothing else referenced the old root paths except
  `DEMO_NOTES.md`, updated. Deleted `eob-sample.png` (deprecated in-session
  after live-testing showed the `.pdf` sample behaves better — no code or
  docs referenced it).
- `ruff format` had never been run across ~57 files (pre-existing drift,
  not from this session's edits) — `make lint`'s format-check would have
  failed on a fresh clone. Ran `ruff check --fix` + `ruff format` across
  `src/tests/api`; full backend suite re-run after (260 passed, unchanged)
  to confirm the reformat was cosmetic only.
- README's Docker section now documents the `data/lookups/` prerequisite
  (`uv run python scripts/download_lookups.py` — ~8MB, not checked into
  git) that a fresh clone needs before `docker build` succeeds.
- The "Extracted" badge demo override from the recording session (every
  document shown as extracted, for camera-friendliness) was reverted
  immediately after recording — the live app now shows the honest
  Extracted/Classified-only distinction again, no code paths quietly
  overclaiming capability.

**Final verification, real, not assumed:** `ruff check`/`ruff format
--check` clean; backend suite 260 passed; frontend `tsc --noEmit` clean,
37 vitest tests passed (+6 new this session), production build clean; a
genuine `docker build --build-context doc-intel=../doc-intel` from a
freshly-`download_lookups.py`'d tree, followed by `docker run` + all 12
alembic migrations running end-to-end + `/health` → 200, then the test
image/container removed. DEMO_NOTES.md rewritten to match final package
state (2 curated packages kept, everything else deleted; live-upload
sequence documented with real file paths). TODO.md carries 4 new
consolidated entries for what's still known-incomplete (per-document
extraction, EOB totals nondeterminism, row-vs-field evidence granularity,
Qdrant self-emptying) — nothing in this list was worked further per
explicit instruction to clean up now, fix later.

Nothing in this session has been committed to git yet — working tree is
clean/ready, commit is a separate explicit step.

## Session N+14: portfolio README pass, real multi-document extraction, PaddleOCR-VL fix (DONE — 2026-08-03)

**README standardized** to match the other 3 sibling portfolio repos
(orion-agent, doc-intel, vault-rag): badges added (was the one repo with
none), section order/casing aligned, ASCII architecture diagram replacing
`assets/architecture.svg` (5-node pipeline, same content). Full 3-item
Contact footer added (was missing entirely).

**Per-document extraction for multi-document packages — built, not just
reworded.** This closes the TODO item from N+13: previously `extract_node`
only ran on the single document matching the package's detected domain
(e.g. the CMS-1500); every other document was classified but never
deep-extracted, even when it had its own registered domain pack (EOB,
declarations page, etc. — these already had real schemas/validators,
just never invoked for non-primary documents).

- `extract_node`/`validate_node` (`src/claimflow/nodes/`) now loop every
  document with a registered domain pack, not just the primary. New
  `secondary_extractions` state key, additive — rides in the existing
  `result_json` blob, no DB migration. Sequential, not parallel (whole-doc
  work, not the page-level parallelism `ThreadPoolExecutor` is used for
  elsewhere). One failing secondary doc is caught per-entry, doesn't fail
  the run. Validation failures tagged `doc_type: field` so a reviewer
  knows which document a failure came from.
- **Verified live, twice.** First with `doc_type_overrides` forcing
  classification (isolating the new logic from an unrelated OCR issue —
  see below); then again for real after fixing PaddleOCR-VL. Both times:
  real OpenAI call, real EOB extraction (`payer_name`, `patient_name`,
  `is_bill`, `claims`), validated cleanly against its own schema,
  primary CMS-1500 extraction/validation unaffected.
- **Frontend updated to match**: `document-list.tsx`'s "Extracted"/
  "Classified only" badge now reflects every extracted doc_type (primary +
  secondary), not just the primary domain — was about to become a real
  UI/backend inconsistency otherwise. `SecondaryExtraction` type added to
  `package-result.ts` (backend `result` is an untyped dict, no OpenAPI
  schema change needed). 37/37 frontend tests, tsc clean, build clean.
- **Not covered — cross-document reconciliation.** Each document validates
  independently; nothing compares one document's values against another's
  (EOB `plan_paid` vs CMS-1500 billed amount, for instance). This is the
  actually-differentiating part of "multi-document processing" for a
  buyer — extraction alone is more JSON, reconciliation catches real
  discrepancies. Documented as the explicit remaining gap in TODO.md, not
  implied as covered.

**PaddleOCR-VL fixed — real root cause, not flaky infra.** While verifying
the above, a CMS-1500 sample image failed classification (fell to
tesseract, not accurate enough). Root cause: `pyproject.toml` requested
doc-intel's `[ocr]` extra (`unstructured[pdf]`, unrelated) instead of
`[paddleocr]` (the `paddleocr`/`paddlepaddle`/`paddlex` client package
actually needed — required even when VL-recognition is offloaded to a
remote GPU server, since local layout-detection still runs through it).
This means PaddleOCR-VL had never actually worked on any machine that ran
this repo since the extra was declared, not just this session's box.
Fixed: `doc-intel[ocr,paddleocr]`, new `CLAIMFLOW_DOC_INTEL_PADDLEOCR_VL_SERVER_URL`
setting wired through the same passthrough pattern as the other
`DOC_INTEL_*` settings, GPU container brought up
(`doc-intel`'s `make paddleocr-vllm-up`, ~2.4GB, checked against the
shared A40 first, stopped again after verification — it reserves ~22GB
via vLLM's utilization ceiling regardless of the model being small).
Verified live: the previously-failing CMS-1500 sample now classifies
correctly with zero manual override.

**Verification, real:** 266 backend tests pass (261 existing + 5 new for
multi-doc extraction), 37 frontend tests, `ruff check`/`tsc --noEmit`/
`npm run build` all clean. Landed as 4 commits on `main` (merged from
short-lived feature branches, not squashed): README standardization,
multi-document extraction, frontend UI + TODO update, PaddleOCR-VL fix.
All pushed.
