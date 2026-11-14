import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import {
  api, type Assessment, type AssessmentListItem, type AuditEntry, type AuditVerify, type Comparison, type DocumentDetail, type DocumentSummary,
  type Health, type History, type Intake, type Overview, type PolicyDetail, type PolicySummary, type QueueItem, type RequestDetail,
  type RequestSummary, type VendorDetail, type VendorSummary,
} from "./api";
import { getIdentity, subscribeIdentity } from "./identity";

export const useIdentity = () => useSyncExternalStore(subscribeIdentity, getIdentity);

export const useHealth = () => useQuery({ queryKey: ["health"], queryFn: () => api.get<Health>("/health/ready"), refetchInterval: 60_000, retry: false });
export const useRequests = (status?: string) =>
  useQuery({ queryKey: ["requests", status ?? "all"], queryFn: () => api.get<RequestSummary[]>("/requests", { status, limit: 500 }) });
export const useRequest = (id: string) => useQuery({ queryKey: ["request", id], queryFn: () => api.get<RequestDetail>(`/requests/${id}`) });
export const useIntake = (id: string) => useQuery({ queryKey: ["intake", id], queryFn: () => api.get<Intake>(`/requests/${id}/intake`) });
export const useComparison = (id: string) => useQuery({ queryKey: ["comparison", id], queryFn: () => api.get<Comparison>(`/requests/${id}/quote-comparison`) });
export const useHistory = (id: string) => useQuery({ queryKey: ["history", id], queryFn: () => api.get<History>(`/requests/${id}/history`) });
export const useAssessments = (id: string) => useQuery({ queryKey: ["assessments", id], queryFn: () => api.get<AssessmentListItem[]>(`/requests/${id}/assessments`) });
export const useAssessment = (id: string | undefined) =>
  useQuery({ queryKey: ["assessment", id], queryFn: () => api.get<Assessment>(`/assessments/${id}`), enabled: !!id });
export const useQueue = (status = "submitted,assessed") => {
  const { role } = useIdentity();
  return useQuery({ queryKey: ["queue", status, role], queryFn: () => api.get<QueueItem[]>("/review/queue", { status }), retry: false });
};
export const useOverview = (params: { since?: string; until?: string; exclude_mock?: boolean }) => {
  const { role } = useIdentity();
  return useQuery({ queryKey: ["overview", params, role], queryFn: () => api.get<Overview>("/analytics/overview", params), retry: false });
};
export const useDocuments = () => useQuery({ queryKey: ["documents"], queryFn: () => api.get<DocumentSummary[]>("/documents", { limit: 500 }) });
export const useDocument = (id: string | null) => useQuery({ queryKey: ["document", id], queryFn: () => api.get<DocumentDetail>(`/documents/${id}`), enabled: !!id });
export const useVendors = () => useQuery({ queryKey: ["vendors"], queryFn: () => api.get<VendorSummary[]>("/vendors") });
export const useVendor = (id: string | null) => useQuery({ queryKey: ["vendor", id], queryFn: () => api.get<VendorDetail>(`/vendors/${id}`), enabled: !!id });
export const usePolicies = () => useQuery({ queryKey: ["policies"], queryFn: () => api.get<PolicySummary[]>("/policies") });
export const usePolicy = (id: string | null) => useQuery({ queryKey: ["policy", id], queryFn: () => api.get<PolicyDetail>(`/policies/${id}`), enabled: !!id });
export const useApprovedSuppliers = () =>
  useQuery({ queryKey: ["approved-suppliers"], queryFn: () => api.get<{ configured: boolean; names: string[] }>("/settings/approved-suppliers") });
export const useAudit = (filters: Record<string, string | undefined>) => {
  const { role } = useIdentity();
  return useQuery({ queryKey: ["audit", filters, role], queryFn: () => api.get<{ entries: AuditEntry[]; next_before_id: number | null }>("/audit", { ...filters, limit: 50 }), retry: false });
};
export const verifyAudit = () => api.get<AuditVerify>("/audit/verify");

/** Refresh everything that depends on one request after a mutation. */
export function useInvalidateRequest() {
  const qc = useQueryClient();
  return (id: string) => {
    ["request", "intake", "comparison", "history", "assessments", "assessment"].forEach((k) => qc.invalidateQueries({ queryKey: [k, id] }));
    ["requests", "queue", "overview", "assessment"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  };
}
