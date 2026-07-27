"use client";

import { useState } from "react";
import { Download, RefreshCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
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
import { StatusBadge, DecisionBadge, ConfidenceBadge } from "@/lib/status";
import { API_BASE_URL } from "@/lib/api";
import { useDeletePackage, useReprocessPackage } from "@/lib/queries";
import { toast } from "sonner";
import { useRouter } from "next/navigation";

export function PackageHeader({
  packageId,
  status,
  decision,
  confidence,
  documentCount,
  failureCount,
  createdAt,
  updatedAt,
  onRecordDecision,
}: {
  packageId: string;
  status: string;
  decision: string | null;
  confidence: number | null;
  documentCount: number;
  failureCount: number;
  createdAt: string;
  updatedAt: string;
  onRecordDecision: (decision: "ready_for_processing" | "needs_review" | "blocked_or_incomplete") => void;
}) {
  const router = useRouter();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const reprocess = useReprocessPackage(packageId);
  const remove = useDeletePackage();

  return (
    <div className="flex flex-col gap-3 border-b bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-sm">{packageId}</span>
          <StatusBadge status={status} />
          <DecisionBadge decision={decision} />
          <ConfidenceBadge confidence={confidence} />
          <span className="text-xs text-muted-foreground">
            {documentCount} document{documentCount === 1 ? "" : "s"} · {failureCount} validation failure
            {failureCount === 1 ? "" : "s"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={async () => {
              try {
                await reprocess.mutateAsync();
                toast.success("Reprocessing started");
              } catch {
                toast.error("Could not start reprocessing");
              }
            }}
            disabled={reprocess.isPending}
          >
            <RefreshCw className={reprocess.isPending ? "animate-spin" : ""} data-icon="inline-start" />
            Reprocess
          </Button>
          <Button variant="outline" size="sm" onClick={() => window.open(`${API_BASE_URL}/packages/${packageId}/export`, "_blank")}>
            <Download data-icon="inline-start" />
            Export
          </Button>
          <Separator orientation="vertical" className="h-6" />
          <Button variant="outline" size="sm" className="border-success text-success hover:bg-success/10" onClick={() => onRecordDecision("ready_for_processing")}>
            Ready for processing
          </Button>
          <Button variant="outline" size="sm" className="border-warning text-warning-foreground hover:bg-warning/10" onClick={() => onRecordDecision("needs_review")}>
            Needs review
          </Button>
          <Button variant="outline" size="sm" className="border-destructive text-destructive hover:bg-destructive/10" onClick={() => onRecordDecision("blocked_or_incomplete")}>
            Blocked
          </Button>
          <Button variant="ghost" size="icon" aria-label="Delete package" onClick={() => setConfirmDelete(true)}>
            <Trash2 />
          </Button>
        </div>
      </div>
      <div className="text-xs text-muted-foreground">
        Created {new Date(createdAt).toLocaleString()} · Updated {new Date(updatedAt).toLocaleString()}
      </div>

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this package?</AlertDialogTitle>
            <AlertDialogDescription>
              This removes the package, its documents, fields, validation failures and decisions. Its audit trail
              is kept.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                try {
                  await remove.mutateAsync(packageId);
                  toast.success("Package deleted");
                  router.push("/packages");
                } catch {
                  toast.error("Could not delete package");
                }
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
