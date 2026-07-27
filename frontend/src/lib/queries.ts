import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, API_BASE_URL } from "@/lib/api";
import type { components } from "@/lib/api-types";

type Schemas = components["schemas"];

export const qk = {
  dashboard: ["dashboard"] as const,
  packages: (params: Record<string, unknown>) => ["packages", params] as const,
  reviewQueue: (params: Record<string, unknown>) => ["reviews", params] as const,
  package: (id: string) => ["package", id] as const,
  packageStatus: (id: string) => ["package-status", id] as const,
  documents: (id: string) => ["documents", id] as const,
  review: (id: string) => ["review", id] as const,
  policyEvidence: (id: string) => ["policy-evidence", id] as const,
  audit: (id: string) => ["audit", id] as const,
  export: (id: string) => ["export", id] as const,
};

export type PackageListParams = {
  page?: number;
  page_size?: number;
  status?: string;
  domain?: string;
  decision?: string;
  confidence_min?: number;
  confidence_max?: number;
  validation_rule?: string;
  date_from?: string;
  date_to?: string;
  search?: string;
  sort?: string;
};

export function useDashboardSummary() {
  return useQuery({
    queryKey: qk.dashboard,
    queryFn: async () => {
      const { data, error } = await api.GET("/dashboard/summary");
      if (error) throw error;
      return data as Schemas["DashboardSummaryResponse"];
    },
    refetchInterval: 30_000,
  });
}

export function usePackageList(params: PackageListParams, enabled = true) {
  return useQuery({
    queryKey: qk.packages(params),
    queryFn: async () => {
      const { data, error } = await api.GET("/packages", { params: { query: params } });
      if (error) throw error;
      return data;
    },
    enabled,
  });
}

export function useReviewQueue(params: PackageListParams, enabled = true) {
  return useQuery({
    queryKey: qk.reviewQueue(params),
    queryFn: async () => {
      const { data, error } = await api.GET("/reviews/queue", { params: { query: params } });
      if (error) throw error;
      return data;
    },
    enabled,
  });
}

export function usePackage(packageId: string, opts?: { poll?: boolean }) {
  return useQuery({
    queryKey: qk.package(packageId),
    queryFn: async () => {
      const { data, error } = await api.GET("/packages/{package_id}", {
        params: { path: { package_id: packageId } },
      });
      if (error) throw error;
      return data;
    },
    refetchInterval: (query) => {
      if (!opts?.poll) return false;
      const status = query.state.data?.status;
      return status === "queued" || status === "processing" ? 2_000 : false;
    },
  });
}

export function useDocuments(packageId: string) {
  return useQuery({
    queryKey: qk.documents(packageId),
    queryFn: async () => {
      const { data, error } = await api.GET("/packages/{package_id}/documents", {
        params: { path: { package_id: packageId } },
      });
      if (error) throw error;
      return data;
    },
  });
}

export function usePackageReview(packageId: string) {
  return useQuery({
    queryKey: qk.review(packageId),
    queryFn: async () => {
      const { data, error } = await api.GET("/packages/{package_id}/review", {
        params: { path: { package_id: packageId } },
      });
      if (error) throw error;
      return data;
    },
  });
}

export function usePolicyEvidence(packageId: string) {
  return useQuery({
    queryKey: qk.policyEvidence(packageId),
    queryFn: async () => {
      const { data, error } = await api.GET("/packages/{package_id}/policy-evidence", {
        params: { path: { package_id: packageId } },
      });
      if (error) throw error;
      return data;
    },
  });
}

export function useAuditTrail(packageId: string) {
  return useQuery({
    queryKey: qk.audit(packageId),
    queryFn: async () => {
      const { data, error } = await api.GET("/packages/{package_id}/audit", {
        params: { path: { package_id: packageId } },
      });
      if (error) throw error;
      return data;
    },
  });
}

export function useExport(packageId: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.export(packageId),
    queryFn: async () => {
      const { data, error } = await api.GET("/packages/{package_id}/export", {
        params: { path: { package_id: packageId } },
      });
      if (error) throw error;
      return data;
    },
    enabled,
  });
}

function invalidatePackage(queryClient: ReturnType<typeof useQueryClient>, packageId: string) {
  queryClient.invalidateQueries({ queryKey: qk.package(packageId) });
  queryClient.invalidateQueries({ queryKey: qk.review(packageId) });
  queryClient.invalidateQueries({ queryKey: qk.audit(packageId) });
  queryClient.invalidateQueries({ queryKey: qk.documents(packageId) });
  queryClient.invalidateQueries({ queryKey: qk.policyEvidence(packageId) });
  queryClient.invalidateQueries({ queryKey: qk.dashboard });
}

export function useCreatePackage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (files: File[]) => {
      const form = new FormData();
      files.forEach((f) => form.append("files", f));
      const res = await fetch(`${API_BASE_URL}/packages`, { method: "POST", body: form });
      const body = await res.json();
      if (!res.ok) throw body;
      return body as Schemas["PackageCreateResponse"];
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["packages"] }),
  });
}

export function useReprocessPackage(packageId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/packages/{package_id}/process", {
        params: { path: { package_id: packageId } },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => invalidatePackage(queryClient, packageId),
  });
}

export function useReclassifyDocument(packageId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      documentId: string;
      docType: Schemas["DocumentType"];
      reviewer?: string;
    }) => {
      const { data, error } = await api.POST("/packages/{package_id}/documents/{document_id}/reclassify", {
        params: { path: { package_id: packageId, document_id: input.documentId } },
        body: { doc_type: input.docType, reviewer: input.reviewer ?? "reviewer" },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.documents(packageId) }),
  });
}

export function useSubmitFieldReview(packageId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      fieldId: number;
      action: "approve" | "edit" | "reject" | "add";
      correctedValue?: unknown;
      reviewer?: string;
      note?: string;
    }) => {
      const { data, error } = await api.POST("/packages/{package_id}/fields/{field_id}/review", {
        params: { path: { package_id: packageId, field_id: input.fieldId } },
        body: {
          action: input.action,
          corrected_value: input.correctedValue,
          reviewer: input.reviewer ?? "reviewer",
          note: input.note,
        },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.review(packageId) }),
  });
}

export function useRerunValidation(packageId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (correctedFields: Record<string, unknown>) => {
      const { data, error } = await api.POST("/packages/{package_id}/validation/re-run", {
        params: { path: { package_id: packageId } },
        body: { corrected_fields: correctedFields },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => invalidatePackage(queryClient, packageId),
  });
}

export function useRecordDecision(packageId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { decision: "approved" | "flagged" | "escalated"; reviewReasons?: string[] }) => {
      const { data, error } = await api.POST("/packages/{package_id}/decision", {
        params: { path: { package_id: packageId } },
        body: { decision: input.decision, review_reasons: input.reviewReasons ?? [] },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => invalidatePackage(queryClient, packageId),
  });
}

export function useDeletePackage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (packageId: string) => {
      const { data, error } = await api.DELETE("/packages/{package_id}", {
        params: { path: { package_id: packageId } },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["packages"] }),
  });
}
