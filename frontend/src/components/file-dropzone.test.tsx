import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileDropzone } from "@/components/file-dropzone";

function dropFiles(dropzone: Element, files: File[]) {
  fireEvent.drop(dropzone, { dataTransfer: { files } });
}

function makeFile(name: string, sizeBytes: number, type = "application/pdf") {
  const file = new File(["x".repeat(Math.min(sizeBytes, 10))], name, { type });
  Object.defineProperty(file, "size", { value: sizeBytes });
  return file;
}

describe("FileDropzone", () => {
  it("rejects an unsupported file format dropped via drag-and-drop", () => {
    // Drag-and-drop bypasses the input's `accept` filter, which is exactly why
    // the dropzone must validate the extension itself, not just rely on `accept`.
    const onChange = vi.fn();
    render(<FileDropzone files={[]} onChange={onChange} />);
    const badFile = makeFile("malware.exe", 100);

    dropFiles(screen.getByTestId("dropzone"), [badFile]);

    expect(onChange).toHaveBeenCalledWith([]);
    expect(screen.getByText(/unsupported format/i)).toBeInTheDocument();
  });

  it("rejects a file over the size limit", async () => {
    const onChange = vi.fn();
    render(<FileDropzone files={[]} onChange={onChange} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;

    const bigFile = makeFile("huge.pdf", 21_000_000);
    await userEvent.upload(input, bigFile);

    expect(onChange).toHaveBeenCalledWith([]);
    expect(screen.getByText(/exceeds/i)).toBeInTheDocument();
  });

  it("accepts a valid file and lists it", async () => {
    const onChange = vi.fn();
    render(<FileDropzone files={[]} onChange={onChange} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;

    const goodFile = makeFile("claim.pdf", 1000);
    await userEvent.upload(input, goodFile);

    expect(onChange).toHaveBeenCalledWith([goodFile]);
  });

  it("removes a file from the list", async () => {
    const onChange = vi.fn();
    const file = makeFile("claim.pdf", 1000);
    render(<FileDropzone files={[file]} onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: /remove claim.pdf/i }));

    expect(onChange).toHaveBeenCalledWith([]);
  });
});
