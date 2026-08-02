"use client";

import { History } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuditTrail } from "@/lib/queries";

// ponytail: one-liner per action we know about; unrecognized actions fall back to the raw badge, no config needed.
function summarize(action: string, detail: unknown): string | null {
  const d = (detail ?? {}) as Record<string, unknown>;
  switch (action) {
    case "upload":
      return `Uploaded ${Array.isArray(d.filenames) ? d.filenames.length : ""} document(s)`.trim();
    case "status_transition":
      return `Status changed from ${d.from ?? "?"} to ${d.to ?? "?"}`;
    case "review_edit":
    case "review_approve":
    case "review_reject":
      return d.field ? `Field ${String(d.field)} ${action === "review_edit" ? "corrected" : action === "review_reject" ? "marked unresolved" : "confirmed"}` : null;
    case "validation_rerun":
      return `Validation re-run — decision now ${d.decision ?? "?"}`;
    case "decision":
      return `Reviewer recorded decision: ${d.decision ?? "?"}`;
    case "reclassify":
      return d.doc_type ? `Document reclassified as ${String(d.doc_type)}` : null;
    default:
      return null;
  }
}

export function AuditTab({ packageId }: { packageId: string }) {
  const { data, isLoading } = useAuditTrail(packageId);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-10" />
        ))}
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <Empty className="py-12">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <History />
          </EmptyMedia>
          <EmptyTitle>No audit events yet</EmptyTitle>
          <EmptyDescription>Events appear as the package is processed and reviewed.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        Application-level workflow audit trail — not compliance-grade tamper-evident logging.
      </p>
      <ol className="flex flex-col gap-2 border-l pl-4">
        {data.map((event, i) => {
          const summary = summarize(event.action, event.detail);
          return (
            <li key={i} className="relative pb-2">
              <span className="absolute -left-[21px] top-1 size-2 rounded-full bg-primary" />
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{event.action}</Badge>
                {event.actor !== "api" && (
                  <span className="text-xs text-muted-foreground">{event.actor}</span>
                )}
                <span className="text-xs text-muted-foreground">{new Date(event.timestamp).toLocaleString()}</span>
              </div>
              {summary && <p className="mt-1 text-sm">{summary}</p>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
