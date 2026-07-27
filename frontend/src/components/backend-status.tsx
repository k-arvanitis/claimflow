"use client";

import { useBackendStatus } from "@/hooks/use-backend-status";
import { cn } from "@/lib/utils";

export function BackendStatus() {
  const online = useBackendStatus();
  const label = online === null ? "Checking backend…" : online ? "Backend online" : "Backend unreachable";
  const dot = online === null ? "bg-muted-foreground" : online ? "bg-success" : "bg-destructive";

  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className={cn("size-2 rounded-full", dot)} aria-hidden />
      <span>{label}</span>
    </div>
  );
}
