/** PackageDetailResponse.result is `dict[str, Any]` in the backend (schemas/packages.py) —
 * this mirrors the actual ClaimState shape returned by the graph (verified against a live
 * package run), since FastAPI doesn't give us a typed OpenAPI shape for it. */
export type FieldEvidence = {
  page: number | null;
  text: string | null;
  bbox: [number, number, number, number] | null;
  block_type: string | null;
};

export type ExtractionField = {
  name: string;
  value: unknown;
  confidence: number;
  grounded: boolean;
  valid: boolean;
  evidence: FieldEvidence | null;
  field_status: "found" | "not_found" | string;
  parent_field?: string | null;
};

export type ValidationFailure = {
  field: string;
  rule: string;
  reason: string;
};

export type PolicyAnswer = {
  question: string;
  answer: string;
  citations: string[];
};

export type PackageDocumentResult = {
  filename: string;
  doc_type: string;
  has_text_layer: boolean;
  scan_quality: number | null;
  classification_reason: string | null;
};

export type PackageResult = {
  decision: "approved" | "flagged" | "escalated" | null;
  extraction_data: Record<string, unknown> | null;
  domain: string | null;
  documents: PackageDocumentResult[];
  ocr_log: unknown[];
  extraction_overall_confidence: number | null;
  extraction_fields: ExtractionField[];
  validation_failures: ValidationFailure[];
  policy_answers: PolicyAnswer[];
  review_reasons: string[];
  error: string | null;
};
