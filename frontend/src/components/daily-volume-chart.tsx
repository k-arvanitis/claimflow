"use client";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function DailyVolumeChart({ data }: { data: { date: string; count: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  // Label the first, middle, and last bar only — 30 labels would collide.
  const labelIndices = new Set([0, Math.floor((data.length - 1) / 2), data.length - 1]);

  return (
    <TooltipProvider>
      <div className="flex h-32 items-end gap-[3px]">
        {data.map((d) => (
          <Tooltip key={d.date}>
            <TooltipTrigger asChild>
              <div className="flex h-full flex-1 flex-col justify-end">
                <div
                  className="w-full rounded-t-sm bg-success/80 transition-colors hover:bg-success"
                  style={{ height: `${Math.max((d.count / max) * 100, d.count > 0 ? 4 : 1)}%` }}
                />
              </div>
            </TooltipTrigger>
            <TooltipContent>
              {formatDate(d.date)}: {d.count} package{d.count === 1 ? "" : "s"}
            </TooltipContent>
          </Tooltip>
        ))}
      </div>
      <div className="mt-1 flex text-xs text-muted-foreground">
        {data.map((d, i) => (
          <div key={d.date} className="flex-1 text-center first:text-left last:text-right">
            {labelIndices.has(i) ? formatDate(d.date) : ""}
          </div>
        ))}
      </div>
    </TooltipProvider>
  );
}
