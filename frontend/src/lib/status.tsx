import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** Mirrors src/claimflow/schemas/enums.py — processing lifecycle, not the routing decision. */
export type PackageStatus =
  | "uploaded"
  | "queued"
  | "processing"
  | "review_ready"
  | "completed"
  | "processing_error"
  | "validation_error"
  | "retrieval_error";

/** Mirrors DecisionType — the routing outcome, distinct from processing status. */
export type RoutingDecision = "ready_for_processing" | "needs_review" | "blocked_or_incomplete";

const RULE_LABEL: Record<string, string> = {
  mandatory: "Missing required field",
  icd10_lookup: "Invalid diagnosis code",
  cpt_lookup: "Invalid procedure code",
  arithmetic: "Amounts don't add up",
  date_window: "Date out of range",
  not_a_bill: "Not a billing document",
  negative_amount: "Negative amount",
  positive_amount: "Amount should be positive",
  amount_consistency: "Inconsistent amounts",
  income_consistency: "Income exceeds revenue",
  acv_check: "Actual cash value mismatch",
  address_consistency: "Inconsistent address",
  signature_required: "Missing signature",
};

/** Deterministic-rule slugs (e.g. "icd10_lookup") aren't meaningful to a non-technical reviewer. */
export function ruleLabel(rule: string): string {
  return RULE_LABEL[rule] ?? rule.replace(/_/g, " ");
}

const STATUS_LABEL: Record<PackageStatus, string> = {
  uploaded: "Uploaded",
  queued: "Queued",
  processing: "Processing",
  review_ready: "Awaiting decision",
  completed: "Completed",
  processing_error: "Processing error",
  validation_error: "Validation error",
  retrieval_error: "Retrieval error",
};

const STATUS_TONE: Record<PackageStatus, "neutral" | "info" | "success" | "warning" | "danger"> = {
  uploaded: "neutral",
  queued: "neutral",
  processing: "info",
  review_ready: "warning",
  completed: "success",
  processing_error: "danger",
  validation_error: "danger",
  retrieval_error: "danger",
};

const DECISION_LABEL: Record<RoutingDecision, string> = {
  ready_for_processing: "Ready for approval",
  needs_review: "Manual review required",
  blocked_or_incomplete: "Blocked or incomplete",
};

// Same decision values mean two different things depending on who set them: a system
// recommendation is a suggestion still awaiting a human ("Ready for approval" reads
// correctly as "pending"), but once a reviewer has recorded that same value as their
// own final outcome, "Ready for approval" reads as still-pending too — misleading,
// since it's actually done. Swap in outcome-specific wording only for that case.
const RESOLVED_DECISION_LABEL: Partial<Record<RoutingDecision, string>> = {
  ready_for_processing: "Approved",
  blocked_or_incomplete: "Blocked",
};

const DECISION_TONE: Record<RoutingDecision, "success" | "warning" | "danger"> = {
  ready_for_processing: "success",
  needs_review: "warning",
  blocked_or_incomplete: "danger",
};

const TONE_CLASS: Record<string, string> = {
  neutral: "bg-secondary text-secondary-foreground",
  info: "bg-primary/10 text-primary",
  success: "bg-success/15 text-success",
  // warning-foreground is a dark color meant for the solid warning background, not
  // this translucent one — pairing them renders near-invisible dark-on-dark text.
  warning: "bg-warning/20 text-warning",
  danger: "bg-destructive/10 text-destructive",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const known = status as PackageStatus;
  const label = STATUS_LABEL[known] ?? status;
  const tone = STATUS_TONE[known] ?? "neutral";
  return (
    <Badge variant="outline" className={cn("border-transparent", TONE_CLASS[tone], className)}>
      {label}
    </Badge>
  );
}

export function DecisionBadge({
  decision,
  resolved,
  className,
}: {
  decision: string | null | undefined;
  resolved?: boolean;
  className?: string;
}) {
  if (!decision) {
    return (
      <Badge variant="outline" className={cn("border-transparent", TONE_CLASS.neutral, className)}>
        No decision
      </Badge>
    );
  }
  const known = decision as RoutingDecision;
  const label = (resolved && RESOLVED_DECISION_LABEL[known]) || DECISION_LABEL[known] || decision;
  const tone = DECISION_TONE[known] ?? "neutral";
  return (
    <Badge variant="outline" className={cn("border-transparent", TONE_CLASS[tone], className)}>
      {label}
    </Badge>
  );
}

export function ConfidenceLabel(confidence: number | null | undefined): {
  text: string;
  level: "high" | "medium" | "low" | "unknown";
} {
  if (confidence == null) return { text: "—", level: "unknown" };
  const pct = Math.round(confidence * 100);
  if (confidence >= 0.75) return { text: `${pct}%`, level: "high" };
  if (confidence >= 0.5) return { text: `${pct}%`, level: "medium" };
  return { text: `${pct}%`, level: "low" };
}

export function ConfidenceBadge({
  confidence,
  notFound = false,
}: {
  confidence: number | null | undefined;
  /** The field is genuinely absent from the document, not low-confidence — the
   * scoring formula still assigns it a validation-weight baseline (e.g. ~30%)
   * even though there's no value to be confident or unsure about, so showing
   * that percentage reads as "the system doubts this field" when it doesn't. */
  notFound?: boolean;
}) {
  if (notFound) {
    return (
      <Badge variant="outline" className={cn("border-transparent tabular-nums", TONE_CLASS.neutral)}>
        Not found
      </Badge>
    );
  }
  const { text, level } = ConfidenceLabel(confidence);
  const tone =
    level === "high" ? "success" : level === "medium" ? "warning" : level === "low" ? "danger" : "neutral";
  return (
    <Badge variant="outline" className={cn("border-transparent tabular-nums", TONE_CLASS[tone])}>
      {text}
    </Badge>
  );
}
