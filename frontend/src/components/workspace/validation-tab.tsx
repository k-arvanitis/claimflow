"use client";

import { useState } from "react";
import { RefreshCw, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { CircleCheck } from "lucide-react";
import type { ExtractionField, ValidationFailure } from "@/lib/package-result";
import type { ReviewState } from "@/components/workspace/fields-tab";
import { useRerunValidation } from "@/lib/queries";
import { toast } from "sonner";

export function ValidationTab({
  packageId,
  fields,
  validationFailures,
  reviewed,
  onSelectField,
}: {
  packageId: string;
  fields: ExtractionField[];
  validationFailures: ValidationFailure[];
  reviewed: ReviewState;
  onSelectField: (fieldName: string) => void;
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
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Field</TableHead>
              <TableHead>Rule</TableHead>
              <TableHead>Reason</TableHead>
              <TableHead>Machine value</TableHead>
              <TableHead>Corrected value</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {validationFailures.map((f, i) => {
              const correction = reviewed[f.field];
              return (
                <TableRow key={`${f.field}-${i}`}>
                  <TableCell className="font-medium">{f.field}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{f.rule}</Badge>
                  </TableCell>
                  <TableCell className="text-sm">{f.reason}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {String(machineValue.get(f.field) ?? "—")}
                  </TableCell>
                  <TableCell className="text-sm">
                    {correction?.action === "edit" ? (
                      <span className="text-success">{String(correction.value)}</span>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell>
                    <Button size="icon" variant="ghost" aria-label="Open field" onClick={() => onSelectField(f.field)}>
                      <ExternalLink />
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
