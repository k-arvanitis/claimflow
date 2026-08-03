"use client";

import { FileText, ScanLine, ScrollText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useDocuments } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function DocumentList({
  packageId,
  selectedDocumentId,
  onSelect,
  extractedDocTypes,
}: {
  packageId: string;
  selectedDocumentId: string | null;
  onSelect: (documentId: string) => void;
  /** doc_types that got deep field extraction — the package's primary domain
   * plus any secondary document with its own registered domain pack (e.g. an
   * EOB alongside a CMS-1500). Every other document is classified but not
   * extracted. Pass null/undefined to hide the extracted/classified-only
   * distinction entirely. */
  extractedDocTypes?: string[] | null;
}) {
  const { data: documents, isLoading } = useDocuments(packageId);

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
          role="button"
          tabIndex={0}
          onClick={() => onSelect(doc.document_id)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") onSelect(doc.document_id);
          }}
          className={cn(
            "flex cursor-pointer flex-col gap-1.5 rounded-md border p-2 text-sm transition-colors",
            selectedDocumentId === doc.document_id ? "border-primary bg-accent/60" : "border-transparent hover:bg-accent/30"
          )}
        >
          <div className="flex items-center gap-2">
            <FileText className="size-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate font-medium">{doc.filename}</span>
          </div>

          <div className="flex flex-wrap items-center gap-1.5 pl-6">
            <Badge variant="secondary">{doc.doc_type}</Badge>
            {extractedDocTypes != null &&
              (() => {
                const isExtracted = extractedDocTypes.includes(doc.doc_type);
                const isPrimary = extractedDocTypes[0] === doc.doc_type;
                return (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Badge
                        variant="outline"
                        className={isExtracted ? "border-success text-success" : "text-muted-foreground"}
                      >
                        {isExtracted ? "Extracted" : "Classified only"}
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent>
                      {isPrimary
                        ? "This package's primary document type — fields, confidence, and validation come from here."
                        : isExtracted
                          ? "A supporting document with its own extraction and validation — read-only, not cross-checked against the primary document."
                          : "Recognized and included in this package, but not deep-extracted — no registered schema for this document type."}
                    </TooltipContent>
                  </Tooltip>
                );
              })()}
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
          {extractedDocTypes != null && !extractedDocTypes.includes(doc.doc_type) && (
            <p className="pl-6 text-xs text-muted-foreground">
              Recognized, not deep-extracted — no registered schema for this document type.
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
