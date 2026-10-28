import { ApiError } from "./auth";
import { apiFetch } from "./http";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

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

export async function listKnowledgeDocuments(): Promise<KnowledgeDocument[]> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/knowledge/documents`);
  if (!response.ok) {
    throw new ApiError(`Document list request failed (${response.status}).`, response.status);
  }
  return (await response.json()) as KnowledgeDocument[];
}

export async function ingestKnowledgeDocument(form: FormData): Promise<{
  document: KnowledgeDocument;
  status: "stored_locally";
  security_status: "clear" | "alert_created";
  security_alert_id: string | null;
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
    );
  }
  return (await response.json()) as {
    document: KnowledgeDocument;
    status: "stored_locally";
    security_status: "clear" | "alert_created";
    security_alert_id: string | null;
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
