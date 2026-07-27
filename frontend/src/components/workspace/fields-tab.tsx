"use client";

import { useState } from "react";
import { Check, Pencil, X, ExternalLink, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfidenceBadge } from "@/lib/status";
import type { ExtractionField, ValidationFailure } from "@/lib/package-result";
import { useSubmitFieldReview } from "@/lib/queries";
import type { SelectedEvidence } from "@/components/workspace/document-viewer";
import { toast } from "sonner";

export type ReviewAction = "approve" | "edit" | "reject";
export type ReviewState = Record<string, { action: ReviewAction; value: unknown }>;

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
  primaryDocumentId,
  fields,
  fieldIds,
  validationFailures,
  onSelectEvidence,
  reviewed,
  onReviewed,
}: {
  packageId: string;
  primaryDocumentId: string | null;
  fields: ExtractionField[];
  fieldIds: Record<string, number>;
  validationFailures: ValidationFailure[];
  onSelectEvidence: (evidence: SelectedEvidence) => void;
  reviewed: ReviewState;
  onReviewed: (fieldName: string, action: ReviewAction, value: unknown) => void;
}) {
  const [editing, setEditing] = useState<Record<string, string>>({});
  const submitReview = useSubmitFieldReview(packageId);

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
      toast.success(`Field ${action === "approve" ? "approved" : action === "reject" ? "rejected" : "corrected"}`);
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

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Scalar fields</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Field</TableHead>
                <TableHead>Machine value</TableHead>
                <TableHead>Confidence</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Validation</TableHead>
                <TableHead>Reviewer action</TableHead>
                <TableHead className="w-10" />
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
                    <TableCell className="font-medium">{f.name}</TableCell>
                    <TableCell>
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
                          className="h-7 w-40"
                          aria-label={`Corrected value for ${f.name}`}
                        />
                      ) : (
                        <span
                          className={
                            review?.action === "edit" || review?.action === "reject"
                              ? "text-muted-foreground line-through"
                              : ""
                          }
                        >
                          {renderValue(f.value)}
                        </span>
                      )}
                      {review && review.action === "edit" && (
                        <div className="text-xs text-success">→ {renderValue(review.value)}</div>
                      )}
                      {isListField && !isEditing && (
                        <div className="text-xs text-muted-foreground">
                          list field — confidence/evidence apply to the whole list
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <ConfidenceBadge confidence={f.confidence} />
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{f.field_status}</TableCell>
                    <TableCell>
                      {failures ? (
                        <Badge variant="destructive">{failures.length} failing</Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                      {review && (
                        <Badge variant="secondary" className="capitalize">{review.action}</Badge>
                      )}
                      {isEditing ? (
                        <div className="flex gap-1">
                          <Button size="sm" variant="outline" onClick={() => saveEdit(f.name, f.value)}>
                            Save
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => cancelEdit(f.name)}>
                            Cancel
                          </Button>
                        </div>
                      ) : (
                        <div className="flex gap-1">
                          <Button size="icon" variant="ghost" aria-label="Approve" onClick={() => act(f.name, "approve")}>
                            <Check className="text-success" />
                          </Button>
                          <Button
                            size="icon"
                            variant="ghost"
                            aria-label="Edit"
                            onClick={() => setEditing((prev) => ({ ...prev, [f.name]: editorValue(f.value) }))}
                          >
                            <Pencil />
                          </Button>
                          <Button size="icon" variant="ghost" aria-label="Reject" onClick={() => act(f.name, "reject")}>
                            <X className="text-destructive" />
                          </Button>
                        </div>
                      )}
                      </div>
                    </TableCell>
                    <TableCell>
                      {f.evidence ? (
                        <Button
                          size="icon"
                          variant="ghost"
                          aria-label="View evidence"
                          onClick={() =>
                            onSelectEvidence({
                              documentId: primaryDocumentId ?? "",
                              page: f.evidence!.page ?? 1,
                              bbox: f.evidence!.bbox,
                              quote: f.evidence!.text,
                            })
                          }
                        >
                          <ExternalLink />
                        </Button>
                      ) : (
                        <span className="text-xs text-muted-foreground">no evidence</span>
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
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Row</TableHead>
                      <TableHead>Values</TableHead>
                      <TableHead>Confidence</TableHead>
                      <TableHead>Reviewer action</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((row, i) => {
                      const review = reviewed[row.name];
                      const isEditing = editing[row.name] !== undefined;
                      return (
                        <TableRow key={row.name}>
                          <TableCell className="text-xs text-muted-foreground">Row {i + 1}</TableCell>
                          <TableCell className="text-sm">
                            {isEditing ? (
                              <Input
                                value={editing[row.name]}
                                onChange={(e) => setEditing((prev) => ({ ...prev, [row.name]: e.target.value }))}
                                aria-label={`Corrected value for ${row.name}`}
                              />
                            ) : row.value && typeof row.value === "object"
                              ? Object.entries(row.value as Record<string, unknown>)
                                  .map(([k, v]) => `${k}: ${v ?? "—"}`)
                                  .join(" · ")
                              : renderValue(row.value)}
                          </TableCell>
                          <TableCell>
                            <ConfidenceBadge confidence={row.confidence} />
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-1">
                            {review && <Badge variant="secondary" className="capitalize">{review.action}</Badge>}
                            {isEditing ? (
                              <>
                                <Button size="sm" variant="outline" onClick={() => saveEdit(row.name, row.value)}>
                                  Save
                                </Button>
                                <Button size="sm" variant="ghost" onClick={() => cancelEdit(row.name)}>
                                  Cancel
                                </Button>
                              </>
                            ) : (
                              <div className="flex gap-1">
                                <Button size="icon" variant="ghost" aria-label="Approve row" onClick={() => act(row.name, "approve")}>
                                  <Check className="text-success" />
                                </Button>
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  aria-label="Edit row"
                                  onClick={() => setEditing((prev) => ({ ...prev, [row.name]: editorValue(row.value) }))}
                                >
                                  <Pencil />
                                </Button>
                                <Button size="icon" variant="ghost" aria-label="Reject row" onClick={() => act(row.name, "reject")}>
                                  <X className="text-destructive" />
                                </Button>
                              </div>
                            )}
                            </div>
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
