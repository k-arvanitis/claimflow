import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ValidationTab } from "@/components/workspace/validation-tab";
import { withQueryClient } from "@/test/query-wrapper";
import type { ExtractionField, ValidationFailure } from "@/lib/package-result";

const postMock = vi.fn().mockResolvedValue({
  data: {
    validation_failures: [],
    decision: "ready_for_processing",
    decision_changed: true,
    previous_decision: "needs_review",
  },
  error: null,
});

vi.mock("@/lib/api", () => ({
  api: { POST: (...args: unknown[]) => postMock(...args) },
  API_BASE_URL: "http://localhost:8010",
}));

const fields: ExtractionField[] = [
  {
    name: "claim_number",
    value: null,
    confidence: 0.3,
    grounded: false,
    valid: true,
    evidence: null,
    field_status: "not_found",
    parent_field: null,
  },
];

const failures: ValidationFailure[] = [{ field: "claim_number", rule: "mandatory", reason: "claim_number is required" }];

describe("ValidationTab", () => {
  it("shows an empty state when there are no failures", () => {
    render(
      withQueryClient(
        <ValidationTab packageId="pkg1" fields={fields} validationFailures={[]} reviewed={{}} onSelectField={vi.fn()} />
      )
    );
    expect(screen.getByText(/no validation failures/i)).toBeInTheDocument();
  });

  it("re-runs validation with corrected field values from the review state", async () => {
    render(
      withQueryClient(
        <ValidationTab
          packageId="pkg1"
          fields={fields}
          validationFailures={failures}
          reviewed={{ claim_number: { action: "edit", value: "CLM-9001" } }}
          onSelectField={vi.fn()}
        />
      )
    );

    await userEvent.click(screen.getByRole("button", { name: /re-run validation/i }));

    expect(postMock).toHaveBeenCalledWith(
      "/packages/{package_id}/validation/re-run",
      expect.objectContaining({
        params: { path: { package_id: "pkg1" } },
        body: { corrected_fields: { claim_number: "CLM-9001" } },
      })
    );
    expect(await screen.findByText(/resulted in decision/i)).toBeInTheDocument();
    expect(screen.getByText("ready_for_processing")).toBeInTheDocument();
  });

  it("sends rejected nested rows as removals", async () => {
    render(
      withQueryClient(
        <ValidationTab
          packageId="pkg1"
          fields={fields}
          validationFailures={failures}
          reviewed={{ "service_lines[0]": { action: "reject", value: undefined } }}
          onSelectField={vi.fn()}
        />
      )
    );

    await userEvent.click(screen.getByRole("button", { name: /re-run validation/i }));

    expect(postMock).toHaveBeenLastCalledWith(
      "/packages/{package_id}/validation/re-run",
      expect.objectContaining({ body: { corrected_fields: { "service_lines[0]": null } } })
    );
  });
});
