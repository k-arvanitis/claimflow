import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PackageQueue } from "@/components/package-queue";
import { withQueryClient } from "@/test/query-wrapper";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(),
}));

const getMock = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { GET: (...args: unknown[]) => getMock(...args) },
  API_BASE_URL: "http://localhost:8010",
}));

describe("PackageQueue", () => {
  it("shows an empty state for the review queue when nothing needs review", async () => {
    getMock.mockResolvedValueOnce({ data: { items: [], page: 1, page_size: 25, total: 0 }, error: null });
    render(withQueryClient(<PackageQueue mode="reviews" />));
    expect(await screen.findByText(/review queue is empty/i)).toBeInTheDocument();
  });

  it("renders package rows with status, decision and confidence", async () => {
    getMock.mockResolvedValueOnce({
      data: {
        items: [
          {
            package_id: "pkg-123",
            status: "review_ready",
            created_at: "2026-07-13T12:00:00Z",
            updated_at: "2026-07-13T12:05:00Z",
            domain: "cms1500",
            decision: "needs_review",
            overall_confidence: 0.6,
            document_count: 1,
            validation_failure_count: 1,
          },
        ],
        page: 1,
        page_size: 25,
        total: 1,
      },
      error: null,
    });
    render(withQueryClient(<PackageQueue mode="packages" />));
    expect(await screen.findByText("cms1500")).toBeInTheDocument();
    expect(screen.getByText("Ready for review")).toBeInTheDocument();
    expect(screen.getByText("Needs manual review")).toBeInTheDocument();
  });

  it("shows a backend error state", async () => {
    getMock.mockRejectedValueOnce(new Error("network down"));
    render(withQueryClient(<PackageQueue mode="packages" />));
    expect(await screen.findByText(/could not load packages/i)).toBeInTheDocument();
  });
});
