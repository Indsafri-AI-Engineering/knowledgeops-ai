import { useEffect, useState, type FormEvent } from "react";
import {
  addJiraComment,
  createJiraIssue,
  getJiraIssueTypes,
  getJiraProjects,
  getJiraStatus,
  getJiraTransitions,
  searchJiraIssues,
  transitionJiraIssue,
  updateJiraIssue,
  type JiraIssue,
  type JiraIssueType,
  type JiraProject,
  type JiraStatus,
  type JiraTransition,
} from "../../api/jira";
import { ApiError } from "../../api/auth";
import type { AuthenticatedUser } from "../../types/auth";

type JiraPanelProps = {
  user: AuthenticatedUser;
};

function errorText(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback;
  return error.requestId
    ? `${error.message} Request ID: ${error.requestId}`
    : error.message;
}

export function JiraPanel({ user }: JiraPanelProps) {
  const canRead = user.capabilities.includes("jira:read");
  const canWrite = user.capabilities.includes("jira:approve");
  const [status, setStatus] = useState<JiraStatus | null>(null);
  const [projects, setProjects] = useState<JiraProject[]>([]);
  const [issueTypes, setIssueTypes] = useState<JiraIssueType[]>([]);
  const [projectKey, setProjectKey] = useState("");
  const [issueTypeId, setIssueTypeId] = useState("");
  const [query, setQuery] = useState("");
  const [issues, setIssues] = useState<JiraIssue[]>([]);
  const [selectedIssue, setSelectedIssue] = useState<JiraIssue | null>(null);
  const [transitions, setTransitions] = useState<JiraTransition[]>([]);
  const [newSummary, setNewSummary] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newPriorityName, setNewPriorityName] = useState("");
  const [summary, setSummary] = useState("");
  const [description, setDescription] = useState("");
  const [priorityName, setPriorityName] = useState("");
  const [comment, setComment] = useState("");
  const [transitionId, setTransitionId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getJiraStatus()
      .then((result) => {
        if (active) setStatus(result);
      })
      .catch((requestError: unknown) => {
        if (active) setError(errorText(requestError, "Jira status could not be loaded."));
      });
    if (canRead) {
      getJiraProjects()
        .then((result) => {
          if (!active) return;
          setProjects(result);
          setProjectKey((current) => current || result[0]?.key || "");
        })
        .catch((requestError: unknown) => {
          if (active) setError(errorText(requestError, "Jira projects could not be loaded."));
        });
    }
    return () => {
      active = false;
    };
  }, [canRead]);

  useEffect(() => {
    let active = true;
    if (canWrite && projectKey) {
      getJiraIssueTypes(projectKey)
        .then((result) => {
          if (!active) return;
          setIssueTypes(result);
          setIssueTypeId((current) =>
            result.some((item) => item.id === current) ? current : result[0]?.id ?? "",
          );
        })
        .catch((requestError: unknown) => {
          if (active) setError(errorText(requestError, "Issue types could not be loaded."));
        });
    }
    return () => {
      active = false;
    };
  }, [canWrite, projectKey]);

  async function search(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await searchJiraIssues(query, projectKey);
      setIssues(result.issues);
      setSelectedIssue(null);
      setTransitions([]);
      setMessage(`${result.issues.length} Jira issue${result.issues.length === 1 ? "" : "s"} found.`);
    } catch (requestError) {
      setError(errorText(requestError, "Jira search failed."));
    } finally {
      setBusy(false);
    }
  }

  async function createIssue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!window.confirm("Create this issue in the selected Jira project?")) return;
    const issueType = issueTypes.find((item) => item.id === issueTypeId);
    if (!issueType) {
      setError("The selected Jira project has no issue type available for creation.");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const created = await createJiraIssue({
        project_key: projectKey,
        issue_type_id: issueType.id,
        summary: newSummary,
        description: newDescription,
        priority_name: newPriorityName || null,
        confirmed: true,
      });
      setNewSummary("");
      setNewDescription("");
      setNewPriorityName("");
      setMessage(`Created ${created.key} in Jira.`);
      await search();
    } catch (requestError) {
      setError(errorText(requestError, "Jira could not create the issue."));
    } finally {
      setBusy(false);
    }
  }

  async function selectIssue(issue: JiraIssue) {
    setSelectedIssue(issue);
    setSummary(issue.summary);
    setDescription(issue.description);
    setPriorityName(issue.priority ?? "");
    setTransitions([]);
    if (!canWrite) return;
    try {
      setTransitions(await getJiraTransitions(issue.key));
    } catch (requestError) {
      setError(errorText(requestError, "Available Jira transitions could not be loaded."));
    }
  }

  async function saveIssue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedIssue || !window.confirm(`Save changes to ${selectedIssue.key}?`)) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await updateJiraIssue(selectedIssue.key, {
        summary,
        description,
        priority_name: priorityName || undefined,
        confirmed: true,
      });
      setMessage(`Updated ${selectedIssue.key}.`);
      await search();
    } catch (requestError) {
      setError(errorText(requestError, "Jira could not update the issue."));
    } finally {
      setBusy(false);
    }
  }

  async function submitComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedIssue || !window.confirm(`Add this comment to ${selectedIssue.key}?`)) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await addJiraComment(selectedIssue.key, comment);
      setComment("");
      setMessage(`Comment added to ${selectedIssue.key}.`);
    } catch (requestError) {
      setError(errorText(requestError, "Jira could not add the comment."));
    } finally {
      setBusy(false);
    }
  }

  async function submitTransition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedIssue || !transitionId) return;
    const selectedTransition = transitions.find((item) => item.id === transitionId);
    if (!window.confirm(`Move ${selectedIssue.key} to "${selectedTransition?.name}"?`)) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await transitionJiraIssue(selectedIssue.key, transitionId);
      setMessage(`${selectedIssue.key} transitioned to ${selectedTransition?.name}.`);
      setTransitionId("");
      await search();
    } catch (requestError) {
      setError(errorText(requestError, "Jira could not transition the issue."));
    } finally {
      setBusy(false);
    }
  }

  if (!canRead && !canWrite) return null;

  return (
    <section className="jira-workspace" aria-labelledby="jira-heading">
      <header className="jira-heading">
        <div>
          <p className="eyebrow">WORK MANAGEMENT</p>
          <h2 id="jira-heading">Jira issues</h2>
          <p>Search and manage issues in your connected Jira workspace.</p>
        </div>
        <span className={`connection-badge ${status?.configured ? "connected" : "disconnected"}`}>
          <span aria-hidden="true" />
          {status?.configured ? "Jira connected" : "Jira setup required"}
        </span>
      </header>

      {message && <p className="success-message" role="status">{message}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {status && !status.configured && (
        <div className="integration-notice">
          Add `JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN` to the backend
          environment, then restart the API. The token stays on the server.
        </div>
      )}
      {status?.base_url && (
        <p className="integration-endpoint">Connected workspace · {status.base_url}</p>
      )}

      <div className="jira-layout">
        <div className="jira-main-column">
          {canRead && (
            <section className="jira-card" aria-labelledby="jira-search-heading">
              <div className="section-title">
                <div>
                  <p className="eyebrow">ISSUE TRACKER</p>
                  <h3 id="jira-search-heading">Find an issue</h3>
                </div>
                <span className="record-count">{issues.length} results</span>
              </div>
              <form className="jira-search-form" onSubmit={(event) => void search(event)}>
                <label className="visually-hidden" htmlFor="jira-project">Project</label>
                <select
                  id="jira-project"
                  value={projectKey}
                  onChange={(event) => setProjectKey(event.target.value)}
                  disabled={!projects.length}
                >
                  {projects.length === 0 && <option value="">All projects</option>}
                  {projects.map((project) => (
                    <option key={project.id} value={project.key}>
                      {project.key} · {project.name}
                    </option>
                  ))}
                </select>
                <label className="visually-hidden" htmlFor="jira-query">Search Jira issues</label>
                <input
                  id="jira-query"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  maxLength={200}
                  placeholder="Search by summary or issue text"
                />
                <button className="button" type="submit" disabled={busy || !status?.configured}>
                  {busy ? "Searching…" : "Search"}
                </button>
              </form>
              {issues.length === 0 ? (
                <p className="empty-state">Search your Jira projects to see matching issues here.</p>
              ) : (
                <div className="jira-issue-list">
                  {issues.map((issue) => (
                    <button
                      className={`jira-issue-row ${selectedIssue?.key === issue.key ? "selected" : ""}`}
                      key={issue.key}
                      type="button"
                      onClick={() => void selectIssue(issue)}
                    >
                      <span className="issue-row-main">
                        <span className="issue-key">{issue.key}</span>
                        <strong>{issue.summary}</strong>
                      </span>
                      <span className="issue-row-meta">
                        <span className="issue-status">{issue.status ?? "Unresolved"}</span>
                        <span>{issue.priority ?? "No priority"}</span>
                        <span>{issue.assignee ?? "Unassigned"}</span>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </section>
          )}

          {canWrite && (
            <section className="jira-card" aria-labelledby="jira-create-heading">
              <div className="section-title">
                <div>
                  <p className="eyebrow">CREATE</p>
                  <h3 id="jira-create-heading">Create an issue</h3>
                </div>
              </div>
              <form className="jira-form-grid" onSubmit={(event) => void createIssue(event)}>
                <label htmlFor="jira-new-summary">Summary</label>
                <input
                  id="jira-new-summary"
                  value={newSummary}
                  onChange={(event) => setNewSummary(event.target.value)}
                  minLength={5}
                  maxLength={255}
                  required
                />
                <label htmlFor="jira-new-description">Description</label>
                <textarea
                  id="jira-new-description"
                  value={newDescription}
                  onChange={(event) => setNewDescription(event.target.value)}
                  maxLength={5000}
                  required
                  rows={4}
                />
                <label htmlFor="jira-issue-type">Issue type</label>
                <select
                  id="jira-issue-type"
                  value={issueTypeId}
                  onChange={(event) => setIssueTypeId(event.target.value)}
                  disabled={!issueTypes.length}
                  required
                >
                  {issueTypes.length === 0 ? (
                    <option value="">Select a Jira project first</option>
                  ) : (
                    issueTypes.map((issueType) => (
                      <option key={issueType.id} value={issueType.id}>{issueType.name}</option>
                    ))
                  )}
                </select>
                <label htmlFor="jira-new-priority">Priority</label>
                <select
                  id="jira-new-priority"
                  value={newPriorityName}
                  onChange={(event) => setNewPriorityName(event.target.value)}
                >
                  <option value="">Use Jira project default</option>
                  {["Highest", "High", "Medium", "Low", "Lowest"].map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
                <button className="button" type="submit" disabled={busy || !status?.configured}>
                  Create in Jira
                </button>
              </form>
            </section>
          )}
        </div>

        {canWrite && (
          <aside className="jira-card jira-detail-card" aria-labelledby="jira-detail-heading">
            <p className="eyebrow">ISSUE ACTIONS</p>
            <h3 id="jira-detail-heading">
              {selectedIssue ? selectedIssue.key : "Select an issue"}
            </h3>
            {!selectedIssue ? (
              <p className="empty-state">Choose an issue from search results to edit, comment, or transition it.</p>
            ) : (
              <div className="jira-detail-actions">
                <form className="jira-form-grid" onSubmit={(event) => void saveIssue(event)}>
                  <label htmlFor="jira-edit-summary">Summary</label>
                  <input
                    id="jira-edit-summary"
                    value={summary}
                    onChange={(event) => setSummary(event.target.value)}
                    minLength={5}
                    maxLength={255}
                    required
                  />
                  <label htmlFor="jira-edit-description">Description</label>
                  <textarea
                    id="jira-edit-description"
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    maxLength={5000}
                    rows={4}
                  />
                  <label htmlFor="jira-edit-priority">Priority</label>
                  <select
                    id="jira-edit-priority"
                    value={priorityName}
                    onChange={(event) => setPriorityName(event.target.value)}
                  >
                    <option value="">Keep current priority</option>
                    {["Highest", "High", "Medium", "Low", "Lowest"].map((item) => (
                      <option key={item} value={item}>{item}</option>
                    ))}
                  </select>
                  <button className="button button-secondary" type="submit" disabled={busy}>
                    Save issue changes
                  </button>
                </form>
                <form className="jira-form-grid" onSubmit={(event) => void submitComment(event)}>
                  <label htmlFor="jira-comment">Add a comment</label>
                  <textarea
                    id="jira-comment"
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                    minLength={1}
                    maxLength={5000}
                    rows={3}
                    required
                  />
                  <button className="button button-secondary" type="submit" disabled={busy}>
                    Add comment
                  </button>
                </form>
                {transitions.length > 0 && (
                  <form className="jira-form-grid" onSubmit={(event) => void submitTransition(event)}>
                    <label htmlFor="jira-transition">Change workflow status</label>
                    <select
                      id="jira-transition"
                      value={transitionId}
                      onChange={(event) => setTransitionId(event.target.value)}
                      required
                    >
                      <option value="">Choose a transition</option>
                      {transitions.map((transition) => (
                        <option key={transition.id} value={transition.id}>{transition.name}</option>
                      ))}
                    </select>
                    <button className="button button-secondary" type="submit" disabled={busy}>
                      Apply transition
                    </button>
                  </form>
                )}
              </div>
            )}
          </aside>
        )}
      </div>
    </section>
  );
}
