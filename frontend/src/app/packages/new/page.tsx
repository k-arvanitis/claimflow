"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, CheckCircle2, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { FileDropzone } from "@/components/file-dropzone";
import { StatusBadge } from "@/lib/status";
import { API_BASE_URL } from "@/lib/api";
import { usePackage } from "@/lib/queries";

type UploadState = "idle" | "uploading" | "error";

export default function NewPackagePage() {
  const [files, setFiles] = useState<File[]>([]);
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [packageId, setPackageId] = useState<string | null>(null);

  const pkg = usePackage(packageId ?? "", { poll: true });

  function upload() {
    setUploadState("uploading");
    setUploadError(null);
    setUploadProgress(0);

    const form = new FormData();
    files.forEach((f) => form.append("files", f));

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/packages`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) setUploadProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const body = JSON.parse(xhr.responseText);
        setPackageId(body.package_id);
        setUploadState("idle");
      } else {
        try {
          const body = JSON.parse(xhr.responseText);
          setUploadError(body?.error?.message ?? "Upload failed");
        } catch {
          setUploadError("Upload failed");
        }
        setUploadState("error");
      }
    };
    xhr.onerror = () => {
      setUploadError("Could not reach the ClaimFlow API");
      setUploadState("error");
    };
    xhr.send(form);
  }

  if (packageId) {
    const status = pkg.data?.status;
    const isTerminal = status === "review_ready" || status === "completed" || (status ?? "").endsWith("error");
    return (
      <div className="mx-auto flex max-w-xl flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Package created</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Package ID</span>
              <span className="font-mono">{packageId}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Documents</span>
              <span>{files.length}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Status</span>
              {status ? <StatusBadge status={status} /> : <span>—</span>}
            </div>
            {!isTerminal && (
              <p className="text-xs text-muted-foreground">
                Processing runs in the background — this updates automatically.
              </p>
            )}
            <Button asChild>
              <Link href={`/packages/${packageId}`}>
                Open package workspace
                <ArrowRight data-icon="inline-end" />
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold">New package</h1>
        <p className="text-sm text-muted-foreground">Upload one or more documents that make up a claim package.</p>
      </div>

      <FileDropzone files={files} onChange={setFiles} disabled={uploadState === "uploading"} />

      {uploadState === "uploading" && (
        <div className="flex flex-col gap-1">
          <Progress value={uploadProgress} />
          <span className="text-xs text-muted-foreground">Uploading… {uploadProgress}%</span>
        </div>
      )}

      {uploadState === "error" && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>Upload failed</AlertTitle>
          <AlertDescription>{uploadError}</AlertDescription>
        </Alert>
      )}

      <Button disabled={files.length === 0 || uploadState === "uploading"} onClick={upload}>
        <CheckCircle2 data-icon="inline-start" />
        Upload {files.length > 0 ? `${files.length} file${files.length > 1 ? "s" : ""}` : ""}
      </Button>
    </div>
  );
}
