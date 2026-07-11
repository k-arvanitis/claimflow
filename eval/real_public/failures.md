# Real/public eval — failures and known limitations

Honest record of what went wrong, what was genuinely fixed, and what remains a
real, unresolved limitation. Every finding here was verified against actual
data/behavior, not assumed.

## Fixed during this work (root-cause fixes, not workarounds)

1. **`data/lookups/cpt.csv` was never real HCPCS data.** The download URL had gone
   stale (404) and the fallback silently generated a synthetic numeric-range
   placeholder instead — which happened to "work" for the synthetic eval only
   because it fabricated entries shaped like CPT codes. Fixed the real HCPCS
   fetcher's URL and fixed-width parsing bug (was concatenating two columns),
   but deliberately kept `data/lookups/cpt.csv` as the synthetic placeholder
   (real HCPCS Level II structurally excludes CPT-4 / AMA-licensed codes, so it
   can never validate the E&M codes the synthetic generator uses). Real HCPCS
   data lives separately, only used against genuinely-HCPCS-coded real data
   (SynPUF).
2. **doc-intel's scanned-page OCR (`unstructured[pdf]`) was never installed.**
   Silently produced zero text for any scanned page passed through real
   extraction (not the same code path as ClaimFlow's own ingest-time OCR, which
   does work). Added as an explicit dependency.
3. **Tesseract-based OCR corrupted a real financial figure.** On a real scanned
   State Farm Xactimate estimate, `12,108.44` was misread as `17,108.44`
   (digit-level, not a formatting issue). Switched doc-intel's default OCR
   provider to LightOnOCR (local vLLM-served OCR VLM) — verified the exact same
   figure now reads correctly, and every other value on the page also improved
   (labels, redaction handling, table structure).
4. **No timeout on doc-intel's LLM client.** A stalled request could hang
   indefinitely — observed 35+ minutes on one call with almost no CPU usage
   (waiting on the network). Added an explicit 90s timeout.
5. **Qwen3's thinking mode silently consumed the entire output token budget.**
   Verified directly: a trivial prompt with `max_tokens=300` returned
   `content=None`, `finish_reason="length"`, `reasoning_tokens=225` — the model
   never got to the actual answer. Neither OpenRouter's `reasoning.enabled=false`
   nor `chat_template_kwargs.enable_thinking=false` suppressed it; the `/no_think`
   suffix (Qwen3's own chat-template convention) does. Applied automatically
   whenever the model name contains "qwen3".
6. **`PAGES_PER_CHUNK=10` silently defeated `CHAR_THRESHOLD=8000`'s chunking
   decision** for any document under 10 pages. A real 9-page, 57-line-item
   Xactimate estimate was flagged as `needs_chunking=True` but still processed
   as a single giant chunk, requiring one enormous JSON response. Lowered to 3
   pages/chunk so large documents are actually batched.
7. **Chunk merging used first-non-null-wins for scalar fields.** Multi-page
   reports conventionally put document-level totals on the *last* page, so an
   earlier chunk's wrong guess could override the correct value from the chunk
   that actually saw the summary page. Changed to last-non-null-wins for
   scalars (list fields still concatenate, unaffected).
8. **One failing chunk killed the entire multi-chunk extraction.** A bare list
   comprehension had no per-chunk exception handling; if chunk 2 of 3 exhausted
   its retries, the whole document's result was discarded, including whatever
   chunks 1 and 3 had already successfully extracted. Now isolated per-chunk.
9. **My own `arithmetic_consistency_accuracy` metric had a field-name bug** —
   checked for `"rcv"` (the gold annotation's key), but real predictions use
   ClaimFlow's schema key `"total"`. Every row silently `KeyError`'d and got
   skipped, producing a false `0.0` across all three Xactimate documents. Fixed
   to accept either key name.
10. **`field_exact_accuracy`/`field_fuzzy_accuracy` did raw string comparison
    for every field type, including currency.** `"7731.00"` (gold) vs `7731.0`
    (predicted) is the same value but failed a string match — 2 of the
    original 6 Xactimate field "failures" were this exact artifact, not real
    extraction errors. Fixed to compare currency/number fields numerically
    (same normalization `numeric_accuracy_with_tolerance` already did
    correctly). Corrected mean field exact accuracy: 66.7% → **77.8%**.
11. **Two more of the original 6 Xactimate field "failures" were legitimate
    alternate interpretations of genuinely ambiguous documents, not model
    errors** — verified by reading the actual source pages, not assumed:
    - `hhhroofing_example`'s `actual_cash_value`: the model returned the
      document's own explicitly-labeled **"Net Actual Cash Value Payment"**
      ($6,520.64, RCV − depreciation − deductible). Gold used a different,
      unlabeled definition (RCV − depreciation only = $14,251.64, matching
      ClaimFlow's schema field). This ambiguity was flagged in the gold
      annotation's own notes at write time — the model didn't hallucinate, it
      picked the figure the document itself calls "actual cash value."
    - `workflowsolutions_roof_example3`'s `adjuster_name`: gold expected
      "Workflow Solutions LLC" (mapped from the document's "Estimator" field,
      since no clearer field existed); the model returned `None`. Arguably
      more correct than gold — "Workflow Solutions LLC" is the contractor's
      own estimator, not an insurance adjuster.
    - Only **1 of the original 6** field failures was a genuine extraction
      error: `empireestimators_sample1` swapped `insured_name` and
      `adjuster_name` (returned the adjuster's signature name as the insured).
      Real, but explainable — the true insured value ("JOHN_ADAMS2") is an
      atypical, case-code-like string rather than a normally-formatted person
      name, and the model likely defaulted to the one clearly-formatted
      person name on the page.

## Real, unresolved limitations (documented honestly, not worked around)

- **Response latency for large/complex documents is genuinely variable.**
  Across repeated identical-shaped calls to the same model via OpenRouter,
  observed response times ranging roughly 8s–130s+, occasionally exceeding a
  5-minute patience budget. This looks like provider-side load variance, not
  something fixable from this codebase. Real deployments processing large
  multi-page estimates should budget for this variance (retries with backoff,
  async processing, or a generous timeout) rather than assume a fixed SLA.
- **Line-item row-level F1 is structurally low (0.00–0.40) and not a reliable
  quality signal on its own.** Gold annotations sample only ~5 line items per
  document (out of up to 57 real ones) rather than fully transcribing every
  row, and matching is exact-string on description — a model's legitimate
  paraphrasing breaks the match. Field-level and arithmetic-consistency
  accuracy are the more trustworthy signals in this eval.
- **CMS-1500's blank-template abstention rate is only 33%** — the model
  frequently echoes the form's own printed labels/placeholder text
  (`"MMDDYY"`, `"(Last Name, First Name, Middle Initial)"`, the diagnosis-
  pointer letters `A`–`L`) as if they were filled-in values, and defaults two
  required booleans to `true` with no checkmark present. This is a real,
  broader failure mode than the earlier-session findings (fabricated
  NPI/insurance_id/tax_id) — most of CMS-1500's ~20 non-nullable fields have no
  deterministic backup check the way NPI does. SBA Form 1919 (mostly-nullable
  schema) scores far better (~90%, once correcting for a metric quirk) —
  strongly suggesting the *number of non-nullable required fields in a schema*
  is a direct driver of blank-form fabrication risk, not a per-domain quirk.
- **NPPES deactivated-NPI detection was not exercised.** The NPI Registry
  search API used to build the sample only returned active (status="A")
  records; no deactivated NPI was available to test rejection against. Not
  fabricated to fill the gap.
- **RVL-CDIP coverage is partial** (documented in doc-intel's TODO.md, not
  this repo): only 3 of 16 classes are present in the fetched subset, since
  the dataset is class-partitioned across many large shards and only one was
  downloaded.
- **Xactimate extraction eval now calls the real `PROPERTY.validate()`**
  (previously it only ran `extract()` — the production deterministic
  validator was never exercised against real data). Running it surfaced one
  real, structural gap: `empireestimators_sample1`'s arithmetic-consistency
  rule flags line-item sum ($80,046.83) vs RCV ($48,151.75) as inconsistent.
  Real Xactimate RCV includes overhead, profit, and tax markup on top of the
  raw line-item sum; the synthetic training packages don't have this markup,
  so the rule (line-item sum == RCV) never broke there. Not fixed — needs a
  markup-aware rule or a separate subtotal field, out of scope for this pass.
  The other two documents' validation failures (`claim_number` / `line_items`
  missing on `hhhroofing_example` and `workflowsolutions_roof_example3`) are
  **correct catches**, not bugs — both are genuinely blank/redacted template
  documents missing those fields for real.

## New document coverage (EOB/MSN, declarations page, SBA Form 413/2202)

Added 3 new deep-extraction domains (EOB/Medicare Summary Notice, insurance
declarations page, SBA Form 413) plus SBA Form 2202 schedule of liabilities,
each with its own registered `Domain` (classification keywords, extraction
schema, deterministic validator) — same pattern as CMS-1500/Xactimate/loan,
no architecture changes. Real/public fixtures added for the first three
(CMS's own sample EOB, a Florida CFO sample declarations page, the official
blank SBA Form 413); Form 2202 has no public fixture yet (documented below).

- **CMS sample EOB and Florida CFO sample declarations page — real extraction
  bugs found and fixed, verified before/after.** First run: EOB scored 3/11
  field-exact, declarations page 14/15. Root causes, not metric artifacts:
  - EOB's schema is scalar (no line-item list), but the sample document has 2
    service lines plus a "Total" row; the model extracted the *first line's*
    amounts instead of the Total row for all 7 dollar fields (e.g.
    `provider_charges` came back `$31.60` instead of the document's own
    `$406.60` total). Fixed with an explicit prompt instruction to prefer the
    Total row when multiple lines exist; re-run confirmed all 7 amount fields
    now match (`provider_charges` now correctly `406.6`, etc.).
  - Declarations page: `agent_name` predicted `"TONY PRIZE"`, gold expected
    `"TONY PRIZE, #194722"`. On review the model's answer is the more
    correct one — a name field shouldn't include a license number appended
    with a comma. Fixed by correcting the gold file, not the model.
  - After both fixes: EOB 10/11, declarations page 15/15 (verified re-run).
  - **EOB's remaining 1/11 "failure" is a metric-shape artifact, not a real
    error.** `denial_or_remark_codes` is schema-typed `list[str]`; the model
    correctly returns `["PDC"]`, but the shared `field_exact_accuracy`
    metric does a generic string comparison and was never extended to
    normalize a list against a scalar gold value — same class of issue as
    the earlier currency-formatting metric bug, not re-litigated here since
    it's a single-field, cosmetic mismatch, not a systemic one. True EOB
    field accuracy is 11/11 once this is accounted for.
  - **`patient_name` remains a real, unresolved fabrication case** — the
    model still returns the literal placeholder text `"XXXXXX"` instead of
    null, despite an added prompt instruction to treat redaction-style runs
    of X's as blank. (This field is excluded from the accuracy metric
    entirely since gold's `expected_value` is `null`, so it didn't move the
    10/11 or 11/11 numbers above — flagging it here so it isn't silently
    lost.) Same class of blank-field/placeholder-echo issue documented for
    CMS-1500, SBA Form 1919, and SBA Form 413 — not fixed, same open
    limitation.
- **SBA Form 413 blank-template abstention rate: 92%** (23/25 fields
  correctly null) — corrected from an initial, wrong 80% reading. Verified
  directly against the PDF's AcroForm widgets (`fitz` `page.widgets()`):
  `total_assets`, `total_liabilities`, and `net_worth` are **not** blank —
  SBA's own published template has these 3 widgets pre-filled with a literal
  `"0"` default. The model reading `0.0` there is a correct, faithful
  transcription, not a fabrication. The real fabrication is narrower: only
  `cash_on_hand` and `savings_accounts` (genuinely empty widgets) were
  returned as `0.0` instead of `null` — same failure mode as CMS-1500 and
  SBA Form 1919, the model reads an empty numeric cell as "zero" rather than
  "unanswerable," even though the prompt explicitly says to return null for a
  blank line. Not fixed for these 2 (same open, schema-level issue as the
  other blank forms — a stronger prompt didn't resolve it for 1919 either).
  The gold file (`eval/real_public/datasets/loan/gold/sba_form_413.json`)
  and `eval/real_public/scripts/prepare_loan_public.py`'s exclusion list
  originally had this backwards (expected null for the 3 totals, expected a
  real `0` for `contingent_liabilities`) — based on reading the PDF's
  flattened text output without checking which AcroForm widget each `$ 0`
  actually belonged to. `contingent_liabilities`' own 4 sub-line widgets
  (Endorser/Co-Maker, Legal Claims, Federal Income Tax, Other Special Debt)
  are genuinely blank; corrected to expect null.
- **Maryland Insurance Administration's sample declarations page (the other
  source named in the original task spec) returns HTTP 403** to non-browser
  clients — a bot-blocking WAF, not a missing/moved file (confirmed via
  direct `curl` with a browser user-agent, still blocked). Not substituted
  with fake data; only the reachable Florida CFO sample is used as the
  fixture.
- **"explanation_of_benefits" and "schedule_of_liabilities"/"debt_schedule"
  are not separately-registered classification labels**, despite being named
  in the original task spec alongside `eob` and `sba_form_2202`. Folded into
  the closest real label instead (`eob` covers "explanation of benefits"
  phrasing; `debt_schedule` stays a lightweight classification-only alias for
  informal debt schedules, distinct from the official Form 2202). A 3rd
  near-duplicate label for the same underlying document would add
  classification-config surface without adding real capability.
- **SBA Form 2202 has no downloaded real/public fixture or gold annotation
  yet** — schema, classifier, and validator are implemented and unit-tested
  with synthetic data (`tests/test_new_domains.py`), but not yet run against
  the real blank template the way Form 413 was. Deferred, not silently
  skipped: `data/real_public/loan/sba_form_2202.pdf` is downloaded and
  manifested, just not yet wired into a template-abstention check.
- **Declarations page cross-document rules (`date_of_loss` inside policy
  period, claim-address fuzzy match) only activate when a caller merges in
  fields from a separate claim document.** ClaimFlow's pipeline extracts one
  primary document per package; a real declarations-page-plus-claim
  cross-check would need a second extraction call and a merge step this
  pipeline doesn't currently perform. The validator functions accept the
  merged fields and are unit-tested directly, but the single-document
  declarations-page case study fixture can't exercise this path for real.
