"use client";

import { useRef, useState } from "react";
import { UploadCloud, X, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const ACCEPTED = [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp", ".docx"];
const MAX_FILE_BYTES = 20_000_000;
const MAX_FILES = 30;

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileDropzone({
  files,
  onChange,
  disabled,
}: {
  files: File[];
  onChange: (files: File[]) => void;
  disabled?: boolean;
}) {
  const [dragging, setDragging] = useState(false);
  const [rejections, setRejections] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  function addFiles(incoming: FileList | File[]) {
    const rejected: string[] = [];
    const accepted: File[] = [];
    for (const f of Array.from(incoming)) {
      const ext = "." + f.name.split(".").pop()?.toLowerCase();
      if (!ACCEPTED.includes(ext)) {
        rejected.push(`${f.name}: unsupported format`);
        continue;
      }
      if (f.size > MAX_FILE_BYTES) {
        rejected.push(`${f.name}: exceeds ${formatBytes(MAX_FILE_BYTES)} limit`);
        continue;
      }
      accepted.push(f);
    }
    const merged = [...files, ...accepted].slice(0, MAX_FILES);
    setRejections(rejected);
    onChange(merged);
  }

  return (
    <div className="flex flex-col gap-3">
      <div
        data-testid="dropzone"
        className={cn(
          "flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-10 text-center transition-colors",
          dragging ? "border-primary bg-accent/50" : "border-border",
          disabled && "pointer-events-none opacity-50"
        )}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
        }}
      >
        <UploadCloud className="size-8 text-muted-foreground" />
        <p className="text-sm font-medium">Drag and drop files, or</p>
        <Button variant="outline" size="sm" onClick={() => inputRef.current?.click()} disabled={disabled}>
          Choose files
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPTED.join(",")}
          className="hidden"
          onChange={(e) => e.target.files && addFiles(e.target.files)}
        />
        <p className="text-xs text-muted-foreground">
          PDF (born-digital or scanned), PNG/JPG/WEBP/TIFF/BMP, DOCX — up to {formatBytes(MAX_FILE_BYTES)} per file,{" "}
          {MAX_FILES} files per package
        </p>
      </div>

      {rejections.length > 0 && (
        <ul className="text-xs text-destructive">
          {rejections.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}

      {files.length > 0 && (
        <ul className="flex flex-col gap-1 rounded-md border p-2">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center justify-between gap-2 rounded px-2 py-1 text-sm hover:bg-accent/50">
              <span className="flex min-w-0 items-center gap-2">
                <FileText className="size-4 shrink-0 text-muted-foreground" />
                <span className="truncate">{f.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground">{formatBytes(f.size)}</span>
              </span>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Remove ${f.name}`}
                disabled={disabled}
                onClick={() => onChange(files.filter((_, idx) => idx !== i))}
              >
                <X />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
