import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PolicyTab } from "@/components/workspace/policy-tab";
import { withQueryClient } from "@/test/query-wrapper";
import type { ValidationFailure } from "@/lib/package-result";

const getMock = vi.fn();

vi.mock("@/lib/api", () => ({
  api: { GET: (...args: unknown[]) => getMock(...args) },
  API_BASE_URL: "http://localhost:8010",
}));

describe("PolicyTab", () => {
  it("distinguishes found vs not-found policy evidence", async () => {
    getMock.mockResolvedValueOnce({
      data: [
        {
          question: "What is the policy on charge discrepancies?",
          answer: "Chapter 26 requires...",
          citations: ["[1] cms_manual.pdf — ..."],
          field: "total_charge",
          rule: "arithmetic",
          status: "found",
        },
        {
          question: "What does policy say about a bad NPI?",
          answer: "No relevant policy document found.",
          citations: [],
          field: "billing_provider_npi",
          rule: "mandatory",
          status: "not_found",
        },
      ],
      error: null,
    });

    render(withQueryClient(<PolicyTab packageId="pkg1" />));

    expect(await screen.findByText("Found")).toBeInTheDocument();
    expect(screen.getByText("Not found in corpus")).toBeInTheDocument();
  });

  it("labels validation failures that never needed a policy lookup", async () => {
    getMock.mockResolvedValueOnce({ data: [], error: null });
    const validationFailures: ValidationFailure[] = [
      {
        field: "total_charge",
        rule: "arithmetic",
        reason: "Line sum does not match total",
        severity: "warning",
        policy_required: false,
      },
    ];

    render(withQueryClient(<PolicyTab packageId="pkg1" validationFailures={validationFailures} />));

    expect(await screen.findByText(/no policy lookup needed/i)).toBeInTheDocument();
  });
});
