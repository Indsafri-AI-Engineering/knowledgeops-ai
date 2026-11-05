import { ApiError } from "./auth";
import { apiFetch } from "./http";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");

export type KnowledgeDocument = {
  document_id: string;
  title: string;
  filename: string;
  source: string;
  document_type: string;
  sha256: string;
  access_scope: string;
  uploaded_at: string;
  owner: string | null;
  version: string | null;
  chunk_count: number;
};

export type VirusTotalURLResult = {
  status:
    | "malicious"
    | "suspicious"
    | "clean"
    | "unknown"
    | "provider_unavailable"
    | "rate_limited"
    | "authentication_failure"
    | "not_configured"
    | "disabled"
    | "privacy_filtered";
  redacted_url: string;
  malicious: number | null;
  suspicious: number | null;
  harmless: number | null;
  undetected: number | null;
  detection_ratio: string | null;
  analysis_status: string;
  last_analysis_at: string | null;
  checked_at: string;
  reason: string | null;
};

export type VirusTotalDocumentSummary = {
  enabled: boolean;
  provider_status: string;
  urls_detected: number;
  malicious_count: number;
  suspicious_count: number;
  clean_count: number;
  unknown_count: number;
  provider_unavailable_count: number;
  rate_limited_count: number;
  authentication_failure_count: number;
  ingestion_blocked: boolean;
  results: VirusTotalURLResult[];
};

export async function listKnowledgeDocuments(): Promise<KnowledgeDocument[]> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/knowledge/documents`);
  if (!response.ok) {
    throw new ApiError(`Document list request failed (${response.status}).`, response.status);
  }
  return (await response.json()) as KnowledgeDocument[];
}

export async function ingestKnowledgeDocument(form: FormData): Promise<{
  document: KnowledgeDocument;
  status: "stored";
  security_status: "clear" | "alert_created";
  security_alert_id: string | null;
  url_scan: VirusTotalDocumentSummary;
  ingestion_blocked: boolean;
}> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/knowledge/documents`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    const payload = (await response.json()) as { detail?: string };
    throw new ApiError(
      payload.detail ?? `Document upload failed (${response.status}).`,
      response.status,
      response.headers.get("X-Request-ID"),
      payload,
    );
  }
  return (await response.json()) as {
    document: KnowledgeDocument;
    status: "stored";
    security_status: "clear" | "alert_created";
    security_alert_id: string | null;
    url_scan: VirusTotalDocumentSummary;
    ingestion_blocked: boolean;
  };
}

export async function deleteKnowledgeDocument(documentId: string): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/v1/knowledge/documents/${encodeURIComponent(documentId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    throw new ApiError(`Document deletion failed (${response.status}).`, response.status);
  }
}
