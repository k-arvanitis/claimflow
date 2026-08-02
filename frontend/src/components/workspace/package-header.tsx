"use client";

import { useEffect, useState } from "react";
import { Download, RefreshCw, Trash2, Undo2 } from "lucide-react";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { StatusBadge, DecisionBadge, ConfidenceBadge } from "@/lib/status";
import { downloadPackageExport, downloadPackageExportExcel } from "@/lib/api";
import { useDeletePackage, useReprocessPackage } from "@/lib/queries";
import { toast } from "sonner";
import { useRouter } from "next/navigation";

// ponytail: elapsed-time label, not a real per-stage stepper — the backend doesn't
// persist which pipeline node is running. Upgrade to a true stepper if a demo needs to
// show ingest/extract/validate/retrieve progress rather than just "still working".
function ProcessingElapsed({ since }: { since: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  // The API returns naive timestamps (no "Z"/offset) that are actually UTC — without
  // this, `new Date(since)` parses them as local time and skews the elapsed count by
  // the browser's UTC offset.
  const sinceUtc = /[Zz]|[+-]\d\d:\d\d$/.test(since) ? since : `${since}Z`;
  const seconds = Math.max(0, Math.floor((now - new Date(sinceUtc).getTime()) / 1000));
  const label = seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return <span className="text-xs tabular-nums text-muted-foreground">Processing… ({label})</span>;
}

export function PackageHeader({
  packageId,
  workflowName,
  status,
  decision,
  reviewerOutcome,
  confidence,
  documentCount,
  failureCount,
  createdAt,
  updatedAt,
  onRecordDecision,
}: {
  packageId: string;
  workflowName?: string;
  status: string;
  decision: string | null;
  reviewerOutcome: string | null;
  confidence: number | null;
  documentCount: number;
  failureCount: number;
  createdAt: string;
  updatedAt: string;
  onRecordDecision: (decision: "ready_for_processing" | "needs_review" | "blocked_or_incomplete") => void;
}) {
  const router = useRouter();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [revisiting, setRevisiting] = useState(false);
  const reprocess = useReprocessPackage(packageId);
  const remove = useDeletePackage();

  // "needs_review" is no longer a reviewer-selectable outcome (the reviewer picking
  // "needs more review" while they're the one reviewing it made no sense) — it only
  // still shows up here on packages decided before that change. Treat it as not
  // actually resolved, not as a real "Reviewed:" state.
  const isResolved = reviewerOutcome === "ready_for_processing" || reviewerOutcome === "blocked_or_incomplete";

  // Adjust state during render (React's documented pattern for resetting state when a
  // prop changes) rather than in an Effect — once a new outcome lands, drop back out
  // of "revisit" mode so the badge shows again.
  const [prevOutcome, setPrevOutcome] = useState(reviewerOutcome);
  if (reviewerOutcome !== prevOutcome) {
    setPrevOutcome(reviewerOutcome);
    if (revisiting) setRevisiting(false);
  }

  return (
    <div className="flex flex-col gap-3 border-b bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          {workflowName && <span className="font-semibold">{workflowName}</span>}
          <span className="font-mono text-xs text-muted-foreground">{packageId}</span>
          <StatusBadge status={status} />
          {status === "processing" && <ProcessingElapsed since={updatedAt} />}
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
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <Download data-icon="inline-start" />
                Export
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onClick={async () => {
                  try {
                    await downloadPackageExport(packageId);
                  } catch {
                    toast.error("Could not export package");
                  }
                }}
              >
                JSON
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={async () => {
                  try {
                    await downloadPackageExportExcel(packageId);
                  } catch {
                    toast.error("Could not export package");
                  }
                }}
              >
                Excel
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button variant="ghost" size="icon" aria-label="Delete package" title="Delete package" onClick={() => setConfirmDelete(true)}>
            <Trash2 />
          </Button>
          <Separator orientation="vertical" className="h-6" />
          {isResolved && !revisiting ? (
            <>
              <span className="text-xs text-muted-foreground">Reviewed:</span>
              <DecisionBadge decision={reviewerOutcome} resolved />
              <Button variant="ghost" size="sm" onClick={() => setRevisiting(true)}>
                <Undo2 data-icon="inline-start" />
                Revisit
              </Button>
            </>
          ) : (
            <>
              <span className="text-xs text-muted-foreground">Your decision:</span>
              <Button
                variant="outline"
                size="sm"
                className="border-success text-success hover:bg-success/10"
                onClick={() => onRecordDecision("ready_for_processing")}
              >
                Approve package
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="border-destructive text-destructive hover:bg-destructive/10"
                onClick={() => onRecordDecision("blocked_or_incomplete")}
              >
                Block package
              </Button>
              {revisiting && (
                <Button variant="ghost" size="sm" onClick={() => setRevisiting(false)}>
                  Cancel
                </Button>
              )}
            </>
          )}
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
