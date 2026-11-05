import { ApiError } from "./auth";
import { apiFetch } from "./http";

export type SourceCitation = {
  title: string;
  source: string;
  source_path: string;
  section: string;
  document_id: string;
  owner: string | null;
  version: string | null;
  effective_date: string | null;
  next_review: string | null;
  environment: string | null;
};

export type FAQSuggestion = {
  faq_id: string;
  question: string;
};

export type RetrievalMode = "vector" | "keyword" | "hybrid";

export type SalesforceLoginGuide = {
  connector: string;
  status: "mock";
  execution: "local_langchain";
  symptom: "sign_in_page" | "password_rejected" | "mfa_problem" | "account_locked" | "browser_error";
  steps: string[];
  escalation: string;
  sources: SourceCitation[];
};

export type ThreatIndicator = {
  rule_id: string;
  severity: "info" | "low" | "medium" | "high" | "critical";
  description: string;
  evidence: string;
};

export type ThreatScanResult = {
  scan_id: string;
  security_alert_id: string | null;
  artifact_type: "url" | "email" | "document";
  artifact_sha256: string;
  submitted_reference: string | null;
  verdict: "suspicious" | "no-known-indicator";
  severity: "info" | "low" | "medium" | "high" | "critical";
  indicators: ThreatIndicator[];
  extracted_urls: string[];
  detector_version: string;
  scanned_at: string;
  limitations: string[];
};

export type ChatResponse = {
  question: string;
  answer: string;
  intent: string;
  route_category: "knowledge" | "workflow" | "analytical" | "unsupported";
  route_component:
    | "knowledge_base"
    | "hr_knowledge"
    | "it_knowledge"
    | "recruitment"
    | "jira"
    | "threat_analysis"
    | "knowledge_analytics"
    | "unsupported";
  workflow_status: "available" | "planned";
  retrieval_mode: RetrievalMode;
  sources: SourceCitation[];
  needs_clarification: boolean;
  action_proposal: null;
};

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");

export async function askQuestion(
  question: string,
  retrievalMode: RetrievalMode,
): Promise<ChatResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      retrieval_mode: retrievalMode,
    }),
  });
  if (!response.ok) {
    throw new ApiError(
      `Question request failed (${response.status}).`,
      response.status,
      response.headers.get("X-Request-ID"),
    );
  }
  return (await response.json()) as ChatResponse;
}

export async function getFaqSuggestions(): Promise<FAQSuggestion[]> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/faqs/suggestions`);
  if (!response.ok) {
    throw new ApiError(`FAQ request failed (${response.status}).`, response.status);
  }
  return (await response.json()) as FAQSuggestion[];
}

export async function getSalesforceLoginGuide(
  symptom: SalesforceLoginGuide["symptom"],
): Promise<SalesforceLoginGuide> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/v1/connectors/it/salesforce/login-guide`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symptom }),
    },
  );
  if (!response.ok) {
    throw new ApiError(`Salesforce guide request failed (${response.status}).`, response.status);
  }
  return (await response.json()) as SalesforceLoginGuide;
}

export async function scanThreatArtifact(
  kind: "urls" | "emails" | "documents",
  payload: Record<string, string>,
): Promise<ThreatScanResult> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/threat-scans/${kind}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new ApiError(`Threat scan request failed (${response.status}).`, response.status);
  }
  return (await response.json()) as ThreatScanResult;
}
