"use client";

import { useState } from "react";
import { RefreshCw, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { CircleCheck } from "lucide-react";
import type { ExtractionField, ValidationFailure } from "@/lib/package-result";
import type { ReviewState } from "@/components/workspace/fields-tab";
import { ruleLabel } from "@/lib/status";
import { useRerunValidation } from "@/lib/queries";
import { toast } from "sonner";

export function ValidationTab({
  packageId,
  fields,
  validationFailures,
  reviewed,
  onSelectField,
  onGoToTab,
}: {
  packageId: string;
  fields: ExtractionField[];
  validationFailures: ValidationFailure[];
  reviewed: ReviewState;
  onSelectField: (fieldName: string) => void;
  onGoToTab: (tab: string) => void;
}) {
  const rerun = useRerunValidation(packageId);
  const [lastResult, setLastResult] = useState<{ decision: string; decisionChanged: boolean } | null>(null);

  const machineValue = new Map(fields.map((f) => [f.name, f.value]));

  async function handleRerun() {
    const correctedFields: Record<string, unknown> = {};
    for (const [name, r] of Object.entries(reviewed)) {
      if (r.action === "edit") correctedFields[name] = r.value;
      if (r.action === "reject") correctedFields[name] = null;
    }
    try {
      const result = await rerun.mutateAsync(correctedFields);
      setLastResult({ decision: result.decision, decisionChanged: result.decision_changed });
      toast.success(`Validation re-run — ${result.validation_failures.length} failure(s), decision: ${result.decision}`);
    } catch {
      toast.error("Could not re-run validation");
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Deterministic rule failures for the latest extraction run. Corrections made in the Fields tab are included
          when you re-run validation.
        </p>
        <Button size="sm" onClick={handleRerun} disabled={rerun.isPending}>
          <RefreshCw className={rerun.isPending ? "animate-spin" : ""} data-icon="inline-start" />
          Re-run validation
        </Button>
      </div>

      {lastResult && (
        <p className="text-xs text-muted-foreground">
          Last re-run resulted in decision <span className="font-medium">{lastResult.decision}</span>
          {lastResult.decisionChanged ? " (changed from the previous decision)" : " (unchanged)"}.
        </p>
      )}

      {validationFailures.length === 0 ? (
        <Empty className="py-12">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <CircleCheck />
            </EmptyMedia>
            <EmptyTitle>No validation failures</EmptyTitle>
            <EmptyDescription>This package&apos;s extracted values pass every deterministic rule.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="flex flex-col gap-2">
          {validationFailures.map((f, i) => {
            const correction = reviewed[f.field];
            const rawValue = machineValue.get(f.field);
            // Prefer the backend's authoritative comparison value (set by the rule that
            // evaluated it) over the raw extracted field — for rules like "arithmetic"
            // the two differ: the field holds the reported total, machine_value holds
            // what the rule actually computed and compared against it.
            const machine =
              f.machine_value ??
              (rawValue == null ? "—" : typeof rawValue === "object" ? JSON.stringify(rawValue) : String(rawValue));
            return (
              <div key={`${f.field}-${i}`} className="rounded-md border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium">{f.field}</span>
                    <Badge variant={f.severity === "error" ? "destructive" : "secondary"}>
                      {f.severity === "error" ? "Blocking" : "Warning"}
                    </Badge>
                    <Badge variant="outline" title={f.rule}>{ruleLabel(f.rule)}</Badge>
                    <span className="text-xs text-muted-foreground">
                      {f.policy_required ? "policy dependent" : "deterministic"}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button size="icon" variant="ghost" aria-label="Open field" title="Open field" onClick={() => onSelectField(f.field)}>
                      <ExternalLink />
                    </Button>
                    {f.policy_required && (
                      <Button size="sm" variant="ghost" onClick={() => onGoToTab("policy")}>
                        Policy evidence
                      </Button>
                    )}
                  </div>
                </div>
                <p className="mt-1.5 text-sm">{f.reason}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Machine value: {machine}
                  {f.expected_value && <> · Expected: {f.expected_value}</>}
                  {correction?.action === "edit" && (
                    <>
                      {" "}
                      → <span className="text-success">{String(correction.value)}</span>
                    </>
                  )}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
