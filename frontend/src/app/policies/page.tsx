"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FileText } from "lucide-react";
import { API_BASE_URL } from "@/lib/api";
import { usePolicies } from "@/lib/queries";

const POLICY_DOMAINS = ["health", "property", "loan"] as const;
const POLICY_DOMAIN_LABELS: Record<string, string> = {
  health: "CMS-1500 Health Claim",
  property: "Property Insurance (Xactimate)",
  loan: "SBA Loan Application",
};

function ViewPolicyDialog({ filename, onClose }: { filename: string | null; onClose: () => void }) {
  return (
    <Dialog open={filename !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex h-[95vh] w-[95vw] !max-w-[95vw] flex-col">
        <DialogHeader>
          <DialogTitle className="truncate">{filename}</DialogTitle>
        </DialogHeader>
        {filename && (
          <iframe
            src={`${API_BASE_URL}/policies/${encodeURIComponent(filename)}/file`}
            className="flex-1 rounded-md border"
            title={filename}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function PoliciesPage() {
  const { data: policies, isLoading } = usePolicies();
  const [viewing, setViewing] = useState<string | null>(null);

  const byDomain = new Map<string, NonNullable<typeof policies>>();
  for (const p of policies ?? []) {
    byDomain.set(p.domain, [...(byDomain.get(p.domain) ?? []), p]);
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold">Policies</h1>
        <p className="text-sm text-muted-foreground">
          Policy sources used by ClaimFlow. Select a document to inspect it.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Policy sources</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {isLoading ? (
            <Skeleton className="h-24" />
          ) : !policies?.length ? (
            <Empty className="py-8">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FileText />
                </EmptyMedia>
                <EmptyTitle>No policy sources</EmptyTitle>
                <EmptyDescription>Policy documents will appear here when they are available.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            POLICY_DOMAINS.filter((d) => byDomain.has(d)).map((d) => (
              <div key={d} className="flex flex-col gap-2">
                <div className="text-xs font-medium text-muted-foreground">{POLICY_DOMAIN_LABELS[d]}</div>
                {byDomain.get(d)!.map((p) => (
                  <Button
                    key={p.filename}
                    variant="outline"
                    className="h-auto min-w-0 justify-start py-2"
                    onClick={() => setViewing(p.filename)}
                    title={`View ${p.filename}`}
                  >
                    <FileText data-icon="inline-start" />
                    <span className="truncate">{p.filename}</span>
                    {p.authority !== "official_cms" && (
                      <Badge variant="secondary" className="ml-auto shrink-0">
                        LLM summary
                      </Badge>
                    )}
                  </Button>
                ))}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <ViewPolicyDialog filename={viewing} onClose={() => setViewing(null)} />
    </div>
  );
}
