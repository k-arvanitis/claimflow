"use client";

import { use, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
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

import { usePackage, useDocuments, usePackageReview, useDomainPack, invalidatePackage } from "@/lib/queries";
import type { PackageResult, ValidationFailure } from "@/lib/package-result";
import { PackageHeader } from "@/components/workspace/package-header";
import { DocumentList } from "@/components/workspace/document-list";
import { DocumentViewer, type EvidenceFocus } from "@/components/workspace/document-viewer";
import { OverviewTab } from "@/components/workspace/overview-tab";
import { FieldsTab, type ReviewState, type ReviewAction } from "@/components/workspace/fields-tab";
import { ValidationTab } from "@/components/workspace/validation-tab";
import { PolicyTab } from "@/components/workspace/policy-tab";
import { AuditTab } from "@/components/workspace/audit-tab";
import { DecisionDialog } from "@/components/workspace/decision-dialog";

export default function PackageWorkspacePage({ params }: { params: Promise<{ packageId: string }> }) {
  const { packageId } = use(params);

  const queryClient = useQueryClient();
  const pkg = usePackage(packageId, { poll: true });
  const domainPack = useDomainPack(pkg.data?.domain ?? null);
  const { data: documents } = useDocuments(packageId);
  const review = usePackageReview(packageId);

  // usePackage polls itself while processing, but documents/review/audit/policy are
  // separate queries fetched once on mount — without this they'd keep showing empty
  // results after background processing finishes, until the user reloads the page.
  const previousStatus = useRef(pkg.data?.status);
  useEffect(() => {
    const status = pkg.data?.status;
    if (status && previousStatus.current && status !== previousStatus.current) {
      invalidatePackage(queryClient, packageId);
    }
    previousStatus.current = status;
  }, [pkg.data?.status, queryClient, packageId]);

  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [tab, setTab] = useState("overview");
  const [pendingDecision, setPendingDecision] = useState<
    "ready_for_processing" | "needs_review" | "blocked_or_incomplete" | null
  >(null);
  const [reviewed, setReviewed] = useState<ReviewState>({});
  const [evidenceFocus, setEvidenceFocus] = useState<EvidenceFocus | null>(null);

  const result = pkg.data?.result as PackageResult | null | undefined;
  const fields = useMemo(() => result?.extraction_fields ?? [], [result]);
  const validationFailures = (review.data?.validation_failures ?? result?.validation_failures ?? []) as ValidationFailure[];

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

  function handleReviewed(fieldName: string, action: ReviewAction, value: unknown) {
    setReviewed((prev) => ({ ...prev, [fieldName]: { action, value } }));
  }

  function handleFocusEvidence(focus: EvidenceFocus) {
    setSelectedDocumentId(focus.documentId);
    setEvidenceFocus(focus);
  }

  if (pkg.isLoading) {
    return <Skeleton className="h-[70vh]" />;
  }

  if (pkg.isError || !pkg.data) {
    return (
      <Alert variant="destructive">
        <AlertTriangle />
        <AlertTitle>Case not found</AlertTitle>
        <AlertDescription>Could not load this case. It may not exist or the API is unreachable.</AlertDescription>
      </Alert>
    );
  }

  const documentListPanel = (
    <DocumentList
      packageId={packageId}
      selectedDocumentId={activeDocumentId}
      onSelect={setSelectedDocumentId}
      extractedDocType={pkg.data.domain ?? null}
    />
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
            systemRecommendation={pkg.data.system_recommendation ?? null}
            reviewerOutcome={pkg.data.reviewer_outcome ?? null}
            reviewerOverride={pkg.data.reviewer_override ?? false}
            confidence={pkg.data.overall_confidence ?? null}
            documentCount={pkg.data.document_count ?? documents?.length ?? 0}
            fields={fields}
            validationFailures={validationFailures}
            reviewed={mergedReviewed}
            ocrWarnings={ocrWarnings}
            onGoToTab={setTab}
          />
        </TabsContent>
        <TabsContent value="fields">
          <FieldsTab
            packageId={packageId}
            fields={fields}
            fieldIds={fieldIds}
            validationFailures={validationFailures}
            reviewed={mergedReviewed}
            onReviewed={handleReviewed}
            onFocusEvidence={handleFocusEvidence}
          />
        </TabsContent>
        <TabsContent value="validation">
          <ValidationTab
            packageId={packageId}
            fields={fields}
            validationFailures={validationFailures}
            reviewed={mergedReviewed}
            onSelectField={() => setTab("fields")}
            onGoToTab={setTab}
          />
        </TabsContent>
        <TabsContent value="policy">
          <PolicyTab packageId={packageId} validationFailures={validationFailures} />
        </TabsContent>
        <TabsContent value="audit">
          <AuditTab packageId={packageId} />
        </TabsContent>
      </div>
    </Tabs>
  );

  return (
    <div className="flex flex-col gap-3">
      <PackageHeader
        packageId={packageId}
        workflowName={domainPack.data?.display_name ?? pkg.data.domain ?? undefined}
        status={pkg.data.status}
        decision={pkg.data.decision ?? null}
        reviewerOutcome={pkg.data.reviewer_outcome ?? null}
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

      <div className="hidden rounded-md border md:block">
        {/* The resizable group defaults to a fixed, clipped height (100% of an
            ancestor + overflow:hidden) so its columns can never grow past the
            viewport. Overriding both here lets the PDF column grow to its full
            page height instead of scrolling in its own small box — the page
            itself scrolls to reveal it, while the doc list and review panel
            stay pinned to the viewport via their own sticky wrappers below. */}
        <ResizablePanelGroup orientation="horizontal" style={{ height: "auto", overflow: "visible" }}>
          <ResizablePanel defaultSize="14" minSize="10" maxSize="28" style={{ maxHeight: "none", overflow: "visible" }}>
            <div className="sticky top-4 max-h-[calc(100vh-8rem)] overflow-auto border-r">
              {documentListPanel}
            </div>
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel
            defaultSize="38"
            minSize="25"
            style={{ maxHeight: "none", overflowY: "visible", overflowX: "hidden" }}
          >
            <DocumentViewer packageId={packageId} documentId={activeDocumentId} focus={evidenceFocus} growToFit />
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize="48" minSize="28" style={{ maxHeight: "none", overflow: "visible" }}>
            <div className="sticky top-4 h-[calc(100vh-8rem)]">{reviewPanel}</div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>

      <div className="flex flex-1 flex-col gap-3 overflow-auto md:hidden">
        <div className="h-80 rounded-md border">
          <DocumentViewer packageId={packageId} documentId={activeDocumentId} focus={evidenceFocus} />
        </div>
        {reviewPanel}
      </div>

      <DecisionDialog
        packageId={packageId}
        pending={pendingDecision}
        onClose={() => setPendingDecision(null)}
        unresolvedFailureCount={validationFailures.length}
        status={pkg.data.status}
        currentDecision={pkg.data.decision ?? null}
      />
    </div>
  );
}
