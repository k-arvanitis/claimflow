import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PoliciesPage from "@/app/policies/page";

vi.mock("@/lib/queries", () => ({
  usePolicies: () => ({
    data: [
      { filename: "cms_manual.pdf", domain: "health", authority: "official_cms" },
      { filename: "health_policy.pdf", domain: "health", authority: "synthetic" },
    ],
    isLoading: false,
  }),
}));

describe("PoliciesPage", () => {
  it("shows every source and marks demonstration policies with an LLM note", () => {
    render(<PoliciesPage />);

    expect(screen.getByRole("button", { name: "cms_manual.pdf" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /health_policy\.pdf/i })).toBeInTheDocument();
    expect(screen.getByText("LLM summary")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remove/i })).not.toBeInTheDocument();
  });
});
