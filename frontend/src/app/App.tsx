import { useEffect, useState } from "react";
import { ApiError, getCurrentUser } from "../api/auth";
import { ChatPanel } from "../features/chat/ChatPanel";
import { SystemStatusPanel } from "../features/system-status/SystemStatusPanel";
import { KnowledgeDocumentsPanel } from "../features/knowledge/KnowledgeDocumentsPanel";
import { JiraPanel } from "../features/jira/JiraPanel";
import { ThreatScanPanel } from "../features/threat-scans/ThreatScanPanel";
import type { AuthenticatedUser } from "../types/auth";
import {
  completeOidcCallback,
  getOidcAuthority,
  getOidcUser,
  isOidcMode,
  startOidcLogin,
  startOidcLogout,
} from "../api/oidc";

const oidcMode = isOidcMode();
type WorkspaceView = "knowledge" | "jira" | "threat-scans" | "system";

export function App() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [activeView, setActiveView] = useState<WorkspaceView>("knowledge");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const initialize = async () => {
      if (oidcMode) {
        await completeOidcCallback();
        if (!(await getOidcUser())) return;
        const currentUser = await getCurrentUser();
        if (active) setUser(currentUser);
        return;
      }
    };
    initialize()
      .catch((initializationError: unknown) => {
        if (active) {
          if (initializationError instanceof ApiError) {
            const requestReference = initializationError.requestId
              ? ` Request ID: ${initializationError.requestId}.`
              : "";
            setError(
              `The API rejected the signed-in session (HTTP ${initializationError.status}).${requestReference}`,
            );
          } else if (initializationError instanceof Error) {
            setError(
              `Sign-in could not be completed: ${initializationError.message}. Check the identity-provider callback and token exchange.`,
            );
          } else {
            setError("Sign-in could not be completed. Check the identity-provider callback and token exchange.");
          }
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  async function handleLogin() {
    setBusy(true);
    setError(null);
    try {
      await startOidcLogin();
    } catch {
      const authority = getOidcAuthority() ?? "the configured identity provider";
      setError(
        `Could not start sign-in. Verify ${authority} is running and that the web client is configured for this application.`,
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    setBusy(true);
    setError(null);
    try {
      await startOidcLogout();
    } catch {
      setError("Sign-out failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <main className="loading-shell"><p role="status">Loading KnowledgeOps AI…</p></main>;
  }

  return (
    user ? (
      <div className="application-shell">
        <aside className="sidebar">
          <a className="brand" href="/" aria-label="KnowledgeOps home">
            <span className="brand-mark">K</span>
            <span>
              <strong>KnowledgeOps</strong>
              <small>INTELLIGENCE WORKSPACE</small>
            </span>
          </a>
          <p className="nav-label">WORKSPACE</p>
          <nav className="primary-nav" aria-label="Workspace navigation">
            <button
              className={activeView === "knowledge" ? "nav-item active" : "nav-item"}
              onClick={() => setActiveView("knowledge")}
            >
              <span className="nav-icon" aria-hidden="true">⌕</span>
              Knowledge assistant
            </button>
            {(user.capabilities.includes("jira:read")
              || user.capabilities.includes("jira:approve")) && (
              <button
                className={activeView === "jira" ? "nav-item active" : "nav-item"}
                onClick={() => setActiveView("jira")}
              >
                <span className="nav-icon" aria-hidden="true">▤</span>
                Jira workspace
              </button>
            )}
            {(user.capabilities.includes("threat_scans:scan")
              || user.capabilities.includes("security_alerts:read")
              || user.capabilities.includes("security_alerts:manage")
              || user.capabilities.includes("system:admin")) && (
              <button
                className={activeView === "threat-scans" ? "nav-item active" : "nav-item"}
                onClick={() => setActiveView("threat-scans")}
              >
                <span className="nav-icon" aria-hidden="true">⌁</span>
                Threat analysis
              </button>
            )}
            <button
              className={activeView === "system" ? "nav-item active" : "nav-item"}
              onClick={() => setActiveView("system")}
            >
              <span className="nav-icon" aria-hidden="true">◉</span>
              System status
            </button>
          </nav>
          <div className="sidebar-footer">
            <span className="environment-indicator"><span /> Authenticated session</span>
            <p>Access is governed by your organization’s identity and permissions.</p>
          </div>
        </aside>

        <div className="workspace">
          <header className="topbar">
            <div className="breadcrumbs">
              <span>Workspace</span>
              <span aria-hidden="true">/</span>
              <strong>
                {activeView === "knowledge"
                  ? "Knowledge assistant"
                  : activeView === "jira"
                    ? "Jira"
                    : activeView === "threat-scans"
                      ? "Threat analysis"
                      : "System status"}
              </strong>
            </div>
            <div className="user-menu">
              <div className="avatar" aria-hidden="true">
                {user.display_name.trim().charAt(0).toUpperCase()}
              </div>
              <div className="user-identity">
                <strong>{user.display_name}</strong>
                <span>{user.role.replaceAll("_", " ")}</span>
              </div>
              <button
                className="button button-secondary signout-button"
                onClick={() => void handleLogout()}
                disabled={busy}
              >
                Sign out
              </button>
            </div>
          </header>

          <main className="workspace-content">
            {error && <p className="error" role="alert">{error}</p>}
            {activeView === "knowledge" && (
              <>
                <section className="page-intro">
                  <p className="eyebrow">KNOWLEDGE WORKSPACE</p>
                  <h1>Good day, {user.display_name.split(" ")[0]}</h1>
                  <p>Ask questions across the documents and knowledge sources you’re authorized to access.</p>
                  <p className="demo-corpus-notice" role="note">
                    FICTIONAL DEMO: Built-in Northstar Works knowledge is synthetic and is not real company policy.
                  </p>
                </section>
                <ChatPanel key={user.user_id} userId={user.user_id} />
                {user.capabilities.includes("knowledge:manage") && <KnowledgeDocumentsPanel />}
              </>
            )}
            {activeView === "jira" && <JiraPanel user={user} />}
            {activeView === "threat-scans" && (
              <ThreatScanPanel
                canScan={user.capabilities.includes("threat_scans:scan")}
                canManageAlerts={
                  user.capabilities.includes("security_alerts:manage")
                  || user.capabilities.includes("threat_scans:scan")
                  || user.capabilities.includes("system:admin")
                }
              />
            )}
            {activeView === "system" && <SystemStatusPanel />}
          </main>
        </div>
      </div>
    ) : (
      <main className="signin-shell">
        <div className="signin-brand">
          <span className="brand-mark">K</span>
          <strong>KnowledgeOps</strong>
        </div>
        <section className="signin-card" aria-labelledby="signin-heading">
          <p className="eyebrow">SECURE WORKSPACE</p>
          <h1 id="signin-heading">Sign in to your workspace</h1>
          <p>Use your organization account to access knowledge and connected tools.</p>
          {error && <p className="error" role="alert">{error}</p>}
          <button
            className="button signin-button"
            onClick={() => void handleLogin()}
            disabled={busy || !oidcMode}
          >
            {busy ? "Connecting…" : "Continue with organization SSO"}
          </button>
          {!oidcMode && (
            <p className="error" role="alert">
              Configure VITE_AUTH_MODE=oidc to enable sign-in.
            </p>
          )}
          <p className="signin-security">Your access is protected by your organization’s identity provider.</p>
        </section>
      </main>
    )
  );
}
