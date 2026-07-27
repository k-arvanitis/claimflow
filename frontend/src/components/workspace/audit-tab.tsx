"use client";

import { History } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuditTrail } from "@/lib/queries";

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
        {data.map((event, i) => (
          <li key={i} className="relative pb-2">
            <span className="absolute -left-[21px] top-1 size-2 rounded-full bg-primary" />
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">{event.action}</Badge>
              <span className="text-xs text-muted-foreground">{event.actor}</span>
              <span className="text-xs text-muted-foreground">{new Date(event.timestamp).toLocaleString()}</span>
            </div>
            {event.detail != null && (
              <pre className="mt-1 max-w-full overflow-x-auto rounded bg-muted p-2 text-xs text-muted-foreground">
                {JSON.stringify(event.detail, null, 2)}
              </pre>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
