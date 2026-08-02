import createClient from "openapi-fetch";
import type { paths } from "@/lib/api-types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8010";

export const api = createClient<paths>({ baseUrl: API_BASE_URL });

export type ApiError = {
  code: string;
  message: string;
  details: unknown;
};

/** Every ClaimFlow error response is {error: {code, message, details}} — see src/claimflow/schemas/errors.py */
export function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "error" in error) {
    const body = (error as { error: ApiError }).error;
    return body?.message ?? "Request failed";
  }
  return "Could not reach the ClaimFlow API";
}

/** Fetches the export JSON and saves it as a file — opening the raw endpoint in a
 * new tab just displays JSON in the browser, which isn't useful to a reviewer. */
export async function downloadPackageExport(packageId: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/packages/${packageId}/export`);
  if (!res.ok) throw new Error("Export failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `package-${packageId}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

/** Multi-sheet Excel export (Claim Summary / Service Lines / Validation Results /
 * Source Evidence / Audit Trail) — see api/main.py's export_package_excel. */
export async function downloadPackageExportExcel(packageId: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/packages/${packageId}/export.xlsx`);
  if (!res.ok) throw new Error("Export failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `package-${packageId}.xlsx`;
  link.click();
  URL.revokeObjectURL(url);
}

/** Batch export — one workbook covering every package matching the given filters
 * (same shape as the packages list query), each sheet prefixed with a Package
 * column. See api/main.py's export_packages_batch_excel. */
export async function downloadPackagesBatchExcel(
  filters: Record<string, string | undefined>
): Promise<void> {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) qs.set(key, value);
  }
  const res = await fetch(`${API_BASE_URL}/packages/export.xlsx?${qs.toString()}`);
  if (!res.ok) throw new Error("Export failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "packages_export.xlsx";
  link.click();
  URL.revokeObjectURL(url);
}
