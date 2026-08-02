"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertTriangle } from "lucide-react";
import { pageImageUrl } from "@/lib/page-image";

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2.5;
const ZOOM_STEP = 0.25;

export type EvidenceFocus = {
  documentId: string;
  page: number;
  bbox?: [number, number, number, number];
  /** Bumped on every request so re-clicking the same page/field still re-triggers the jump. */
  token: number;
};

export function DocumentViewer({
  packageId,
  documentId,
  focus,
  growToFit = false,
}: {
  packageId: string;
  documentId: string | null;
  /** External request to jump to a page and highlight a bbox (from a field's evidence). */
  focus?: EvidenceFocus | null;
  /** Render at the page's natural height instead of clipping to a fixed-height,
   * internally-scrolling box — used when the surrounding layout wants the page
   * scroll itself to reveal the rest of the document. */
  growToFit?: boolean;
}) {
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [loading, setLoading] = useState(true);
  const [renderError, setRenderError] = useState(false);

  const [appliedFocusToken, setAppliedFocusToken] = useState<number | null>(null);
  if (focus && focus.documentId === documentId && focus.token !== appliedFocusToken) {
    setAppliedFocusToken(focus.token);
    if (focus.page !== page) setPage(focus.page);
  }
  const highlightBbox = focus && focus.documentId === documentId && focus.page === page ? focus.bbox : undefined;

  // Skeleton only on a genuine page/document change. A bbox-only change (jumping to a
  // field's evidence on the page already showing) swaps the <img> src in place — the
  // browser keeps the old frame visible until the new one loads, so no blank flash.
  const renderKey = `${documentId ?? ""}:${page}`;
  const [prevRenderKey, setPrevRenderKey] = useState(renderKey);
  if (renderKey !== prevRenderKey) {
    setPrevRenderKey(renderKey);
    setLoading(true);
    setRenderError(false);
  }

  if (!documentId) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Select a document to view its pages.
      </div>
    );
  }

  const src = pageImageUrl(packageId, documentId, page, highlightBbox);

  return (
    <div className={growToFit ? "flex flex-col" : "flex h-full flex-col"}>
      <div className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b bg-background p-2">
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

      {/* Centering this with flexbox (justify-center) makes the overflow unreachable by
          scroll on the leading edge once the zoomed image is wider than the container —
          a well-known flexbox scroll limitation. Block-level margin:auto centering
          doesn't have that problem. */}
      <div className={growToFit ? "overflow-x-auto overflow-y-visible" : "flex-1 overflow-auto"}>
        <div className="p-4">
          {loading && !renderError && <Skeleton className="mx-auto h-[800px] w-[600px]" />}
          {renderError ? (
            <Alert variant="destructive" className="mx-auto max-w-md">
              <AlertTriangle />
              <AlertTitle>Could not render this page</AlertTitle>
              <AlertDescription>The document page failed to render. Try another page or reprocess.</AlertDescription>
            </Alert>
          ) : (
            <>
              {/* Dynamic, already-rendered page PNG; keep the native element so
                  naturalWidth and exact query parameters remain available. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={src}
                alt={`Page ${page}`}
                style={{ width: `${zoom * 100}%`, maxWidth: "900px", display: loading ? "none" : "block" }}
                className="mx-auto"
                onLoad={() => setLoading(false)}
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
