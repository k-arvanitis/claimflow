"use client";

import { use, useMemo, useState } from "react";
import { PanelLeft } from "lucide-react";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertTriangle } from "lucide-react";

import { usePackage, useDocuments, usePackageReview } from "@/lib/queries";
import type { PackageResult } from "@/lib/package-result";
import { PackageHeader } from "@/components/workspace/package-header";
import { DocumentList } from "@/components/workspace/document-list";
import { DocumentViewer, type SelectedEvidence } from "@/components/workspace/document-viewer";
import { OverviewTab } from "@/components/workspace/overview-tab";
import { FieldsTab, type ReviewState, type ReviewAction } from "@/components/workspace/fields-tab";
import { ValidationTab } from "@/components/workspace/validation-tab";
import { PolicyTab } from "@/components/workspace/policy-tab";
import { AuditTab } from "@/components/workspace/audit-tab";
import { DecisionDialog } from "@/components/workspace/decision-dialog";

export default function PackageWorkspacePage({ params }: { params: Promise<{ packageId: string }> }) {
  const { packageId } = use(params);

  const pkg = usePackage(packageId, { poll: true });
  const { data: documents } = useDocuments(packageId);
  const review = usePackageReview(packageId);

  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<SelectedEvidence | null>(null);
  const [tab, setTab] = useState("overview");
  const [pendingDecision, setPendingDecision] = useState<
    "ready_for_processing" | "needs_review" | "blocked_or_incomplete" | null
  >(null);
  const [reviewed, setReviewed] = useState<ReviewState>({});

  const result = pkg.data?.result as PackageResult | null | undefined;
  const fields = useMemo(() => result?.extraction_fields ?? [], [result]);
  const validationFailures = review.data?.validation_failures ?? result?.validation_failures ?? [];

  const fieldIds = useMemo(() => {
    const map: Record<string, number> = {};
    for (const f of review.data?.fields ?? []) map[f.name] = f.field_id;
    return map;
  }, [review.data]);

  // Server-persisted reviewer actions (survive a refresh) merged with this session's
  // own optimistic updates — local state wins until the server catches up post-invalidation.
  const mergedReviewed = useMemo(() => {
    const fromServer: ReviewState = {};
    for (const f of review.data?.fields ?? []) {
      if (f.reviewer_action) {
        fromServer[f.name] = { action: f.reviewer_action as ReviewAction, value: f.corrected_value };
      }
    }
    return { ...fromServer, ...reviewed };
  }, [review.data, reviewed]);

  const primaryDocument = documents?.find((d) => d.doc_type === pkg.data?.domain) ?? documents?.[0] ?? null;
  const activeDocumentId = selectedDocumentId ?? primaryDocument?.document_id ?? null;

  const ocrWarnings = (documents ?? [])
    .filter((d) => d.scan_quality != null && d.scan_quality < 0.5)
    .map((d) => `${d.filename}: low scan quality (${d.scan_quality?.toFixed(2)})`);

  function handleSelectEvidence(next: SelectedEvidence) {
    setEvidence(next);
    if (next.documentId) setSelectedDocumentId(next.documentId);
    setTab((t) => t); // keep current tab; viewer updates independently
  }

  function handleSelectFieldFromValidation(fieldName: string) {
    setTab("fields");
    const field = fields.find((f) => f.name === fieldName);
    if (field?.evidence) {
      handleSelectEvidence({
        documentId: primaryDocument?.document_id ?? "",
        page: field.evidence.page ?? 1,
        bbox: field.evidence.bbox,
        quote: field.evidence.text,
      });
    }
  }

  function handleReviewed(fieldName: string, action: ReviewAction, value: unknown) {
    setReviewed((prev) => ({ ...prev, [fieldName]: { action, value } }));
  }

  if (pkg.isLoading) {
    return <Skeleton className="h-[70vh]" />;
  }

  if (pkg.isError || !pkg.data) {
    return (
      <Alert variant="destructive">
        <AlertTriangle />
        <AlertTitle>Package not found</AlertTitle>
        <AlertDescription>Could not load this package. It may not exist or the API is unreachable.</AlertDescription>
      </Alert>
    );
  }

  const documentListPanel = (
    <DocumentList packageId={packageId} selectedDocumentId={activeDocumentId} onSelect={setSelectedDocumentId} />
  );

  const reviewPanel = (
    <Tabs value={tab} onValueChange={setTab} className="flex h-full flex-col">
      <TabsList className="mx-2 mt-2 w-fit">
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="fields">Fields</TabsTrigger>
        <TabsTrigger value="validation">Validation</TabsTrigger>
        <TabsTrigger value="policy">Policy evidence</TabsTrigger>
        <TabsTrigger value="audit">Audit</TabsTrigger>
      </TabsList>
      <div className="flex-1 overflow-auto p-4">
        <TabsContent value="overview">
          <OverviewTab
            status={pkg.data.status}
            decision={pkg.data.decision ?? null}
            confidence={pkg.data.overall_confidence ?? null}
            documentCount={pkg.data.document_count ?? documents?.length ?? 0}
            fields={fields}
            validationFailures={validationFailures}
            reviewed={mergedReviewed}
            ocrWarnings={ocrWarnings}
            onGoToTab={setTab}
            onRecordDecision={setPendingDecision}
          />
        </TabsContent>
        <TabsContent value="fields">
          <FieldsTab
            packageId={packageId}
            primaryDocumentId={primaryDocument?.document_id ?? null}
            fields={fields}
            fieldIds={fieldIds}
            validationFailures={validationFailures}
            onSelectEvidence={handleSelectEvidence}
            reviewed={mergedReviewed}
            onReviewed={handleReviewed}
          />
        </TabsContent>
        <TabsContent value="validation">
          <ValidationTab
            packageId={packageId}
            fields={fields}
            validationFailures={validationFailures}
            reviewed={mergedReviewed}
            onSelectField={handleSelectFieldFromValidation}
          />
        </TabsContent>
        <TabsContent value="policy">
          <PolicyTab packageId={packageId} />
        </TabsContent>
        <TabsContent value="audit">
          <AuditTab packageId={packageId} />
        </TabsContent>
      </div>
    </Tabs>
  );

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-3">
      <PackageHeader
        packageId={packageId}
        status={pkg.data.status}
        decision={pkg.data.decision ?? null}
        confidence={pkg.data.overall_confidence ?? null}
        documentCount={pkg.data.document_count ?? documents?.length ?? 0}
        failureCount={validationFailures.length}
        createdAt={pkg.data.created_at}
        updatedAt={pkg.data.updated_at}
        onRecordDecision={setPendingDecision}
      />

      {/* Mobile: document list opens in a Sheet, viewer + tabs stack full width */}
      <div className="flex items-center gap-2 md:hidden">
        <Sheet>
          <SheetTrigger asChild>
            <Button variant="outline" size="sm">
              <PanelLeft data-icon="inline-start" />
              Documents
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72">
            <SheetTitle className="p-4">Documents</SheetTitle>
            {documentListPanel}
          </SheetContent>
        </Sheet>
      </div>

      <div className="hidden flex-1 overflow-hidden rounded-md border md:block">
        <ResizablePanelGroup orientation="horizontal">
          <ResizablePanel defaultSize="18" minSize="12" maxSize="30">
            <div className="h-full overflow-auto border-r">{documentListPanel}</div>
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize="42" minSize="25">
            <DocumentViewer packageId={packageId} documentId={activeDocumentId} evidence={evidence} />
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize="40" minSize="28">
            {reviewPanel}
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>

      <div className="flex flex-1 flex-col gap-3 overflow-auto md:hidden">
        <div className="h-80 rounded-md border">
          <DocumentViewer packageId={packageId} documentId={activeDocumentId} evidence={evidence} />
        </div>
        {reviewPanel}
      </div>

      <DecisionDialog
        packageId={packageId}
        pending={pendingDecision}
        onClose={() => setPendingDecision(null)}
        unresolvedFailureCount={validationFailures.length}
        status={pkg.data.status}
      />
    </div>
  );
}
