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

type PendingDecision = "approved" | "flagged" | "escalated" | null;

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

  const requiresReason = pending === "escalated";
  const showFailureWarning = pending === "approved" && unresolvedFailureCount > 0;
  const showIncompleteWarning = pending === "approved" && status !== "review_ready" && status !== "completed";

  return (
    <AlertDialog open={pending !== null} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {pending === "approved" && "Approve this package?"}
            {pending === "flagged" && "Flag this package for review?"}
            {pending === "escalated" && "Escalate this package?"}
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
            placeholder="Reason for escalation (required)"
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
                toast.success(`Package ${pending}`);
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
