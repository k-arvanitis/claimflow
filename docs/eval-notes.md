# Eval debugging notes

Root-cause detail behind the synthetic 3-domain eval numbers in the README. These numbers reflect a debugging pass, not just model performance — the eval process itself surfaced and fixed several real issues along the way:

- Schema gaps: health was missing `patient_city`/`state`/`zip`; several fields across domains were non-nullable, structurally forcing the model to fabricate a value instead of returning null for a blank field.
- A currency-comparison bug and a None-vs-empty-string bug in the eval script itself.
- A non-deterministic extraction pipeline (no `temperature` control).
- A coarse source-evidence bounding box on dense forms — the PDF parser treated CMS-1500's outer border as one giant table.
- Several prompt/schema fixes for ID-field extraction.
- Deterministic placeholder-pattern checks for `tax_id`/`applicant_name`/`claim_number`/NPI — each catches a real, generalizable pattern (not a real value, or not a real format) rather than trusting the model's self-report.
- Two retired ICD-10 codes (`M54.5`, `K21.0`) baked into the synthetic data generator's "valid code" pool.
- A set of placeholder-style NPI values (`1234567890`, `0987654321`, etc.) in the generator's own "valid" pool that a real-world system would treat as suspicious — same class of issue as the retired codes, fixed the same way.

Straight-through rates below 50% are not a regression — catch rate rose alongside them, meaning the pipeline now correctly flags packages it previously waved through undetected.

**`temperature=0` doesn't fully guarantee run-to-run reproducibility** — see [Known limitations](../README.md#known-limitations) for the verified finding.

## Health false-positive rate — root cause

Health's false-positive rate was a real, verified finding, not a bug — now fixed at the source. The ICD-10 lookup is the current, full 74,720-code CMS list. The synthetic health data generator's pool of "valid" diagnosis codes included `M54.5` and `K21.0`, both parent codes retired in the 2021 ICD-10-CM revision in favor of specific subcodes (`M54.50`, `K21.00`). The model extracted them correctly; the deterministic validator correctly flagged them as not currently billable — the validation layer was doing its job. Fixed by correcting the generator's code pool (`M54.50`, `K21.00`) and regenerating the dataset: false-positive rate dropped from 44.4% to 0.0%.
