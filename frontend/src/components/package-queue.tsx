"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Download, MoreHorizontal, RefreshCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { StatusBadge, DecisionBadge, ConfidenceBadge } from "@/lib/status";
import { usePackageList, useReviewQueue, useDeletePackage, type PackageListParams } from "@/lib/queries";
import { API_BASE_URL } from "@/lib/api";
import { AlertTriangle, Inbox } from "lucide-react";
import { toast } from "sonner";

const DOMAINS = ["cms1500", "eob", "medicare_summary_notice", "xactimate", "declarations_page", "loan", "sba_form_413", "sba_form_2202"];
const STATUSES = ["queued", "processing", "review_ready", "completed", "processing_error", "validation_error", "retrieval_error"];
const DECISIONS = ["approved", "flagged", "escalated"];
const SORTS = [
  { value: "-created_at", label: "Newest first" },
  { value: "created_at", label: "Oldest first" },
  { value: "confidence", label: "Lowest confidence first" },
  { value: "-validation_failure_count", label: "Most failures first" },
];

export function PackageQueue({ mode }: { mode: "packages" | "reviews" }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const params: PackageListParams = {
    page: Number(searchParams.get("page") ?? 1),
    page_size: 25,
    status: searchParams.get("status") ?? undefined,
    domain: searchParams.get("domain") ?? undefined,
    decision: searchParams.get("decision") ?? undefined,
    validation_rule: searchParams.get("validation_rule") ?? undefined,
    confidence_min: searchParams.get("confidence_min") ? Number(searchParams.get("confidence_min")) : undefined,
    confidence_max: searchParams.get("confidence_max") ? Number(searchParams.get("confidence_max")) : undefined,
    date_from: searchParams.get("date_from") ?? undefined,
    date_to: searchParams.get("date_to") ?? undefined,
    search: searchParams.get("search") ?? undefined,
    sort: searchParams.get("sort") ?? "-created_at",
  };

  const packagesQuery = usePackageList(params, mode === "packages");
  const reviewsQuery = useReviewQueue(params, mode === "reviews");
  const query = mode === "packages" ? packagesQuery : reviewsQuery;
  const remove = useDeletePackage();

  function setParam(key: string, value: string | undefined) {
    const next = new URLSearchParams(searchParams.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    router.push(`?${next.toString()}`);
  }

  async function handleExport(packageId: string) {
    window.open(`${API_BASE_URL}/packages/${packageId}/export`, "_blank");
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Search package ID…"
          defaultValue={params.search}
          className="w-48"
          onKeyDown={(e) => {
            if (e.key === "Enter") setParam("search", (e.target as HTMLInputElement).value || undefined);
          }}
        />
        {mode === "packages" && (
          <Select value={params.status ?? "all"} onValueChange={(v) => setParam("status", v === "all" ? undefined : v)}>
            <SelectTrigger className="w-40">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="all">All statuses</SelectItem>
                {STATUSES.map((s) => (
                  <SelectItem key={s} value={s}>
                    {s.replace(/_/g, " ")}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        )}
        <Select value={params.domain ?? "all"} onValueChange={(v) => setParam("domain", v === "all" ? undefined : v)}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Domain" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="all">All domains</SelectItem>
              {DOMAINS.map((d) => (
                <SelectItem key={d} value={d}>
                  {d}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select value={params.decision ?? "all"} onValueChange={(v) => setParam("decision", v === "all" ? undefined : v)}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Decision" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="all">All decisions</SelectItem>
              {DECISIONS.map((d) => (
                <SelectItem key={d} value={d}>
                  {d}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Input
          placeholder="Validation rule"
          defaultValue={params.validation_rule}
          className="w-40"
          onKeyDown={(e) => {
            if (e.key === "Enter") setParam("validation_rule", (e.target as HTMLInputElement).value || undefined);
          }}
        />
        <Select value={params.sort ?? "-created_at"} onValueChange={(v) => setParam("sort", v)}>
          <SelectTrigger className="w-48">
            <SelectValue placeholder="Sort" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {SORTS.map((s) => (
                <SelectItem key={s.value} value={s.value}>
                  {s.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button variant="outline" size="sm" onClick={() => query.refetch()} disabled={query.isFetching}>
          <RefreshCw className={query.isFetching ? "animate-spin" : ""} data-icon="inline-start" />
          Refresh
        </Button>
      </div>

      {query.isError && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>Could not load packages</AlertTitle>
          <AlertDescription>Check that the ClaimFlow API is reachable.</AlertDescription>
        </Alert>
      )}

      {query.isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : query.data && query.data.items.length === 0 ? (
        <Empty className="py-12">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Inbox />
            </EmptyMedia>
            <EmptyTitle>{mode === "reviews" ? "Review queue is empty" : "No packages found"}</EmptyTitle>
            <EmptyDescription>
              {mode === "reviews"
                ? "No packages currently need human review."
                : "Try adjusting your filters, or upload a new package."}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : query.data ? (
        <div className="overflow-x-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Package</TableHead>
                <TableHead>Domain</TableHead>
                <TableHead>Documents</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Decision</TableHead>
                <TableHead>Confidence</TableHead>
                <TableHead>Failures</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.items.map((pkg) => (
                <TableRow
                  key={pkg.package_id}
                  className="cursor-pointer"
                  onClick={() => router.push(`/packages/${pkg.package_id}`)}
                >
                  <TableCell className="font-mono text-xs">{pkg.package_id.slice(0, 8)}</TableCell>
                  <TableCell className="text-sm">{pkg.domain ?? "—"}</TableCell>
                  <TableCell className="text-sm tabular-nums">{pkg.document_count}</TableCell>
                  <TableCell>
                    <StatusBadge status={pkg.status} />
                  </TableCell>
                  <TableCell>
                    <DecisionBadge decision={pkg.decision} />
                  </TableCell>
                  <TableCell>
                    <ConfidenceBadge confidence={pkg.overall_confidence} />
                  </TableCell>
                  <TableCell className="text-sm tabular-nums">{pkg.validation_failure_count}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {new Date(pkg.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" aria-label="Row actions">
                          <MoreHorizontal />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuGroup>
                          <DropdownMenuItem onClick={() => router.push(`/packages/${pkg.package_id}`)}>
                            Open
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={async () => {
                              try {
                                const res = await fetch(`${API_BASE_URL}/packages/${pkg.package_id}/process`, { method: "POST" });
                                if (!res.ok) throw new Error();
                                toast.success("Reprocessing started");
                                query.refetch();
                              } catch {
                                toast.error("Could not start reprocessing");
                              }
                            }}
                          >
                            <RefreshCw data-icon="inline-start" />
                            Reprocess
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => handleExport(pkg.package_id)}>
                            <Download data-icon="inline-start" />
                            Export
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            variant="destructive"
                            onClick={() => setPendingDelete(pkg.package_id)}
                          >
                            <Trash2 data-icon="inline-start" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuGroup>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}

      {query.data && query.data.total > query.data.page_size && (
        <Pagination>
          <PaginationContent>
            <PaginationItem>
              <PaginationPrevious
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  if (params.page && params.page > 1) setParam("page", String(params.page - 1));
                }}
              />
            </PaginationItem>
            <PaginationItem className="px-3 text-sm text-muted-foreground">
              Page {query.data.page} of {Math.ceil(query.data.total / query.data.page_size)}
            </PaginationItem>
            <PaginationItem>
              <PaginationNext
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  if (query.data && query.data.page * query.data.page_size < query.data.total) {
                    setParam("page", String(query.data.page + 1));
                  }
                }}
              />
            </PaginationItem>
          </PaginationContent>
        </Pagination>
      )}

      <AlertDialog open={pendingDelete !== null} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this package?</AlertDialogTitle>
            <AlertDialogDescription>
              This removes the package, its documents, fields, validation failures and decisions. Its audit trail
              is kept.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                if (!pendingDelete) return;
                try {
                  await remove.mutateAsync(pendingDelete);
                  toast.success("Package deleted");
                } catch {
                  toast.error("Could not delete package");
                } finally {
                  setPendingDelete(null);
                }
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
