import type { AuthenticatedUser } from "../types/auth";
import { apiFetch } from "./http";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");
const API_PREFIX = `${API_BASE_URL}/api/v1`;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await apiFetch(`${API_PREFIX}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    throw new ApiError(
      `Request failed (${response.status}).`,
      response.status,
      response.headers.get("X-Request-ID"),
    );
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function getCurrentUser(): Promise<AuthenticatedUser | null> {
  try {
    return await request<AuthenticatedUser>("/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null;
    }
    throw error;
  }
}
