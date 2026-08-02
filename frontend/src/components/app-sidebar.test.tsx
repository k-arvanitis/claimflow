import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AppSidebar } from "@/components/app-sidebar";
import { SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { withQueryClient } from "@/test/query-wrapper";

let pathname = "/packages";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  addEventListener: () => {},
  removeEventListener: () => {},
})) as unknown as typeof window.matchMedia;

const getMock = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { GET: (...args: unknown[]) => getMock(...args) },
  API_BASE_URL: "http://localhost:8010",
}));

describe("AppSidebar", () => {
  it("highlights only 'Packages' on the packages list, not 'New package'", () => {
    pathname = "/packages";
    getMock.mockResolvedValue({ data: {}, error: null });
    render(withQueryClient(<TooltipProvider><SidebarProvider><AppSidebar /></SidebarProvider></TooltipProvider>));
    expect(screen.getByRole("link", { name: /^packages$/i })).toHaveAttribute("data-active", "true");
    expect(screen.getByRole("link", { name: /new package/i })).toHaveAttribute("data-active", "false");
  });

  it("highlights only 'New package' on the upload page, not 'Packages'", () => {
    pathname = "/packages/new";
    getMock.mockResolvedValue({ data: {}, error: null });
    render(withQueryClient(<TooltipProvider><SidebarProvider><AppSidebar /></SidebarProvider></TooltipProvider>));
    expect(screen.getByRole("link", { name: /new package/i })).toHaveAttribute("data-active", "true");
    expect(screen.getByRole("link", { name: /^packages$/i })).toHaveAttribute("data-active", "false");
  });

  it("highlights 'Packages' when viewing a package workspace", () => {
    pathname = "/packages/abc-123";
    getMock.mockResolvedValue({ data: {}, error: null });
    render(withQueryClient(<TooltipProvider><SidebarProvider><AppSidebar /></SidebarProvider></TooltipProvider>));
    expect(screen.getByRole("link", { name: /^packages$/i })).toHaveAttribute("data-active", "true");
    expect(screen.getByRole("link", { name: /new package/i })).toHaveAttribute("data-active", "false");
  });
});
