import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AuditTab } from "@/components/workspace/audit-tab";
import { withQueryClient } from "@/test/query-wrapper";

const getMock = vi.fn();

vi.mock("@/lib/api", () => ({
  api: { GET: (...args: unknown[]) => getMock(...args) },
  API_BASE_URL: "http://localhost:8010",
}));

describe("AuditTab", () => {
  it("shows an empty state with no events", async () => {
    getMock.mockResolvedValueOnce({ data: [], error: null });
    render(withQueryClient(<AuditTab packageId="pkg1" />));
    expect(await screen.findByText(/no audit events yet/i)).toBeInTheDocument();
  });

  it("renders audit events chronologically with actor and action", async () => {
    getMock.mockResolvedValueOnce({
      data: [
        { actor: "api", action: "upload", timestamp: "2026-07-13T12:00:00Z", detail: { filenames: ["a.pdf"] } },
        { actor: "reviewer", action: "decision", timestamp: "2026-07-13T12:05:00Z", detail: { decision: "approved" } },
      ],
      error: null,
    });
    render(withQueryClient(<AuditTab packageId="pkg1" />));
    expect(await screen.findByText("upload")).toBeInTheDocument();
    expect(screen.getByText("decision")).toBeInTheDocument();
    expect(screen.getByText("reviewer")).toBeInTheDocument();
  });
});
