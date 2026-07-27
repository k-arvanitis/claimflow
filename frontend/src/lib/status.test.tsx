import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge, DecisionBadge, ConfidenceBadge, ConfidenceLabel } from "@/lib/status";

describe("StatusBadge", () => {
  it("renders a human label for a known status", () => {
    render(<StatusBadge status="review_ready" />);
    expect(screen.getByText("Ready for review")).toBeInTheDocument();
  });

  it("falls back to the raw value for an unknown status", () => {
    render(<StatusBadge status="something_new" />);
    expect(screen.getByText("something_new")).toBeInTheDocument();
  });
});

describe("DecisionBadge", () => {
  it("shows 'No decision' when null", () => {
    render(<DecisionBadge decision={null} />);
    expect(screen.getByText("No decision")).toBeInTheDocument();
  });

  it("shows the decision label when present", () => {
    render(<DecisionBadge decision="escalated" />);
    expect(screen.getByText("Escalated")).toBeInTheDocument();
  });
});

describe("ConfidenceLabel", () => {
  it("classifies high/medium/low/unknown correctly", () => {
    expect(ConfidenceLabel(0.9).level).toBe("high");
    expect(ConfidenceLabel(0.6).level).toBe("medium");
    expect(ConfidenceLabel(0.2).level).toBe("low");
    expect(ConfidenceLabel(null).level).toBe("unknown");
  });
});

describe("ConfidenceBadge", () => {
  it("renders a percentage", () => {
    render(<ConfidenceBadge confidence={0.762} />);
    expect(screen.getByText("76%")).toBeInTheDocument();
  });
});
