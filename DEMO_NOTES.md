# Demo session notes

## Connect

```
ssh -L 8010:localhost:8010 -L 3001:localhost:3001 karvanitis@ai.lmids.sse.gr
```

Then open `http://localhost:3001` in your browser.

Backend runs on 8010, frontend dev server on 3001 (port picks the next free
one — check the frontend terminal output if it ever differs, and adjust the
`-L` flag to match).

## Before recording

1. `curl localhost:6339/collections` — if `{"result":{"collections":[]}}`
   (empty), Qdrant lost its seeded data (happened repeatedly across sessions,
   cause not identified — looks external to the app, see TODO.md). Reseed:
   ```
   cd ~/claimflow && uv run python scripts/seed_qdrant.py
   ```
2. Confirm both servers respond:
   ```
   curl localhost:8010/health
   curl -o /dev/null -w "%{http_code}\n" localhost:3001
   ```
3. Local demo files (download once, browser runs on your laptop, files live on the dev box):
   ```
   scp karvanitis@ai.lmids.sse.gr:/home/karvanitis/claimflow/data/synthetic/health/package_008/claim.pdf ~/Desktop/demo/cms1500.pdf
   scp karvanitis@ai.lmids.sse.gr:/home/karvanitis/claimflow/data/samples/eob-sample.pdf ~/Desktop/demo/eob.pdf
   ```
   `package_008` has a seeded invalid ICD-10 code (`XXXXX`) plus a bad NPI —
   both are policy-required validation failures, real CMS citations retrieved.

## Demo packages already live in the app

| Package ID | Domain | Status | What it shows |
|---|---|---|---|
| `92c113d6-1b7c-49d3-8928-80c2755a9e2c` | CMS-1500 | completed, approved | **Clean, already-reviewed claim** — 93% confidence, 0 failures, decision recorded. Use for the export flow or to show the "Reviewed: Approved" label. |
| `67b2d462-7a30-4c72-b95f-763900da7278` | CMS-1500 | completed | Second clean claim, undecided — variety / client-search demo. |

Everything else from earlier sessions was deleted for a clean recording state
— the live-upload flow (below) recreates the flagged/multi-doc scenarios on
camera instead of relying on pre-seeded packages.

## What's real vs. not yet built (don't overclaim on camera)

- Multi-document packages: classification works for every document; **only
  the package's primary document type gets deep field extraction**. A
  secondary document (e.g. an EOB alongside a CMS-1500) shows "Classified
  only" — recognized, not extracted. See TODO.md's "Per-document extraction"
  entry for the real fix.
- EOB extraction (as its own package, not combined) is fully built and
  tested — multi-claim schema, real bbox evidence, validated live. Worth
  mentioning verbally if asked, without demoing it live unless planned.
- No staged processing progress bar (upload → OCR → extract → validate...)
  — status badge + spinner while processing, button disabled until ready.
- Docker image builds and runs for real (`docker build --build-context
  doc-intel=../doc-intel -t claimflow .`) — verified with a real `docker run`
  + `/health` check. See README's Docker section for the `download_lookups.py`
  prerequisite (ICD-10/CPT data isn't checked into git).
- Full eval numbers are real and current (98.8% / 99.6% / 98.0% field
  accuracy across health/property/loan, 100% citation rate, 0% false
  positives) — see README's Eval section.

## Recording sequence

1. **New package** → CMS-1500 Claim Review → upload `cms1500.pdf` + `eob.pdf`
   together. Point out both get classified automatically; only the CMS-1500
   gets deep extraction. Button stays disabled with a spinner until
   processing finishes (~30-90s) — no empty workspace wait.
2. Fields tab — click evidence on a found field (red box on the PDF), point
   at a `Not found` field showing a neutral badge instead of a misleading
   confidence percentage.
3. Validation tab — the seeded ICD-10 + NPI failures, both policy-required.
4. Policy evidence tab — real CMS manual citation grounding the ICD-10 flag.
5. Decision — Block (it's a real error) or correct the field and re-run
   validation to show the decision changing live. Audit tab shows a clean
   one-line summary of what just happened, no raw JSON.
6. Packages queue — search by client name, click a client name to filter to
   their history, "Export filtered (Excel)" for a multi-package workbook.
7. Open `92c113d6` — "Reviewed: Approved" label, Export → JSON/Excel.
