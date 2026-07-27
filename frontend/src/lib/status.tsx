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
export type RoutingDecision = "approved" | "flagged" | "escalated";

const STATUS_LABEL: Record<PackageStatus, string> = {
  uploaded: "Uploaded",
  queued: "Queued",
  processing: "Processing",
  review_ready: "Ready for review",
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
  approved: "Approved",
  flagged: "Flagged",
  escalated: "Escalated",
};

const DECISION_TONE: Record<RoutingDecision, "success" | "warning" | "danger"> = {
  approved: "success",
  flagged: "warning",
  escalated: "danger",
};

const TONE_CLASS: Record<string, string> = {
  neutral: "bg-secondary text-secondary-foreground",
  info: "bg-primary/10 text-primary",
  success: "bg-success/15 text-success",
  warning: "bg-warning/20 text-warning-foreground",
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

export function DecisionBadge({ decision, className }: { decision: string | null | undefined; className?: string }) {
  if (!decision) {
    return (
      <Badge variant="outline" className={cn("border-transparent", TONE_CLASS.neutral, className)}>
        No decision
      </Badge>
    );
  }
  const known = decision as RoutingDecision;
  const label = DECISION_LABEL[known] ?? decision;
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

export function ConfidenceBadge({ confidence }: { confidence: number | null | undefined }) {
  const { text, level } = ConfidenceLabel(confidence);
  const tone =
    level === "high" ? "success" : level === "medium" ? "warning" : level === "low" ? "danger" : "neutral";
  return (
    <Badge variant="outline" className={cn("border-transparent tabular-nums", TONE_CLASS[tone])}>
      {text}
    </Badge>
  );
}
