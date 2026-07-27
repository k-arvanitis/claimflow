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
  ready_for_processing: "Ready for processing",
  needs_review: "Needs manual review",
  blocked_or_incomplete: "Blocked or incomplete",
};

export function DecisionDialog({
  packageId,
  pending,
  onClose,
  unresolvedFailureCount,
  status,
}: {
  packageId: string;
  pending: PendingDecision;
  onClose: () => void;
  unresolvedFailureCount: number;
  status: string;
}) {
  const [reason, setReason] = useState("");
  const record = useRecordDecision(packageId);

  const requiresReason = pending === "blocked_or_incomplete";
  const showFailureWarning = pending === "ready_for_processing" && unresolvedFailureCount > 0;
  const showIncompleteWarning =
    pending === "ready_for_processing" && status !== "review_ready" && status !== "completed";

  return (
    <AlertDialog open={pending !== null} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {pending === "ready_for_processing" && "Mark this package ready for processing?"}
            {pending === "needs_review" && "Send this package for manual review?"}
            {pending === "blocked_or_incomplete" && "Mark this package blocked or incomplete?"}
          </AlertDialogTitle>
          <AlertDialogDescription>
            This records a routing decision. The backend remains the final authority — recording a decision does
            not change extracted data or validation results.
          </AlertDialogDescription>
        </AlertDialogHeader>

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
