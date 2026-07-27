"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { useBackendStatus } from "@/hooks/use-backend-status";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

export default function SettingsPage() {
  const online = useBackendStatus();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["settings"],
    queryFn: async () => {
      const { data, error } = await api.GET("/settings");
      if (error) throw error;
      return data;
    },
  });

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Read-only configuration status. No API keys, credentials, or document content is shown here.
        </p>
      </div>

      {isError && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>Could not load settings</AlertTitle>
          <AlertDescription>Check that the ClaimFlow API is reachable.</AlertDescription>
        </Alert>
      )}

      {isLoading ? (
        <Skeleton className="h-96" />
      ) : data ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Backend</CardTitle>
            </CardHeader>
            <CardContent>
              <Row
                label="Backend status"
                value={
                  online ? (
                    <span className="inline-flex items-center gap-1 text-success">
                      <CheckCircle2 className="size-4" /> Online
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-destructive">
                      <XCircle className="size-4" /> Unreachable
                    </span>
                  )
                }
              />
              <Separator />
              <Row
                label="Anthropic API key configured"
                value={data.anthropic_api_key_configured ? "Yes" : "No"}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Review thresholds</CardTitle>
            </CardHeader>
            <CardContent>
              <Row label="Confidence threshold" value={`${Math.round(data.confidence_threshold * 100)}%`} />
              <Separator />
              <Row label="Escalation threshold" value={`${Math.round(data.escalation_threshold * 100)}%`} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Enabled domains</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-1.5">
                {data.enabled_domains.map((d) => (
                  <Badge key={d} variant="secondary">
                    {d}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Document intelligence</CardTitle>
            </CardHeader>
            <CardContent>
              <Row label="Provider" value={data.doc_intel_provider} />
              <Separator />
              <Row label="Model" value={data.doc_intel_model} />
              <Separator />
              <Row label="OCR provider" value={data.ocr_provider} />
              <Separator />
              <Row label="OCR fallback providers" value={data.ocr_fallback_providers.join(", ")} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Retrieval</CardTitle>
            </CardHeader>
            <CardContent>
              <Row label="Qdrant URL" value={data.qdrant_url} />
              <Separator />
              <Row label="Qdrant collection" value={data.qdrant_collection} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Observability</CardTitle>
            </CardHeader>
            <CardContent>
              <Row label="Langfuse tracing" value={data.langfuse_enabled ? "Enabled" : "Disabled"} />
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
