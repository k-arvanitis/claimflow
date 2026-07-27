"use client";

import { useRef, useState } from "react";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertTriangle } from "lucide-react";
import { pageImageUrl } from "@/lib/page-image";

export type SelectedEvidence = {
  documentId: string;
  page: number;
  bbox: [number, number, number, number] | null;
  quote: string | null;
};

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2.5;
const ZOOM_STEP = 0.25;

export function DocumentViewer({
  packageId,
  documentId,
  evidence,
}: {
  packageId: string;
  documentId: string | null;
  evidence: SelectedEvidence | null;
}) {
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [loading, setLoading] = useState(true);
  const [renderError, setRenderError] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  // Adjust state during render (React's documented pattern for resetting state when
  // a prop changes) rather than in an Effect, which would cause an extra render pass.
  const [prevEvidence, setPrevEvidence] = useState(evidence);
  if (evidence !== prevEvidence) {
    setPrevEvidence(evidence);
    if (evidence && evidence.documentId === documentId) {
      setPage(evidence.page);
    }
  }

  const renderKey = `${documentId ?? ""}:${page}`;
  const [prevRenderKey, setPrevRenderKey] = useState(renderKey);
  if (renderKey !== prevRenderKey) {
    setPrevRenderKey(renderKey);
    setLoading(true);
    setRenderError(false);
  }

  function handleImageLoad() {
    setLoading(false);
    if (!imgRef.current || !scrollRef.current || !evidence?.bbox) return;
    const img = imgRef.current;
    const [, y0, , y1] = evidence.bbox;
    const fractionY = ((y0 + y1) / 2) / img.naturalHeight;
    const container = scrollRef.current;
    const targetScroll = fractionY * img.clientHeight - container.clientHeight / 2;
    container.scrollTo({ top: Math.max(0, targetScroll), behavior: "smooth" });
  }

  if (!documentId) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Select a document to view its pages.
      </div>
    );
  }

  const highlightBbox = evidence && evidence.documentId === documentId && evidence.page === page ? evidence.bbox : null;
  const src = pageImageUrl(packageId, documentId, page, highlightBbox ?? undefined);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-2 border-b p-2">
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            <ChevronLeft />
          </Button>
          <span className="text-sm tabular-nums">Page {page}</span>
          <Button variant="ghost" size="icon" aria-label="Next page" onClick={() => setPage((p) => p + 1)}>
            <ChevronRight />
          </Button>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" aria-label="Zoom out" disabled={zoom <= MIN_ZOOM} onClick={() => setZoom((z) => Math.max(MIN_ZOOM, z - ZOOM_STEP))}>
            <ZoomOut />
          </Button>
          <span className="w-12 text-center text-xs tabular-nums">{Math.round(zoom * 100)}%</span>
          <Button variant="ghost" size="icon" aria-label="Zoom in" disabled={zoom >= MAX_ZOOM} onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z + ZOOM_STEP))}>
            <ZoomIn />
          </Button>
          <Button variant="ghost" size="icon" aria-label="Reset zoom" onClick={() => setZoom(1)}>
            <RotateCcw />
          </Button>
        </div>
      </div>

      {evidence && evidence.documentId === documentId && (
        <div className="border-b bg-muted/50 p-2 text-xs">
          {evidence.quote ? (
            <span>
              Evidence: <span className="italic">&ldquo;{evidence.quote}&rdquo;</span>
            </span>
          ) : (
            <span className="text-muted-foreground">
              No source evidence available for this field — a highlighted region is not shown.
            </span>
          )}
        </div>
      )}

      <div ref={scrollRef} className="flex-1 overflow-auto">
        <div className="flex justify-center p-4">
          {loading && !renderError && <Skeleton className="h-[800px] w-[600px]" />}
          {renderError ? (
            <Alert variant="destructive" className="max-w-md">
              <AlertTriangle />
              <AlertTitle>Could not render this page</AlertTitle>
              <AlertDescription>The document page failed to render. Try another page or reprocess.</AlertDescription>
            </Alert>
          ) : (
            <>
              {/* Dynamic, already-rendered evidence PNG; keep the native element so
                  naturalWidth and exact query parameters remain available. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                ref={imgRef}
                src={src}
                alt={`Page ${page}`}
                style={{ width: `${zoom * 100}%`, maxWidth: "900px", display: loading ? "none" : "block" }}
                onLoad={handleImageLoad}
                onError={() => {
                  setLoading(false);
                  setRenderError(true);
                }}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
