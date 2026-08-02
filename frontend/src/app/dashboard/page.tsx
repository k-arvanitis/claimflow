"use client";

import Link from "next/link";
import { RefreshCw, AlertTriangle, Inbox } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { MetricCard } from "@/components/metric-card";
import { DailyVolumeChart } from "@/components/daily-volume-chart";
import { DecisionBadge, ruleLabel } from "@/lib/status";
import { useDashboardSummary, usePackageList } from "@/lib/queries";

export default function DashboardPage() {
  const summary = useDashboardSummary();
  const recent = usePackageList({ page: 1, page_size: 8, sort: "-created_at" });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            {summary.dataUpdatedAt
              ? `Last refreshed ${new Date(summary.dataUpdatedAt).toLocaleTimeString()}`
              : "Loading…"}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => summary.refetch()} disabled={summary.isFetching}>
          <RefreshCw className={summary.isFetching ? "animate-spin" : ""} data-icon="inline-start" />
          Refresh
        </Button>
      </div>

      {summary.isError && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>Backend unavailable</AlertTitle>
          <AlertDescription>Could not load dashboard summary. Check the API connection.</AlertDescription>
        </Alert>
      )}

      {summary.isLoading ? (
        <div className="grid grid-cols-3 gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : summary.data ? (
        (() => {
          const total = summary.data.total_packages;
          const needsReview = summary.data.flagged + summary.data.escalated + summary.data.processing_errors;
          const ready = summary.data.approved;
          const pct = (n: number) => (total > 0 ? `${Math.round((n / total) * 100)}%` : "—");
          return (
            <div className="grid grid-cols-3 gap-3">
              <MetricCard label="Uploaded" value={total} href="/packages" />
              <MetricCard
                label="Needs review"
                value={`${needsReview} (${pct(needsReview)})`}
                href="/packages?status=review_ready"
                tone="warning"
              />
              <MetricCard
                label="Approved"
                value={`${ready} (${pct(ready)})`}
                href="/packages?decision=ready_for_processing"
                tone="success"
              />
            </div>
          );
        })()
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Packages uploaded, last 30 days</CardTitle>
        </CardHeader>
        <CardContent>
          {summary.isLoading ? (
            <Skeleton className="h-32" />
          ) : summary.data ? (
            <DailyVolumeChart data={summary.data.packages_by_day} />
          ) : null}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Top validation failures</CardTitle>
          </CardHeader>
          <CardContent>
            {summary.data && summary.data.top_validation_failures.length === 0 ? (
              <Empty className="py-6">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <Inbox />
                  </EmptyMedia>
                  <EmptyTitle>No validation failures</EmptyTitle>
                  <EmptyDescription>Nothing has failed a deterministic rule yet.</EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Rule</TableHead>
                    <TableHead className="text-right">Count</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {summary.data?.top_validation_failures.map((f) => (
                    <TableRow key={f.rule}>
                      <TableCell>
                        <Link
                          href={`/packages?validation_rule=${encodeURIComponent(f.rule)}`}
                          className="hover:underline"
                          title={f.rule}
                        >
                          {ruleLabel(f.rule)}
                        </Link>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{f.count}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Recently processed packages</CardTitle>
          </CardHeader>
          <CardContent>
            {recent.isLoading ? (
              <div className="flex flex-col gap-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-8" />
                ))}
              </div>
            ) : recent.data && recent.data.items.length === 0 ? (
              <Empty className="py-6">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <Inbox />
                  </EmptyMedia>
                  <EmptyTitle>No packages yet</EmptyTitle>
                  <EmptyDescription>Upload a package to get started.</EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Package</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {recent.data?.items.map((pkg) => (
                    <TableRow key={pkg.package_id} className="cursor-pointer" onClick={() => {
                      window.location.href = `/packages/${pkg.package_id}`;
                    }}>
                      <TableCell className="font-mono text-xs">{pkg.package_id.slice(0, 8)}</TableCell>
                      <TableCell>
                        <DecisionBadge
                          decision={
                            pkg.reviewer_outcome === "ready_for_processing" || pkg.reviewer_outcome === "blocked_or_incomplete"
                              ? pkg.reviewer_outcome
                              : pkg.system_recommendation
                          }
                          resolved={
                            pkg.reviewer_outcome === "ready_for_processing" || pkg.reviewer_outcome === "blocked_or_incomplete"
                          }
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
