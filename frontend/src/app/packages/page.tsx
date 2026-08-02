import { Suspense } from "react";
import Link from "next/link";
import { FilePlus2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PackageQueue } from "@/components/package-queue";
import { Skeleton } from "@/components/ui/skeleton";

export default function PackagesPage() {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Packages</h1>
        <Button asChild size="sm">
          <Link href="/packages/new">
            <FilePlus2 data-icon="inline-start" />
            New package
          </Link>
        </Button>
      </div>
      <Suspense fallback={<Skeleton className="h-64" />}>
        <PackageQueue />
      </Suspense>
    </div>
  );
}
