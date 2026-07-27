import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DocumentViewer } from "@/components/workspace/document-viewer";

describe("DocumentViewer", () => {
  it("prompts to select a document when none is chosen", () => {
    render(<DocumentViewer packageId="pkg1" documentId={null} evidence={null} />);
    expect(screen.getByText(/select a document/i)).toBeInTheDocument();
  });

  it("shows the evidence quote and bakes the bbox into the rendered page URL", () => {
    render(
      <DocumentViewer
        packageId="pkg1"
        documentId="doc1"
        evidence={{ documentId: "doc1", page: 1, bbox: [10, 20, 30, 40], quote: "Total: $100" }}
      />
    );
    expect(screen.getByText(/Total: \$100/)).toBeInTheDocument();
    const img = document.querySelector("img") as HTMLImageElement;
    expect(img.src).toContain("/packages/pkg1/documents/doc1/pages/1");
    expect(img.src).toContain("bbox=10,20,30,40");
  });

  it("shows a restrained notice instead of a fabricated highlight when bbox is unavailable", () => {
    render(
      <DocumentViewer
        packageId="pkg1"
        documentId="doc1"
        evidence={{ documentId: "doc1", page: 1, bbox: null, quote: null }}
      />
    );
    expect(screen.getByText(/no source evidence available/i)).toBeInTheDocument();
    const img = document.querySelector("img") as HTMLImageElement;
    expect(img.src).not.toContain("bbox=");
  });
});
