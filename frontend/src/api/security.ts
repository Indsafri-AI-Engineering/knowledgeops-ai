import { ApiError } from "./auth";
import { apiFetch } from "./http";

export type SecurityAlertStatus =
  | "open"
  | "acknowledged"
  | "resolved"
  | "false_positive";

export type SecurityAlert = {
  alert_id: string;
  alert_type:
    | "document_security"
    | "threat_indicator"
    | "authentication_anomaly"
    | "authorization_anomaly";
  severity: "info" | "low" | "medium" | "high";
  title: string;
  summary: string;
  status: SecurityAlertStatus;
  created_at: string;
  updated_at: string;
  actor_id: string | null;
  artifact_sha256: string | null;
  indicators: Array<{
    rule_id: string;
    severity: "info" | "low" | "medium" | "high";
    description: string;
    evidence_redacted: boolean;
  }>;
  virustotal_findings: Array<{
    provider: "VirusTotal";
    threat_category: "Malicious URL" | "Suspicious URL" | "Unknown URL reputation";
    severity: "info" | "low" | "medium" | "high";
    detection_ratio: string | null;
    scan_status: string;
    redacted_url: string;
    document_event_reference: string;
    timestamp: string;
  }>;
  detector_version: string;
  notification_status: "not_configured" | "sent" | "failed";
  response_workflow_status:
    | "not_requested"
    | "not_configured"
    | "sent"
    | "failed";
  resolution_note: string | null;
  reviewed_by: string | null;
};

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

export async function listSecurityAlerts(): Promise<SecurityAlert[]> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/security/alerts`);
  if (!response.ok) {
    throw new ApiError(`Security alert request failed (${response.status}).`, response.status);
  }
  return (await response.json()) as SecurityAlert[];
}

export async function reviewSecurityAlert(
  alertId: string,
  status: "acknowledged" | "resolved" | "false_positive",
): Promise<SecurityAlert> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/v1/security/alerts/${encodeURIComponent(alertId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    },
  );
  if (!response.ok) {
    throw new ApiError(`Security alert update failed (${response.status}).`, response.status);
  }
  return (await response.json()) as SecurityAlert;
}

export async function requestSecurityResponseWorkflow(
  alertId: string,
): Promise<SecurityAlert> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/v1/security/alerts/${encodeURIComponent(alertId)}/response-workflow`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmed: true }),
    },
  );
  if (!response.ok) {
    throw new ApiError(
      `Approved security response request failed (${response.status}).`,
      response.status,
    );
  }
  return (await response.json()) as SecurityAlert;
}
