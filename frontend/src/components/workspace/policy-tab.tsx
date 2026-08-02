"use client";

import { BookOpen } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import { usePolicyEvidence } from "@/lib/queries";
import { ChevronRight } from "lucide-react";
import type { ValidationFailure } from "@/lib/package-result";
import { ruleLabel } from "@/lib/status";

export function PolicyTab({
  packageId,
  validationFailures = [],
}: {
  packageId: string;
  validationFailures?: ValidationFailure[];
}) {
  const { data, isLoading } = usePolicyEvidence(packageId);
  const notRequired = validationFailures.filter((f) => !f.policy_required);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        {Array.from({ length: 2 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="flex flex-col gap-3">
        <Empty className="py-12">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BookOpen />
            </EmptyMedia>
            <EmptyTitle>No policy support retrieved</EmptyTitle>
            <EmptyDescription>
              Policy evidence is only retrieved for validation failures that depend on written guidance — a
              checksum, arithmetic, or missing-field failure does not trigger a policy lookup.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
        {notRequired.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {notRequired.map((f, i) => (
              <Badge key={i} variant="secondary" title={f.reason}>
                {f.field} ({ruleLabel(f.rule)}) — no policy lookup needed
              </Badge>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        Cited policy support for failed validation rules — secondary to the deterministic validation result, not a
        substitute for it.
      </p>
      {notRequired.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {notRequired.map((f, i) => (
            <Badge key={i} variant="secondary" title={f.reason}>
              {f.field} ({ruleLabel(f.rule)}) — no policy lookup needed
            </Badge>
          ))}
        </div>
      )}
      {data.map((item, i) => {
        const notFound = item.status === "not_found";
        return (
          <Card key={i} className={notFound ? "border-warning/40" : undefined}>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                {item.field && (
                  <p className="text-xs font-medium text-muted-foreground">
                    Supports validation finding: <span className="font-mono">{item.field}</span>
                    {item.rule ? ` (${item.rule})` : ""}
                  </p>
                )}
                <Badge variant="outline" className={notFound ? "border-warning text-warning" : "border-success text-success"}>
                  {notFound ? "Not found in corpus" : "Found"}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              <p className="text-sm">{item.answer}</p>
              {!notFound && (
                <Collapsible>
                  <CollapsibleTrigger className="group flex items-center gap-1 text-xs text-muted-foreground hover:underline">
                    <ChevronRight className="size-3 transition-transform group-data-[state=open]:rotate-90" />
                    Technical details ({item.citations.length} citation{item.citations.length === 1 ? "" : "s"})
                  </CollapsibleTrigger>
                  <CollapsibleContent className="pt-2 text-xs text-muted-foreground">
                    {item.citations.map((c, j) => (
                      <div key={j}>{String(c)}</div>
                    ))}
                  </CollapsibleContent>
                </Collapsible>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
