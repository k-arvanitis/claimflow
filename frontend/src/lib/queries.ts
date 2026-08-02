import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, API_BASE_URL } from "@/lib/api";
import type { components } from "@/lib/api-types";

type Schemas = components["schemas"];

export const qk = {
  dashboard: ["dashboard"] as const,
  packages: (params: Record<string, unknown>) => ["packages", params] as const,
  package: (id: string) => ["package", id] as const,
  packageStatus: (id: string) => ["package-status", id] as const,
  documents: (id: string) => ["documents", id] as const,
  review: (id: string) => ["review", id] as const,
  policyEvidence: (id: string) => ["policy-evidence", id] as const,
  audit: (id: string) => ["audit", id] as const,
  fieldEvidence: (packageId: string, fieldId: number) => ["field-evidence", packageId, fieldId] as const,
  export: (id: string) => ["export", id] as const,
  domainPacks: ["domain-packs"] as const,
  domainPack: (key: string) => ["domain-pack", key] as const,
  llmCredentials: ["llm-credentials"] as const,
  policies: ["policies"] as const,
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
  client_key?: string;
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

export function useFieldEvidence(packageId: string, fieldId: number | null) {
  return useQuery({
    queryKey: qk.fieldEvidence(packageId, fieldId ?? -1),
    queryFn: async () => {
      const { data, error } = await api.GET("/packages/{package_id}/fields/{field_id}/evidence", {
        params: { path: { package_id: packageId, field_id: fieldId as number } },
      });
      if (error) throw error;
      return data as Schemas["FieldEvidenceResponse"];
    },
    enabled: fieldId != null,
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

export function useDomainPacks() {
  return useQuery({
    queryKey: qk.domainPacks,
    queryFn: async () => {
      const { data, error } = await api.GET("/domain-packs");
      if (error) throw error;
      return data;
    },
    staleTime: 5 * 60_000,
  });
}

export function useDomainPack(key: string | null) {
  return useQuery({
    queryKey: qk.domainPack(key ?? ""),
    queryFn: async () => {
      const { data, error } = await api.GET("/domain-packs/{key}", {
        params: { path: { key: key! } },
      });
      if (error) throw error;
      return data;
    },
    enabled: !!key,
    staleTime: 5 * 60_000,
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

export function invalidatePackage(queryClient: ReturnType<typeof useQueryClient>, packageId: string) {
  queryClient.invalidateQueries({ queryKey: ["packages"] });
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
    mutationFn: async (input: {
      decision: "ready_for_processing" | "needs_review" | "blocked_or_incomplete";
      reviewReasons?: string[];
    }) => {
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

export function useLLMCredentials() {
  return useQuery({
    queryKey: qk.llmCredentials,
    queryFn: async () => {
      const { data, error } = await api.GET("/llm-credentials");
      if (error) throw error;
      return data;
    },
  });
}

export function useSetLLMCredentials() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { provider: string; api_key: string | null; model: string | null }) => {
      const { data, error } = await api.POST("/llm-credentials", { body: input });
      if (error) throw error;
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.llmCredentials }),
  });
}

export function useDeleteLLMCredentials() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error } = await api.DELETE("/llm-credentials");
      if (error) throw error;
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.llmCredentials }),
  });
}

export function usePolicies() {
  return useQuery({
    queryKey: qk.policies,
    queryFn: async () => {
      const { data, error } = await api.GET("/policies");
      if (error) throw error;
      return data;
    },
  });
}

export function useUploadPolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { file: File; domain: string; authority: string }) => {
      const form = new FormData();
      form.append("file", input.file);
      form.append("domain", input.domain);
      form.append("authority", input.authority);
      const res = await fetch(`${API_BASE_URL}/policies`, { method: "POST", body: form });
      const body = await res.json();
      if (!res.ok) throw body;
      return body as Schemas["PolicyIndexStatus"];
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.policies }),
  });
}

export function useDeletePolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (filename: string) => {
      const { data, error } = await api.DELETE("/policies/{filename}", {
        params: { path: { filename } },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.policies }),
  });
}
