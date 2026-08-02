import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DocumentViewer } from "@/components/workspace/document-viewer";

describe("DocumentViewer", () => {
  it("prompts to select a document when none is chosen", () => {
    render(<DocumentViewer packageId="pkg1" documentId={null} />);
    expect(screen.getByText(/select a document/i)).toBeInTheDocument();
  });

  it("renders the page image for the selected document", () => {
    render(<DocumentViewer packageId="pkg1" documentId="doc1" />);
    const img = document.querySelector("img") as HTMLImageElement;
    expect(img.src).toContain("/packages/pkg1/documents/doc1/pages/1");
  });

  it("swaps the highlight in place without a skeleton flash when only bbox changes", () => {
    const { rerender } = render(<DocumentViewer packageId="pkg1" documentId="doc1" />);
    const img = document.querySelector("img") as HTMLImageElement;
    fireEvent.load(img); // finish the initial load
    expect(img).toBeVisible();

    rerender(
      <DocumentViewer
        packageId="pkg1"
        documentId="doc1"
        focus={{ documentId: "doc1", page: 1, bbox: [1, 2, 3, 4], token: 1 }}
      />
    );

    // Same page — should update the src in place, not blank out behind a skeleton.
    expect(document.querySelector('[data-slot="skeleton"]')).not.toBeInTheDocument();
    expect(img).toBeVisible();
    expect(img.src).toContain("bbox=1,2,3,4");
  });
});
