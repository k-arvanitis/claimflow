"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { FileDropzone } from "@/components/file-dropzone";
import { StatusBadge } from "@/lib/status";
import { API_BASE_URL } from "@/lib/api";
import { usePackage, useDomainPacks } from "@/lib/queries";
import type { PackageResult } from "@/lib/package-result";

type UploadState = "idle" | "uploading" | "error";

// ponytail: static copy per the 3 reference workflows — no backend "description" field to
// duplicate this from yet; display_name/document_types below still come from the real API.
const WORKFLOWS = [
  {
    key: "cms1500",
    title: "CMS-1500 Claim Review",
    description:
      "Process CMS-1500 healthcare claim packages, extract claim and provider information, validate identifiers and medical codes, check dates and totals, and retrieve relevant CMS policy guidance when required.",
    chips: ["CMS-1500 forms", "Supporting documents", "NPI validation", "ICD-10 / CPT lookups", "CMS policy evidence"],
  },
  {
    key: "xactimate",
    title: "Property Estimate Review",
    description:
      "Process Xactimate property-damage estimates, extract estimate summaries and line items, validate arithmetic rollups, depreciation and ACV values, and flag inconsistent estimate calculations.",
    chips: ["Xactimate estimates", "Nested line items", "Arithmetic reconciliation", "Depreciation checks", "Estimate consistency"],
  },
  {
    key: "loan",
    title: "SBA Application Review",
    description:
      "Process SBA loan-application packages, extract applicant and financial information, check required documents, validate dates and totals, and identify incomplete or inconsistent application data.",
    chips: ["Multi-document applications", "Applicant information", "Financial consistency", "Required-document checks", "Completeness validation"],
  },
] as const;

export default function NewPackagePage() {
  const [workflow, setWorkflow] = useState<string | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [packageId, setPackageId] = useState<string | null>(null);

  const domainPacks = useDomainPacks();
  const pkg = usePackage(packageId ?? "", { poll: true });
  const result = pkg.data?.result as PackageResult | null | undefined;
  const mismatch = result?.domain_mismatch ?? false;
  const detectedDomain = result?.detected_domain;

  function upload() {
    setUploadState("uploading");
    setUploadError(null);
    setUploadProgress(0);

    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    if (workflow) form.append("domain", workflow);

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
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" />
                Processing — OCR, extraction, and validation run in the background.
              </p>
            )}
            {mismatch && (
              <Alert variant="destructive">
                <AlertTriangle />
                <AlertTitle>Uploaded documents may not match this package type</AlertTitle>
                <AlertDescription>
                  You selected {workflow}, but the documents look like {detectedDomain}. Processing still runs under
                  {" "}{workflow} — if that&apos;s wrong, create a new package under the correct package type instead.
                </AlertDescription>
              </Alert>
            )}
            {isTerminal ? (
              <Button asChild>
                <Link href={`/packages/${packageId}`}>
                  Open package workspace
                  <ArrowRight data-icon="inline-end" />
                </Link>
              </Button>
            ) : (
              <Button disabled>
                <Loader2 className="animate-spin" data-icon="inline-start" />
                Waiting for processing to finish…
              </Button>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!workflow) {
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-4">
        <div>
          <h1 className="text-lg font-semibold">Choose a package type</h1>
          <p className="text-sm text-muted-foreground">
            ClaimFlow is a configurable document-review engine — each package type below is a reference
            configuration (document types, extraction schema, validation rules, policy corpus) of the same engine.
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {WORKFLOWS.map((w) => {
            const pack = domainPacks.data?.find((p) => p.key === w.key);
            return (
              <Card
                key={w.key}
                className="cursor-pointer transition-colors hover:border-primary"
                onClick={() => setWorkflow(w.key)}
              >
                <CardHeader>
                  <CardTitle className="text-base">{pack?.display_name ?? w.title}</CardTitle>
                  <CardDescription>{w.description}</CardDescription>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-1.5">
                  {w.chips.map((c) => (
                    <Badge key={c} variant="secondary">
                      {c}
                    </Badge>
                  ))}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold">{WORKFLOWS.find((w) => w.key === workflow)?.title}</h1>
        <p className="text-sm text-muted-foreground">
          Upload one or more documents that make up this package.{" "}
          <button className="underline" onClick={() => setWorkflow(null)}>
            Change package type
          </button>
        </p>
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
