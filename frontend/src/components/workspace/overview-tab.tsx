"use client";

import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { StatusBadge, DecisionBadge, ConfidenceBadge } from "@/lib/status";
import { AlertTriangle, RefreshCw } from "lucide-react";
import type { ExtractionField, ValidationFailure } from "@/lib/package-result";
import type { ReviewState } from "@/components/workspace/fields-tab";

export function OverviewTab({
  status,
  systemRecommendation,
  reviewerOutcome,
  reviewerOverride,
  confidence,
  documentCount,
  fields,
  validationFailures,
  reviewed,
  ocrWarnings,
  onGoToTab,
}: {
  status: string;
  systemRecommendation: string | null;
  reviewerOutcome: string | null;
  reviewerOverride: boolean;
  confidence: number | null;
  documentCount: number;
  fields: ExtractionField[];
  validationFailures: ValidationFailure[];
  reviewed: ReviewState;
  ocrWarnings: string[];
  onGoToTab: (tab: string) => void;
}) {
  const reviewedCount = Object.keys(reviewed).length;
  const totalFields = fields.filter((f) => !f.parent_field).length;
  // Same exemption as the backend's flagged_fields (doc_intel/confidence.py score()):
  // a genuinely absent, optional field isn't a reviewer's problem, so it doesn't belong
  // in this count just because its baseline score sits below threshold — recomputed here
  // independently of the backend value, so it needs the same exclusion applied locally.
  const lowConfidence = fields.filter(
    (f) => !f.parent_field && f.confidence < 0.75 && f.field_status !== "not_found",
  );

  // "needs_review" predates reviewers losing that option (they only pick
  // Ready/Blocked now) — legacy packages can still carry it. Treat it as
  // unresolved, not a genuine reviewer outcome.
  const isResolved = reviewerOutcome === "ready_for_processing" || reviewerOutcome === "blocked_or_incomplete";

  return (
    <div className="flex flex-col gap-4">
      <div className="@container">
        <div className="grid grid-cols-2 gap-3 @2xl:grid-cols-4">
          <div className="min-w-0 rounded-md border p-3">
            <div className="text-xs text-muted-foreground">Status</div>
            <StatusBadge status={status} className="mt-1" />
          </div>
          <div className="min-w-0 rounded-md border p-3">
            <div className="text-xs text-muted-foreground">Outcome</div>
            {isResolved ? (
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <DecisionBadge decision={reviewerOutcome} resolved />
                {reviewerOverride && <span className="text-xs text-muted-foreground">(overrode system)</span>}
              </div>
            ) : (
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <DecisionBadge decision={systemRecommendation} />
                {systemRecommendation && <span className="text-xs text-muted-foreground">(pending review)</span>}
              </div>
            )}
          </div>
          <div className="min-w-0 rounded-md border p-3">
            <div className="text-xs text-muted-foreground">Confidence</div>
            <ConfidenceBadge confidence={confidence} />
          </div>
          <div className="min-w-0 rounded-md border p-3">
            <div className="text-xs text-muted-foreground">Documents</div>
            <div className="text-lg font-semibold tabular-nums">{documentCount}</div>
          </div>
          <div className="min-w-0 rounded-md border p-3">
            <div className="text-xs text-muted-foreground">Fields</div>
            <div className="text-lg font-semibold tabular-nums">{totalFields}</div>
          </div>
          <div className="min-w-0 rounded-md border p-3">
            <div className="text-xs text-muted-foreground">Validation failures</div>
            <div className="text-lg font-semibold tabular-nums">{validationFailures.length}</div>
          </div>
          <div className="min-w-0 rounded-md border p-3">
            <div className="text-xs text-muted-foreground">Low-confidence fields</div>
            <div className="text-lg font-semibold tabular-nums">{lowConfidence.length}</div>
          </div>
          <div className="min-w-0 rounded-md border p-3">
            <div className="text-xs text-muted-foreground">Review progress</div>
            <div className="text-lg font-semibold tabular-nums">
              {reviewedCount}/{totalFields}
            </div>
          </div>
        </div>
      </div>

      {ocrWarnings.length > 0 && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>Low-quality scan detected</AlertTitle>
          <AlertDescription>{ocrWarnings.join(" ")}</AlertDescription>
        </Alert>
      )}

      {validationFailures.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Next actions</h3>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => onGoToTab("fields")}>
              Review flagged fields
            </Button>
            <Button variant="outline" size="sm" onClick={() => onGoToTab("validation")}>
              <RefreshCw data-icon="inline-start" />
              Re-run validation
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
