import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DecisionDialog } from "@/components/workspace/decision-dialog";
import { withQueryClient } from "@/test/query-wrapper";

const postMock = vi.fn().mockResolvedValue({ data: { package_id: "p1", decision: "escalated" }, error: null });

vi.mock("@/lib/api", () => ({
  api: { POST: (...args: unknown[]) => postMock(...args) },
  API_BASE_URL: "http://localhost:8010",
}));

describe("DecisionDialog", () => {
  it("requires a reason before allowing an escalation to be confirmed", async () => {
    render(
      withQueryClient(
        <DecisionDialog packageId="p1" pending="escalated" onClose={vi.fn()} unresolvedFailureCount={0} status="review_ready" />
      )
    );

    const confirm = screen.getByRole("button", { name: /confirm/i });
    expect(confirm).toBeDisabled();

    await userEvent.type(screen.getByPlaceholderText(/reason for escalation/i), "Needs supervisor sign-off");
    expect(confirm).toBeEnabled();
  });

  it("warns about unresolved validation failures before approval", () => {
    render(
      withQueryClient(
        <DecisionDialog packageId="p1" pending="approved" onClose={vi.fn()} unresolvedFailureCount={2} status="review_ready" />
      )
    );

    expect(screen.getByText(/unresolved validation failures/i)).toBeInTheDocument();
  });

  it("submits the decision and calls onClose", async () => {
    const onClose = vi.fn();
    render(
      withQueryClient(
        <DecisionDialog packageId="p1" pending="approved" onClose={onClose} unresolvedFailureCount={0} status="review_ready" />
      )
    );

    await userEvent.click(screen.getByRole("button", { name: /confirm/i }));

    expect(postMock).toHaveBeenCalledWith(
      "/packages/{package_id}/decision",
      expect.objectContaining({ params: { path: { package_id: "p1" } } })
    );
    expect(onClose).toHaveBeenCalled();
  });
});
