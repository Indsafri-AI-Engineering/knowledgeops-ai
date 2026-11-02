import { useEffect, useState } from "react";
import { ApiError, getCurrentUser } from "../api/auth";
import { ChatPanel } from "../features/chat/ChatPanel";
import { SystemStatusPanel } from "../features/system-status/SystemStatusPanel";
import { KnowledgeDocumentsPanel } from "../features/knowledge/KnowledgeDocumentsPanel";
import { JiraPanel } from "../features/jira/JiraPanel";
import { ThreatScanPanel } from "../features/threat-scans/ThreatScanPanel";
import type { VirusTotalDocumentSummary } from "../api/knowledge";
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
  const [chatSessionKey, setChatSessionKey] = useState(0);
  const [lastDocumentUrlScan, setLastDocumentUrlScan] =
    useState<VirusTotalDocumentSummary | null>(null);

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
    setChatSessionKey((key) => key + 1);
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
              <span className="nav-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none">
                  <path d="M5 5.75A2.75 2.75 0 0 1 7.75 3h8.5A2.75 2.75 0 0 1 19 5.75v8.5A2.75 2.75 0 0 1 16.25 17H12l-4.5 4v-4h-.25A2.75 2.75 0 0 1 5 14.25v-8.5Z" />
                  <path d="M9 8h6M9 12h4" />
                </svg>
              </span>
              Knowledge assistant
            </button>
            {(user.capabilities.includes("jira:read")
              || user.capabilities.includes("jira:approve")) && (
              <button
                className={activeView === "jira" ? "nav-item active" : "nav-item"}
                onClick={() => setActiveView("jira")}
              >
                <span className="nav-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none">
                    <path d="M5 4.5h14v15H5zM8 8h8M8 12h8M8 16h4" />
                  </svg>
                </span>
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
                <span className="nav-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none">
                    <path d="M12 3 19 6v5c0 4.5-2.8 7.8-7 10-4.2-2.2-7-5.5-7-10V6l7-3Z" />
                    <path d="m9 12 2 2 4-4" />
                  </svg>
                </span>
                Threat analysis
              </button>
            )}
            <button
              className={activeView === "system" ? "nav-item active" : "nav-item"}
              onClick={() => setActiveView("system")}
            >
              <span className="nav-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none">
                  <path d="M4 13h4l2.2-6 3.6 10 2.2-5H20" />
                </svg>
              </span>
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
                  <h1>Welcome back, {user.display_name.split(" ")[0]}</h1>
                  <p>Your team’s knowledge, ready when you need it.</p>
                  <p className="demo-corpus-notice" role="note">
                    Demo workspace <span aria-hidden="true">·</span> Built-in Northstar Works content is fictional.
                  </p>
                </section>
                <ChatPanel key={chatSessionKey} />
                {user.capabilities.includes("knowledge:manage") && (
                  <KnowledgeDocumentsPanel onUrlScan={setLastDocumentUrlScan} />
                )}
              </>
            )}
            {activeView === "jira" && <JiraPanel user={user} />}
            {activeView === "threat-scans" && (
              <ThreatScanPanel
                canScan={user.capabilities.includes("threat_scans:scan")}
                lastDocumentUrlScan={lastDocumentUrlScan}
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
