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
import { StatusBadge, DecisionBadge, ConfidenceBadge } from "@/lib/status";
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
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
          {Array.from({ length: 7 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : summary.data ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
          <MetricCard label="Total packages" value={summary.data.total_packages} href="/packages" />
          <MetricCard label="Processing" value={summary.data.processing} href="/packages?status=processing" />
          <MetricCard
            label="Awaiting review"
            value={summary.data.awaiting_review}
            href="/reviews"
            tone="warning"
          />
          <MetricCard
            label="Ready for processing"
            value={summary.data.approved}
            href="/packages?decision=ready_for_processing"
            tone="success"
          />
          <MetricCard
            label="Needs review"
            value={summary.data.flagged}
            href="/reviews?decision=needs_review"
            tone="warning"
          />
          <MetricCard
            label="Blocked or incomplete"
            value={summary.data.escalated}
            href="/reviews?decision=blocked_or_incomplete"
            tone="danger"
          />
          <MetricCard
            label="Processing errors"
            value={summary.data.processing_errors}
            href="/packages?status=processing_error"
            tone="danger"
          />
        </div>
      ) : null}

      {summary.data && (
        <Card className="w-fit">
          <CardHeader>
            <CardTitle className="text-sm font-medium text-muted-foreground">Straight-through rate</CardTitle>
          </CardHeader>
          <CardContent>
            <span className="text-2xl font-semibold tabular-nums">
              {Math.round(summary.data.straight_through_rate * 100)}%
            </span>
          </CardContent>
        </Card>
      )}

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
                          href={`/reviews?validation_rule=${encodeURIComponent(f.rule)}`}
                          className="hover:underline"
                        >
                          {f.rule}
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
                    <TableHead>Decision</TableHead>
                    <TableHead className="text-right">Confidence</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {recent.data?.items.map((pkg) => (
                    <TableRow key={pkg.package_id} className="cursor-pointer" onClick={() => {
                      window.location.href = `/packages/${pkg.package_id}`;
                    }}>
                      <TableCell className="font-mono text-xs">{pkg.package_id.slice(0, 8)}</TableCell>
                      <TableCell>
                        <StatusBadge status={pkg.status} />
                      </TableCell>
                      <TableCell>
                        <DecisionBadge decision={pkg.decision} />
                      </TableCell>
                      <TableCell className="text-right">
                        <ConfidenceBadge confidence={pkg.overall_confidence} />
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
