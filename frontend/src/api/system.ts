import { ApiError } from "./auth";
import { apiFetch } from "./http";

export type SystemComponent = {
  name: string;
  category: string;
  mode: "local" | "mock" | "disabled" | "external";
  description: string;
  external_connection: boolean;
};

export type SystemStatus = {
  environment: string;
  components: SystemComponent[];
  virustotal: {
    enabled: boolean;
    api_key_configured: boolean;
    connection_status: string;
    last_successful_check: string | null;
    last_check: string | null;
    last_error: string | null;
    privacy_policy: string;
    failure_policy: string;
  };
};

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

export async function getSystemStatus(): Promise<SystemStatus> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/system/status`);
  if (!response.ok) {
    throw new ApiError(`System status request failed (${response.status}).`, response.status);
  }
  return (await response.json()) as SystemStatus;
}
