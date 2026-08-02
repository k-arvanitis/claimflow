"use client";

import { useState } from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertTriangle } from "lucide-react";
import { useRecordDecision } from "@/lib/queries";
import { toast } from "sonner";

type PendingDecision = "ready_for_processing" | "needs_review" | "blocked_or_incomplete" | null;

const DECISION_LABEL: Record<Exclude<PendingDecision, null>, string> = {
  ready_for_processing: "Approved",
  needs_review: "Manual review required",
  blocked_or_incomplete: "Blocked",
};

export function DecisionDialog({
  packageId,
  pending,
  onClose,
  unresolvedFailureCount,
  status,
  currentDecision,
}: {
  packageId: string;
  pending: PendingDecision;
  onClose: () => void;
  unresolvedFailureCount: number;
  status: string;
  currentDecision: string | null;
}) {
  const [reason, setReason] = useState("");
  const record = useRecordDecision(packageId);

  // Blocking a package always needs a reason; overriding the system's recommendation
  // only needs a warning, not a forced explanation.
  const isOverride = pending !== null && currentDecision !== null && pending !== currentDecision;
  const requiresReason = pending === "blocked_or_incomplete";
  const showOverrideWarning = pending === "ready_for_processing" && isOverride;
  const showFailureWarning = pending === "ready_for_processing" && unresolvedFailureCount > 0;
  const showIncompleteWarning =
    pending === "ready_for_processing" && status !== "review_ready" && status !== "completed";

  return (
    <AlertDialog open={pending !== null} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {pending === "ready_for_processing" && "Approve this package?"}
            {pending === "needs_review" && "Send this package for manual review?"}
            {pending === "blocked_or_incomplete" && "Block this package?"}
          </AlertDialogTitle>
          <AlertDialogDescription>
            This records your decision. It doesn&apos;t change any extracted data or validation results.
          </AlertDialogDescription>
        </AlertDialogHeader>

        {showOverrideWarning && (
          <Alert variant="destructive">
            <AlertTriangle />
            <AlertTitle>Overriding system recommendation</AlertTitle>
            <AlertDescription>The system recommended &quot;Manual review required&quot; for this package.</AlertDescription>
          </Alert>
        )}
        {showFailureWarning && (
          <Alert variant="destructive">
            <AlertTriangle />
            <AlertTitle>Unresolved validation failures</AlertTitle>
            <AlertDescription>
              {unresolvedFailureCount} validation failure{unresolvedFailureCount === 1 ? "" : "s"} remain unresolved.
            </AlertDescription>
          </Alert>
        )}
        {showIncompleteWarning && (
          <Alert variant="destructive">
            <AlertTriangle />
            <AlertTitle>Processing incomplete</AlertTitle>
            <AlertDescription>This package has not finished processing yet.</AlertDescription>
          </Alert>
        )}

        {requiresReason && (
          <Textarea
            placeholder="Reason for blocking (required)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        )}

        <AlertDialogFooter>
          <AlertDialogCancel onClick={onClose}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={requiresReason && reason.trim().length === 0}
            onClick={async () => {
              if (!pending) return;
              try {
                await record.mutateAsync({
                  decision: pending,
                  reviewReasons: reason.trim() ? [reason.trim()] : [],
                });
                toast.success(`Package ${DECISION_LABEL[pending]}`);
                onClose();
                setReason("");
              } catch {
                toast.error("Could not record decision");
              }
            }}
          >
            Confirm
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
