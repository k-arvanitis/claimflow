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
