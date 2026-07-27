"use client";

import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { StatusBadge, DecisionBadge, ConfidenceBadge } from "@/lib/status";
import { AlertTriangle, RefreshCw, Gavel } from "lucide-react";
import type { ExtractionField, ValidationFailure } from "@/lib/package-result";
import type { ReviewState } from "@/components/workspace/fields-tab";

export function OverviewTab({
  status,
  decision,
  confidence,
  documentCount,
  fields,
  validationFailures,
  reviewed,
  ocrWarnings,
  onGoToTab,
  onRecordDecision,
}: {
  status: string;
  decision: string | null;
  confidence: number | null;
  documentCount: number;
  fields: ExtractionField[];
  validationFailures: ValidationFailure[];
  reviewed: ReviewState;
  ocrWarnings: string[];
  onGoToTab: (tab: string) => void;
  onRecordDecision: (decision: "ready_for_processing" | "needs_review" | "blocked_or_incomplete") => void;
}) {
  const reviewedCount = Object.keys(reviewed).length;
  const totalFields = fields.filter((f) => !f.parent_field).length;
  const lowConfidence = fields.filter((f) => !f.parent_field && f.confidence < 0.75);

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-md border p-3">
          <div className="text-xs text-muted-foreground">Status</div>
          <StatusBadge status={status} className="mt-1" />
        </div>
        <div className="rounded-md border p-3">
          <div className="text-xs text-muted-foreground">Decision</div>
          <DecisionBadge decision={decision} className="mt-1" />
        </div>
        <div className="rounded-md border p-3">
          <div className="text-xs text-muted-foreground">Confidence</div>
          <ConfidenceBadge confidence={confidence} />
        </div>
        <div className="rounded-md border p-3">
          <div className="text-xs text-muted-foreground">Documents</div>
          <div className="text-lg font-semibold tabular-nums">{documentCount}</div>
        </div>
        <div className="rounded-md border p-3">
          <div className="text-xs text-muted-foreground">Fields</div>
          <div className="text-lg font-semibold tabular-nums">{totalFields}</div>
        </div>
        <div className="rounded-md border p-3">
          <div className="text-xs text-muted-foreground">Validation failures</div>
          <div className="text-lg font-semibold tabular-nums">{validationFailures.length}</div>
        </div>
        <div className="rounded-md border p-3">
          <div className="text-xs text-muted-foreground">Low-confidence fields</div>
          <div className="text-lg font-semibold tabular-nums">{lowConfidence.length}</div>
        </div>
        <div className="rounded-md border p-3">
          <div className="text-xs text-muted-foreground">Review progress</div>
          <div className="text-lg font-semibold tabular-nums">
            {reviewedCount}/{totalFields}
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

      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-medium">Next actions</h3>
        <div className="flex flex-wrap gap-2">
          {validationFailures.length > 0 && (
            <Button variant="outline" size="sm" onClick={() => onGoToTab("fields")}>
              Review flagged fields
            </Button>
          )}
          {validationFailures.length > 0 && (
            <Button variant="outline" size="sm" onClick={() => onGoToTab("validation")}>
              <RefreshCw data-icon="inline-start" />
              Re-run validation
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => onRecordDecision("ready_for_processing")}>
            <Gavel data-icon="inline-start" />
            Record decision
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">Export is available from the header at any time.</p>
      </div>
    </div>
  );
}
