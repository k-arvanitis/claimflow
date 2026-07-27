import { API_BASE_URL } from "@/lib/api";

/** GET /packages/{package_id}/documents/{document_id}/pages/{page} — PNG render, optional bbox highlight. */
export function pageImageUrl(
  packageId: string,
  documentId: string,
  page: number,
  bbox?: [number, number, number, number]
) {
  const url = `${API_BASE_URL}/packages/${packageId}/documents/${documentId}/pages/${page}`;
  return bbox ? `${url}?bbox=${bbox.join(",")}` : url;
}
