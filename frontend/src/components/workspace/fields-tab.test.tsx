import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FieldsTab } from "@/components/workspace/fields-tab";
import { withQueryClient } from "@/test/query-wrapper";
import type { ExtractionField } from "@/lib/package-result";

const postMock = vi.fn().mockResolvedValue({
  data: { field_id: 1, action: "approve", reviewer: "reviewer", corrected_value: null },
  error: null,
});

vi.mock("@/lib/api", () => ({
  api: { POST: (...args: unknown[]) => postMock(...args) },
  API_BASE_URL: "http://localhost:8010",
}));

const fields: ExtractionField[] = [
  {
    name: "total_replacement_cost",
    value: 15932.0,
    confidence: 1.0,
    grounded: true,
    valid: true,
    evidence: { page: 1, text: "RCV $15932.00", bbox: [1, 2, 3, 4], block_type: "paragraph" },
    field_status: "found",
    parent_field: null,
  },
];

describe("FieldsTab", () => {
  it("submits an approve action for a scalar field", async () => {
    const onReviewed = vi.fn();
    render(
      withQueryClient(
        <FieldsTab
          packageId="pkg1"
          primaryDocumentId="doc1"
          fields={fields}
          fieldIds={{ total_replacement_cost: 162 }}
          validationFailures={[]}
          onSelectEvidence={vi.fn()}
          reviewed={{}}
          onReviewed={onReviewed}
        />
      )
    );

    await userEvent.click(screen.getByRole("button", { name: /approve/i }));

    expect(postMock).toHaveBeenCalledWith(
      "/packages/{package_id}/fields/{field_id}/review",
      expect.objectContaining({
        params: { path: { package_id: "pkg1", field_id: 162 } },
        body: expect.objectContaining({ action: "approve" }),
      })
    );
    expect(onReviewed).toHaveBeenCalledWith("total_replacement_cost", "approve", undefined);
  });

  it("opens evidence when the evidence button is clicked", async () => {
    const onSelectEvidence = vi.fn();
    render(
      withQueryClient(
        <FieldsTab
          packageId="pkg1"
          primaryDocumentId="doc1"
          fields={fields}
          fieldIds={{ total_replacement_cost: 162 }}
          validationFailures={[]}
          onSelectEvidence={onSelectEvidence}
          reviewed={{}}
          onReviewed={vi.fn()}
        />
      )
    );

    await userEvent.click(screen.getByRole("button", { name: /view evidence/i }));
    expect(onSelectEvidence).toHaveBeenCalledWith({
      documentId: "doc1",
      page: 1,
      bbox: [1, 2, 3, 4],
      quote: "RCV $15932.00",
    });
  });

  it("preserves numeric types when editing a scalar field", async () => {
    render(
      withQueryClient(
        <FieldsTab
          packageId="pkg1"
          primaryDocumentId="doc1"
          fields={fields}
          fieldIds={{ total_replacement_cost: 162 }}
          validationFailures={[]}
          onSelectEvidence={vi.fn()}
          reviewed={{}}
          onReviewed={vi.fn()}
        />
      )
    );

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const input = screen.getByRole("spinbutton", { name: /corrected value/i });
    await userEvent.clear(input);
    await userEvent.type(input, "42.5");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(postMock).toHaveBeenLastCalledWith(
      "/packages/{package_id}/fields/{field_id}/review",
      expect.objectContaining({ body: expect.objectContaining({ action: "edit", corrected_value: 42.5 }) })
    );
  });

  it("supports typed JSON edits for nested rows", async () => {
    const nestedFields: ExtractionField[] = [
      {
        name: "service_lines",
        value: [{ cpt_code: "99213", units: 1 }],
        confidence: 0.9,
        grounded: true,
        valid: true,
        evidence: null,
        field_status: "found",
        parent_field: null,
      },
      {
        name: "service_lines[0]",
        value: { cpt_code: "99213", units: 1 },
        confidence: 0.85,
        grounded: true,
        valid: true,
        evidence: null,
        field_status: "found",
        parent_field: "service_lines",
      },
    ];
    render(
      withQueryClient(
        <FieldsTab
          packageId="pkg1"
          primaryDocumentId="doc1"
          fields={nestedFields}
          fieldIds={{ "service_lines[0]": 200 }}
          validationFailures={[]}
          onSelectEvidence={vi.fn()}
          reviewed={{}}
          onReviewed={vi.fn()}
        />
      )
    );

    await userEvent.click(screen.getByRole("button", { name: "Edit row" }));
    const input = screen.getByRole("textbox", { name: /corrected value for service_lines\[0\]/i });
    fireEvent.change(input, { target: { value: JSON.stringify({ cpt_code: "99214", units: 2 }) } });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(postMock).toHaveBeenLastCalledWith(
      "/packages/{package_id}/fields/{field_id}/review",
      expect.objectContaining({
        body: expect.objectContaining({
          action: "edit",
          corrected_value: { cpt_code: "99214", units: 2 },
        }),
      })
    );
  });
});
