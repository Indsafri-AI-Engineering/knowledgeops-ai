import { ApiError } from "./auth";
import { apiFetch } from "./http";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");
const JIRA_API = `${API_BASE_URL}/api/v1/jira`;

export type JiraStatus = {
  configured: boolean;
  base_url: string | null;
};

export type JiraProject = {
  id: string;
  key: string;
  name: string;
};

export type JiraIssueType = {
  id: string;
  name: string;
};

export type JiraIssue = {
  id: string;
  key: string;
  summary: string;
  description: string;
  status: string | null;
  priority: string | null;
  project_key: string | null;
  assignee: string | null;
  issue_type: string | null;
  updated: string;
};

export type JiraTransition = {
  id: string;
  name: string;
};

async function jiraRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(`${JIRA_API}${path}`, init);
  if (!response.ok) {
    let detail = `Jira request failed (${response.status}).`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Keep the status-based message if the server response is not JSON.
    }
    throw new ApiError(
      detail,
      response.status,
      response.headers.get("X-Request-ID"),
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function jsonRequest(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export function getJiraStatus(): Promise<JiraStatus> {
  return jiraRequest("/status");
}

export function getJiraProjects(): Promise<JiraProject[]> {
  return jiraRequest("/projects");
}

export function getJiraIssueTypes(projectKey: string): Promise<JiraIssueType[]> {
  return jiraRequest(`/projects/${encodeURIComponent(projectKey)}/issue-types`);
}

export function searchJiraIssues(
  query: string,
  projectKey: string,
): Promise<{ issues: JiraIssue[] }> {
  const params = new URLSearchParams();
  if (query.trim()) params.set("query", query.trim());
  if (projectKey) params.set("project_key", projectKey);
  return jiraRequest(`/issues?${params.toString()}`);
}

export function createJiraIssue(input: {
  project_key: string;
  issue_type_id: string;
  summary: string;
  description: string;
  priority_name: string | null;
  confirmed: true;
}): Promise<{ id: string; key: string; url: string }> {
  return jiraRequest("/issues", jsonRequest("POST", input));
}

export function updateJiraIssue(
  issueKey: string,
  input: {
    summary?: string;
    description?: string;
    priority_name?: string;
    confirmed: true;
  },
): Promise<void> {
  return jiraRequest(
    `/issues/${encodeURIComponent(issueKey)}`,
    jsonRequest("PATCH", input),
  );
}

export function addJiraComment(
  issueKey: string,
  body: string,
): Promise<{ id: string }> {
  return jiraRequest(
    `/issues/${encodeURIComponent(issueKey)}/comments`,
    jsonRequest("POST", { body, confirmed: true }),
  );
}

export function getJiraTransitions(issueKey: string): Promise<JiraTransition[]> {
  return jiraRequest(`/issues/${encodeURIComponent(issueKey)}/transitions`);
}

export function transitionJiraIssue(
  issueKey: string,
  transitionId: string,
): Promise<void> {
  return jiraRequest(
    `/issues/${encodeURIComponent(issueKey)}/transitions`,
    jsonRequest("POST", { transition_id: transitionId, confirmed: true }),
  );
}
