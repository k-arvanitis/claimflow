import { Suspense } from "react";
import { PackageQueue } from "@/components/package-queue";
import { Skeleton } from "@/components/ui/skeleton";

export default function ReviewsPage() {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold">Review queue</h1>
        <p className="text-sm text-muted-foreground">Packages awaiting human review, across the whole system.</p>
      </div>
      <Suspense fallback={<Skeleton className="h-64" />}>
        <PackageQueue mode="reviews" />
      </Suspense>
    </div>
  );
}
