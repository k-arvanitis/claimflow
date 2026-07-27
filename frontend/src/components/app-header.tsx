"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import { BackendStatus } from "@/components/backend-status";
import { ThemeToggle } from "@/components/theme-toggle";

const LABELS: Record<string, string> = {
  dashboard: "Dashboard",
  packages: "Packages",
  new: "New package",
  reviews: "Review queue",
  settings: "Settings",
};

export function AppHeader() {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b bg-card px-4">
      <div className="flex items-center gap-2">
        <SidebarTrigger />
        <Separator orientation="vertical" className="h-4" />
        <Breadcrumb>
          <BreadcrumbList>
            {segments.length === 0 && (
              <BreadcrumbItem>
                <BreadcrumbPage>Dashboard</BreadcrumbPage>
              </BreadcrumbItem>
            )}
            {segments.map((seg, i) => {
              const href = "/" + segments.slice(0, i + 1).join("/");
              const isLast = i === segments.length - 1;
              const label = LABELS[seg] ?? (seg.length > 12 ? `${seg.slice(0, 8)}…` : seg);
              return (
                <span key={href} className="flex items-center gap-1.5">
                  {i > 0 && <BreadcrumbSeparator />}
                  <BreadcrumbItem>
                    {isLast ? (
                      <BreadcrumbPage>{label}</BreadcrumbPage>
                    ) : (
                      <BreadcrumbLink asChild>
                        <Link href={href}>{label}</Link>
                      </BreadcrumbLink>
                    )}
                  </BreadcrumbItem>
                </span>
              );
            })}
          </BreadcrumbList>
        </Breadcrumb>
      </div>
      <div className="flex items-center gap-3">
        <BackendStatus />
        <ThemeToggle />
      </div>
    </header>
  );
}
