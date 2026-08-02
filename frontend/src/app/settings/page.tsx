"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AlertTriangle, CheckCircle2, XCircle, KeyRound, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useBackendStatus } from "@/hooks/use-backend-status";
import {
  useLLMCredentials,
  useSetLLMCredentials,
  useDeleteLLMCredentials,
  useDomainPacks,
  useDomainPack,
} from "@/lib/queries";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  groq: "Groq",
  openrouter: "OpenRouter",
  openai: "OpenAI",
  custom: "Custom service",
};

type LLMCredentialsStatus = NonNullable<ReturnType<typeof useLLMCredentials>["data"]>;

function LLMCredentialsForm({ status }: { status: LLMCredentialsStatus }) {
  const setCredentials = useSetLLMCredentials();
  const clearCredentials = useDeleteLLMCredentials();

  const activeServiceCanBeSelected = status.providers.includes(status.active_service);
  const [provider, setProvider] = useState(
    status.provider ?? (activeServiceCanBeSelected ? status.active_service : status.providers[0] ?? "groq"),
  );
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(
    status.model ?? (!status.using_override && activeServiceCanBeSelected ? status.active_model : ""),
  );

  async function handleSave() {
    try {
      await setCredentials.mutateAsync({ provider, api_key: apiKey.trim() || null, model: model.trim() || null });
      setApiKey("");
      toast.success("Active model updated");
    } catch {
      toast.error("Could not save LLM credentials");
    }
  }

  async function handleClear() {
    try {
      await clearCredentials.mutateAsync();
      setApiKey("");
      toast.success("Reverted to the server configuration");
    } catch {
      toast.error("Could not clear LLM credentials");
    }
  }

  const busy = setCredentials.isPending || clearCredentials.isPending;

  return (
    <>
      <div>
        <Row label="Service" value={PROVIDER_LABELS[status.active_service] ?? status.active_service} />
        <Separator />
        <Row label="Model" value={status.active_model} />
        <Separator />
        <Row
          label="Configuration"
          value={
            <span className="inline-flex items-center gap-2">
              <Badge variant="outline">{status.using_override ? "Custom credentials" : "Server configuration"}</Badge>
              {status.key_set && (
                <span className="text-xs font-normal text-muted-foreground">key ending {status.key_last4}</span>
              )}
            </span>
          }
        />
      </div>

      <Separator />

      <FieldSet>
        <FieldLegend variant="label">LLM configuration</FieldLegend>
        <FieldGroup className="gap-3">
          <Field>
            <FieldLabel htmlFor="llm-service">Service</FieldLabel>
            <Select value={provider} onValueChange={(v) => v && setProvider(v)}>
              <SelectTrigger id="llm-service" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {(status.providers ?? Object.keys(PROVIDER_LABELS)).map((p) => (
                    <SelectItem key={p} value={p}>
                      {PROVIDER_LABELS[p] ?? p}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>

          <Field>
            <FieldLabel htmlFor="llm-api-key">API key</FieldLabel>
            <Input
              id="llm-api-key"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={status.key_set ? `Leave blank to keep key ending ${status.key_last4}` : "sk-..."}
              autoComplete="off"
            />
          </Field>

          <Field>
            <FieldLabel htmlFor="llm-model">Model</FieldLabel>
            <Input
              id="llm-model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="Use the service default"
            />
            <FieldDescription>Optional. Leave blank to use the service&apos;s default model.</FieldDescription>
          </Field>
        </FieldGroup>
      </FieldSet>

      <div className="flex justify-end gap-2 pt-1">
        {status.key_set && (
          <Button variant="outline" size="sm" onClick={handleClear} disabled={busy}>
            Use server configuration
          </Button>
        )}
        <Button size="sm" onClick={handleSave} disabled={busy || !provider || (!status.key_set && !apiKey.trim())}>
          {busy ? <Loader2 className="animate-spin" /> : <KeyRound data-icon="inline-start" />}
          Save
        </Button>
      </div>

      <p className="text-xs text-muted-foreground">
        Applies to extraction and policy-lookup LLM calls. Stored on the server only, never shown again after
        saving. Takes effect immediately — no restart needed.
      </p>
    </>
  );
}

function LLMCredentialsCard() {
  const { data: status, isLoading } = useLLMCredentials();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Active model</CardTitle>
        <CardDescription>Used for document extraction and policy lookup.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {isLoading || !status ? <Skeleton className="h-32" /> : <LLMCredentialsForm status={status} />}
      </CardContent>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function PackageTypeDetail({ packKey }: { packKey: string }) {
  const { data, isLoading } = useDomainPack(packKey);
  if (isLoading) return <Skeleton className="h-32" />;
  if (!data) return <p className="text-sm text-muted-foreground">Could not load schema.</p>;
  const [primaryType, ...supportingTypes] = data.document_types;
  return (
    <div className="flex flex-col gap-3 text-sm">
      <div>
        <p className="mb-1 text-xs font-medium text-muted-foreground">Primary document type</p>
        <Badge className="border-success text-success" variant="outline">{primaryType}</Badge>
      </div>
      {supportingTypes.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            Recognized supporting documents ({supportingTypes.length})
          </p>
          <div className="flex flex-wrap gap-1">
            {supportingTypes.map((t) => (
              <Badge key={t} variant="secondary">{t}</Badge>
            ))}
          </div>
        </div>
      )}
      <Row label="Confidence threshold" value={`${Math.round(data.confidence_threshold * 100)}%`} />
      <Row label="Escalation threshold" value={`${Math.round(data.escalation_threshold * 100)}%`} />
      <Row label="Policy collection" value={data.policy_collection ?? "none"} />
      <Row label="Retrieval mode" value={data.retrieval_mode} />
      <div>
        <p className="mb-1 text-xs font-medium text-muted-foreground">Required fields ({data.required_fields.length})</p>
        <div className="flex flex-wrap gap-1">
          {data.required_fields.map((f) => (
            <Badge key={f} variant="outline">{f}</Badge>
          ))}
        </div>
      </div>
      <div>
        <p className="mb-1 text-xs font-medium text-muted-foreground">Optional fields ({data.optional_fields.length})</p>
        <div className="flex flex-wrap gap-1">
          {data.optional_fields.map((f) => (
            <Badge key={f} variant="secondary">{f}</Badge>
          ))}
        </div>
      </div>
      {data.reviewer_guidance && (
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">Reviewer guidance</p>
          <p className="text-sm">{data.reviewer_guidance}</p>
        </div>
      )}
    </div>
  );
}

function PackageTypesCard() {
  const { data: packs, isLoading } = useDomainPacks();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Package types</CardTitle>
        <CardDescription>
          The extraction schema, required/optional fields, and thresholds each package type is configured with.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-24" />
        ) : (
          <Accordion type="single" collapsible>
            {packs?.map((pack) => (
              <AccordionItem key={pack.key} value={pack.key}>
                <AccordionTrigger>{pack.display_name}</AccordionTrigger>
                <AccordionContent>
                  <PackageTypeDetail packKey={pack.key} />
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        )}
      </CardContent>
    </Card>
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
          Configuration status. Document content is never shown here; the only credential this page accepts
          is an optional LLM API key, stored server-side and never redisplayed.
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

          <LLMCredentialsCard />

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Document processing</CardTitle>
            </CardHeader>
            <CardContent>
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

          <PackageTypesCard />
        </>
      ) : null}
    </div>
  );
}
