"use client";

import { useState } from "react";
import { Check, Pencil, X, Plus, FileSearch, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfidenceBadge } from "@/lib/status";
import { cn } from "@/lib/utils";
import type { ExtractionField, ValidationFailure } from "@/lib/package-result";
import { useSubmitFieldReview } from "@/lib/queries";
import { api } from "@/lib/api";
import type { EvidenceFocus } from "@/components/workspace/document-viewer";
import { toast } from "sonner";

export type ReviewAction = "approve" | "edit" | "reject";
export type ReviewState = Record<string, { action: ReviewAction; value: unknown }>;

const ACTION_LABEL: Record<ReviewAction, string> = {
  approve: "Confirmed",
  edit: "Corrected",
  reject: "Marked unresolved",
};

function isScalar(value: unknown) {
  return value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function isObjectList(value: unknown): value is Record<string, unknown>[] {
  return Array.isArray(value) && value.length > 0 && typeof value[0] === "object" && value[0] !== null;
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.join(", ") || "—";
  return String(value);
}

const ACRONYMS = new Set(["cpt", "npi", "id", "epsdt"]);

function humanizeLabel(key: string): string {
  const words = key.split("_");
  return words
    .map((w, i) => {
      if (ACRONYMS.has(w.toLowerCase())) return w.toUpperCase();
      return i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w;
    })
    .join(" ");
}

function humanizeRowValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" && /^\d{6}(\d{2})?$/.test(value) && /date/i.test(key)) {
    return `${value.slice(0, 2)}/${value.slice(2, 4)}/${value.slice(4)}`;
  }
  if (typeof value === "number" && /(charge|amount|cost|total|price)/i.test(key)) {
    return `$${value.toFixed(2)}`;
  }
  return String(value);
}

function editorValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function parseEditorValue(original: unknown, value: string): unknown {
  if (typeof original === "number") {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) throw new Error("Enter a valid number");
    return parsed;
  }
  if (typeof original === "boolean") return value === "true";
  if (Array.isArray(original)) {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) throw new Error("Enter a valid JSON array");
    return parsed;
  }
  if (original && typeof original === "object") {
    const parsed = JSON.parse(value);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("Enter a valid JSON object");
    }
    return parsed;
  }
  if (original === null) {
    try {
      return JSON.parse(value);
    } catch {
      return value;
    }
  }
  return value;
}

export function FieldsTab({
  packageId,
  fields,
  fieldIds,
  validationFailures,
  reviewed,
  onReviewed,
  onFocusEvidence,
}: {
  packageId: string;
  fields: ExtractionField[];
  fieldIds: Record<string, number>;
  validationFailures: ValidationFailure[];
  reviewed: ReviewState;
  onReviewed: (fieldName: string, action: ReviewAction, value: unknown) => void;
  onFocusEvidence: (focus: EvidenceFocus) => void;
}) {
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [editingRow, setEditingRow] = useState<Record<string, Record<string, string>>>({});
  const [loadingEvidence, setLoadingEvidence] = useState<string | null>(null);
  const submitReview = useSubmitFieldReview(packageId);

  async function jumpToEvidence(fieldName: string) {
    const fieldId = fieldIds[fieldName];
    if (!fieldId) return;
    setLoadingEvidence(fieldName);
    try {
      const { data, error } = await api.GET("/packages/{package_id}/fields/{field_id}/evidence", {
        params: { path: { package_id: packageId, field_id: fieldId } },
      });
      if (error || !data || data.evidence_unavailable || data.page == null) {
        toast.error("No source evidence recorded for this field");
        return;
      }
      onFocusEvidence({
        documentId: data.document_id,
        page: data.page,
        bbox: data.bbox as [number, number, number, number] | undefined,
        token: Date.now(),
      });
    } catch {
      toast.error("Could not load evidence");
    } finally {
      setLoadingEvidence(null);
    }
  }

  const failuresByField = new Map<string, ValidationFailure[]>();
  for (const f of validationFailures) {
    failuresByField.set(f.field, [...(failuresByField.get(f.field) ?? []), f]);
  }

  const topLevel = fields.filter((f) => !f.parent_field);
  const scalarFields = topLevel.filter((f) => isScalar(f.value) || (Array.isArray(f.value) && !isObjectList(f.value)));
  const nestedFields = topLevel.filter((f) => isObjectList(f.value));

  async function act(fieldName: string, action: ReviewAction, correctedValue?: unknown): Promise<boolean> {
    const fieldId = fieldIds[fieldName];
    if (!fieldId) return false;
    try {
      await submitReview.mutateAsync({ fieldId, action, correctedValue });
      onReviewed(fieldName, action, correctedValue);
      toast.success(`Field ${ACTION_LABEL[action].toLowerCase()}`);
      return true;
    } catch {
      toast.error("Could not submit review action");
      return false;
    }
  }

  async function saveEdit(fieldName: string, originalValue: unknown) {
    try {
      const correctedValue = parseEditorValue(originalValue, editing[fieldName]);
      const saved = await act(fieldName, "edit", correctedValue);
      if (!saved) return;
      setEditing((prev) => {
        const next = { ...prev };
        delete next[fieldName];
        return next;
      });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Enter a valid value");
    }
  }

  function cancelEdit(fieldName: string) {
    setEditing((prev) => {
      const next = { ...prev };
      delete next[fieldName];
      return next;
    });
  }

  function startRowEdit(row: ExtractionField) {
    const original = row.value as Record<string, unknown>;
    const values: Record<string, string> = {};
    for (const [k, v] of Object.entries(original)) values[k] = editorValue(v);
    setEditingRow((prev) => ({ ...prev, [row.name]: values }));
  }

  function cancelRowEdit(rowName: string) {
    setEditingRow((prev) => {
      const next = { ...prev };
      delete next[rowName];
      return next;
    });
  }

  async function saveRowEdit(row: ExtractionField) {
    const original = row.value as Record<string, unknown>;
    const edits = editingRow[row.name];
    try {
      const corrected: Record<string, unknown> = {};
      for (const k of Object.keys(original)) {
        corrected[k] = parseEditorValue(original[k], edits[k]);
      }
      const saved = await act(row.name, "edit", corrected);
      if (!saved) return;
      cancelRowEdit(row.name);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Enter a valid value");
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Scalar fields</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <Table className="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className="w-[28%]">Field</TableHead>
                <TableHead className="w-[30%]">Value</TableHead>
                <TableHead className="w-[18%]">Signal</TableHead>
                <TableHead className="w-[24%]">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {scalarFields.map((f) => {
                const failures = failuresByField.get(f.name);
                const review = reviewed[f.name];
                const isEditing = editing[f.name] !== undefined;
                const isListField = Array.isArray(f.value);

                return (
                  <TableRow key={f.name} className={failures ? "bg-destructive/5" : undefined}>
                    <TableCell className="truncate font-medium" title={f.name}>
                      {f.name}
                    </TableCell>
                    <TableCell className="max-w-0">
                      {isEditing && typeof f.value === "boolean" ? (
                        <Select
                          value={editing[f.name]}
                          onValueChange={(value) => setEditing((prev) => ({ ...prev, [f.name]: value }))}
                        >
                          <SelectTrigger size="sm" className="w-32">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectGroup>
                              <SelectItem value="true">True</SelectItem>
                              <SelectItem value="false">False</SelectItem>
                            </SelectGroup>
                          </SelectContent>
                        </Select>
                      ) : isEditing ? (
                        <Input
                          type={typeof f.value === "number" ? "number" : "text"}
                          value={editing[f.name]}
                          onChange={(e) => setEditing((prev) => ({ ...prev, [f.name]: e.target.value }))}
                          className="h-7 w-32"
                          aria-label={`Corrected value for ${f.name}`}
                        />
                      ) : (
                        <span
                          className={cn(
                            "block truncate",
                            (review?.action === "edit" || review?.action === "reject") &&
                              "text-muted-foreground line-through",
                          )}
                          title={renderValue(f.value)}
                        >
                          {renderValue(f.value)}
                        </span>
                      )}
                      {review && review.action === "edit" && (
                        <div className="text-xs text-success">→ {renderValue(review.value)}</div>
                      )}
                      {isListField && !isEditing && (
                        <div className="text-xs text-muted-foreground">list field</div>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col items-start gap-1">
                        <ConfidenceBadge confidence={f.confidence} notFound={f.field_status === "not_found"} />
                        {f.field_status !== "found" && f.field_status !== "not_found" && (
                          <span className="text-xs text-muted-foreground">{f.field_status}</span>
                        )}
                        {failures && <Badge variant="destructive">{failures.length} failing</Badge>}
                        {review && <Badge variant="secondary">{ACTION_LABEL[review.action]}</Badge>}
                      </div>
                    </TableCell>
                    <TableCell>
                      {isEditing ? (
                        <div className="flex flex-col gap-1">
                          <Button size="sm" variant="outline" onClick={() => saveEdit(f.name, f.value)}>
                            Save
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => cancelEdit(f.name)}>
                            Cancel
                          </Button>
                        </div>
                      ) : (
                        <div className="flex flex-wrap items-center gap-0.5">
                          <Button size="icon" variant="ghost" aria-label="Confirm value" title="Confirm value" onClick={() => act(f.name, "approve")}>
                            <Check className="text-success" />
                          </Button>
                          <Button
                            size="icon"
                            variant="ghost"
                            aria-label="Correct value" title="Correct value"
                            onClick={() => setEditing((prev) => ({ ...prev, [f.name]: editorValue(f.value) }))}
                          >
                            <Pencil />
                          </Button>
                          <Button size="icon" variant="ghost" aria-label="Mark unresolved" title="Mark unresolved" onClick={() => act(f.name, "reject")}>
                            <X className="text-destructive" />
                          </Button>
                          {f.evidence != null && (
                            <Button
                              size="icon"
                              variant="ghost"
                              aria-label="View source evidence"
                              title="View source evidence"
                              onClick={() => jumpToEvidence(f.name)}
                              disabled={loadingEvidence === f.name}
                            >
                              {loadingEvidence === f.name ? <Loader2 className="animate-spin" /> : <FileSearch />}
                            </Button>
                          )}
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {nestedFields.map((parent) => {
        const rows = fields.filter((f) => f.parent_field === parent.name);
        const parentFailures = failuresByField.get(parent.name);
        return (
          <Card key={parent.name}>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-sm">{parent.name}</CardTitle>
              {parentFailures && <Badge variant="destructive">{parentFailures.length} failing</Badge>}
            </CardHeader>
            <CardContent className="overflow-x-auto p-0">
              {rows.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">No rows extracted.</p>
              ) : (
                <Table className="table-fixed">
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-14">Row</TableHead>
                      <TableHead className="w-[46%]">Values</TableHead>
                      <TableHead className="w-[14%]">Signal</TableHead>
                      <TableHead className="w-[22%]">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((row, i) => {
                      const review = reviewed[row.name];
                      const rowEdits = editingRow[row.name];
                      // A saved correction replaces the row entirely (saveRowEdit stores the whole
                      // corrected object) — show that instead of the stale originally-extracted value.
                      const displayValue = review?.action === "edit" ? review.value : row.value;
                      const entries =
                        displayValue && typeof displayValue === "object"
                          ? Object.entries(displayValue as Record<string, unknown>).filter(
                              ([, v]) => v !== null && v !== undefined && v !== "",
                            )
                          : null;
                      return (
                        <TableRow key={row.name}>
                          <TableCell className="text-xs text-muted-foreground">Row {i + 1}</TableCell>
                          <TableCell className="text-sm">
                            {rowEdits ? (
                              <div className="flex flex-col gap-2 py-1">
                                {Object.keys(rowEdits).map((k) => (
                                  <div key={k} className="flex flex-col gap-0.5">
                                    <label className="text-xs text-muted-foreground">
                                      {humanizeLabel(k)}
                                    </label>
                                    <Input
                                      value={rowEdits[k]}
                                      onChange={(e) =>
                                        setEditingRow((prev) => ({
                                          ...prev,
                                          [row.name]: { ...prev[row.name], [k]: e.target.value },
                                        }))
                                      }
                                      className="h-7"
                                      aria-label={humanizeLabel(k)}
                                    />
                                  </div>
                                ))}
                              </div>
                            ) : entries ? (
                              <div className="flex flex-col gap-0.5">
                                {entries.map(([k, v]) => (
                                  <div key={k} className="flex gap-1">
                                    <span className="text-muted-foreground">{humanizeLabel(k)}:</span>
                                    <span>{humanizeRowValue(k, v)}</span>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              renderValue(displayValue)
                            )}
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-col items-start gap-1">
                              <ConfidenceBadge confidence={row.confidence} />
                              {review && <Badge variant="secondary">{ACTION_LABEL[review.action]}</Badge>}
                            </div>
                          </TableCell>
                          <TableCell>
                            {rowEdits ? (
                              <div className="flex flex-col gap-1">
                                <Button size="sm" variant="outline" onClick={() => saveRowEdit(row)}>
                                  Save
                                </Button>
                                <Button size="sm" variant="ghost" onClick={() => cancelRowEdit(row.name)}>
                                  Cancel
                                </Button>
                              </div>
                            ) : (
                              <div className="flex flex-wrap items-center gap-0.5">
                                <Button size="icon" variant="ghost" aria-label="Confirm row" title="Confirm row" onClick={() => act(row.name, "approve")}>
                                  <Check className="text-success" />
                                </Button>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  aria-label="Correct row" title="Correct row"
                                  onClick={() => startRowEdit(row)}
                                >
                                  <Pencil />
                                </Button>
                                <Button size="icon" variant="ghost" aria-label="Mark row unresolved" title="Mark row unresolved" onClick={() => act(row.name, "reject")}>
                                  <X className="text-destructive" />
                                </Button>
                                {row.evidence != null && (
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    aria-label="View source evidence"
                                    title="View source evidence"
                                    onClick={() => jumpToEvidence(row.name)}
                                    disabled={loadingEvidence === row.name}
                                  >
                                    {loadingEvidence === row.name ? <Loader2 className="animate-spin" /> : <FileSearch />}
                                  </Button>
                                )}
                              </div>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
              <div className="p-2">
                <Button variant="outline" size="sm" disabled title="Requires knowing the row schema — not yet supported">
                  <Plus data-icon="inline-start" />
                  Add row
                </Button>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
