"use client";

import { BookOpen } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import { usePolicyEvidence } from "@/lib/queries";
import { ChevronDown } from "lucide-react";

export function PolicyTab({ packageId }: { packageId: string }) {
  const { data, isLoading } = usePolicyEvidence(packageId);

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
      <Empty className="py-12">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <BookOpen />
          </EmptyMedia>
          <EmptyTitle>No policy support retrieved</EmptyTitle>
          <EmptyDescription>
            Policy evidence is only retrieved for packages with validation failures.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        Cited policy support for failed validation rules — secondary to the deterministic validation result, not a
        substitute for it.
      </p>
      {data.map((item, i) => (
        <Card key={i}>
          <CardHeader>
            <CardTitle className="text-sm font-normal text-muted-foreground">{item.question}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <p className="text-sm">{item.answer}</p>
            <Collapsible>
              <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:underline">
                <ChevronDown className="size-3" />
                Technical details ({item.citations.length} citation{item.citations.length === 1 ? "" : "s"})
              </CollapsibleTrigger>
              <CollapsibleContent className="pt-2 text-xs text-muted-foreground">
                {item.citations.map((c, j) => (
                  <div key={j}>{String(c)}</div>
                ))}
              </CollapsibleContent>
            </Collapsible>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
