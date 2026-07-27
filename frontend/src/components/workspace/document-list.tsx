"use client";

import { FileText, RefreshCw, ScanLine, ScrollText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useDocuments, useReclassifyDocument, useReprocessPackage } from "@/lib/queries";
import type { components } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

const DOC_TYPES: components["schemas"]["DocumentType"][] = [
  "cms1500",
  "eob",
  "medicare_summary_notice",
  "xactimate",
  "declarations_page",
  "loan",
  "sba_form_413",
  "sba_form_2202",
  "medical_bill",
  "insurance_policy",
  "denial_letter",
  "clinical_note",
  "lab_report",
  "discharge_summary",
  "referral_letter",
  "prior_authorization_letter",
  "eligibility_benefits_verification",
  "ub04_cms1450",
  "loss_report",
  "contractor_invoice",
  "adjuster_notes",
  "roof_inspection_report",
  "damage_photo",
  "material_receipt",
  "fire_report",
  "police_report",
  "tax_return",
  "bank_statement",
  "balance_sheet",
  "income_statement",
  "id_document",
  "supporting_exhibit",
  "profit_loss_statement",
  "debt_schedule",
  "business_license",
  "articles_of_incorporation",
  "payroll_report",
  "w2_1099_paystub",
  "unknown",
];

export function DocumentList({
  packageId,
  selectedDocumentId,
  onSelect,
}: {
  packageId: string;
  selectedDocumentId: string | null;
  onSelect: (documentId: string) => void;
}) {
  const { data: documents, isLoading } = useDocuments(packageId);
  const reclassify = useReclassifyDocument(packageId);
  const reprocess = useReprocessPackage(packageId);

  if (isLoading) {
    return <div className="p-3 text-sm text-muted-foreground">Loading documents…</div>;
  }

  if (!documents || documents.length === 0) {
    return <div className="p-3 text-sm text-muted-foreground">No documents in this package.</div>;
  }

  return (
    <div className="flex flex-col gap-1 p-2">
      {documents.map((doc) => (
        <div
          key={doc.document_id}
          className={cn(
            "flex flex-col gap-1.5 rounded-md border p-2 text-sm transition-colors",
            selectedDocumentId === doc.document_id ? "border-primary bg-accent/60" : "border-transparent hover:bg-accent/30"
          )}
        >
          <button
            className="flex items-center gap-2 text-left"
            onClick={() => onSelect(doc.document_id)}
          >
            <FileText className="size-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate font-medium">{doc.filename}</span>
          </button>

          <div className="flex flex-wrap items-center gap-1.5 pl-6">
            <Badge variant="secondary">{doc.doc_type}</Badge>
            {doc.manually_overridden && <Badge variant="outline">manually overridden</Badge>}
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                  {doc.has_text_layer ? <ScrollText className="size-3" /> : <ScanLine className="size-3" />}
                  {doc.has_text_layer ? "Native text" : "OCR"}
                </span>
              </TooltipTrigger>
              <TooltipContent>{doc.classification_reason ?? "No classification reason recorded"}</TooltipContent>
            </Tooltip>
            {doc.scan_quality != null && (
              <span className="text-xs text-muted-foreground">scan quality {doc.scan_quality.toFixed(2)}</span>
            )}
          </div>

          <div className="flex items-center gap-2 pl-6">
            <Select
              value={doc.doc_type}
              onValueChange={async (value) => {
                try {
                  await reclassify.mutateAsync({
                    documentId: doc.document_id,
                    docType: value as components["schemas"]["DocumentType"],
                  });
                  toast.success("Document reclassified — reprocess to apply");
                } catch {
                  toast.error("Reclassification failed");
                }
              }}
            >
              <SelectTrigger size="sm" className="h-7 w-40 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {DOC_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            {doc.manually_overridden && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={async () => {
                  try {
                    await reprocess.mutateAsync();
                    toast.success("Reprocessing started");
                  } catch {
                    toast.error("Could not start reprocessing");
                  }
                }}
              >
                <RefreshCw data-icon="inline-start" />
                Reprocess
              </Button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
