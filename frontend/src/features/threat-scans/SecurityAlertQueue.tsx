import { useEffect, useState } from "react";
import {
  listSecurityAlerts,
  requestSecurityResponseWorkflow,
  reviewSecurityAlert,
  type SecurityAlert,
} from "../../api/security";

type Props = {
  refreshKey: number;
  canManage: boolean;
};

export function SecurityAlertQueue({ refreshKey, canManage }: Props) {
  const [alerts, setAlerts] = useState<SecurityAlert[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyAlert, setBusyAlert] = useState<string | null>(null);

  async function refresh() {
    try {
      setAlerts(await listSecurityAlerts());
      setError(null);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Security alerts could not be loaded.",
      );
    }
  }

  useEffect(() => {
    void refresh();
  }, [refreshKey]);

  async function update(alert: SecurityAlert, nextStatus: "acknowledged" | "resolved" | "false_positive") {
    setBusyAlert(alert.alert_id);
    try {
      await reviewSecurityAlert(alert.alert_id, nextStatus);
      await refresh();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Security alert could not be updated.",
      );
    } finally {
      setBusyAlert(null);
    }
  }

  async function dispatchApprovedWorkflow(alert: SecurityAlert) {
    if (!window.confirm(
      "Send this acknowledged alert to the configured n8n response workflow? The app will send only alert metadata and rule identifiers.",
    )) return;
    setBusyAlert(alert.alert_id);
    try {
      await requestSecurityResponseWorkflow(alert.alert_id);
      await refresh();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "The approved response workflow could not be requested.",
      );
    } finally {
      setBusyAlert(null);
    }
  }

  return (
    <section className="panel" aria-labelledby="security-alerts-heading">
      <div className="panel-heading-row">
        <div>
          <p className="eyebrow">SECURITY OPERATIONS</p>
          <h2 id="security-alerts-heading">Alert review queue</h2>
        </div>
        <button className="button button-secondary" type="button" onClick={() => void refresh()}>
          Refresh
        </button>
      </div>
      <p>Alert evidence is redacted. Review status changes are recorded in the audit log.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {alerts.length === 0 && !error ? (
        <p>No security alerts have been recorded.</p>
      ) : (
        <ul className="system-component-list security-alert-list">
          {alerts.map((alert) => (
            <li key={alert.alert_id}>
              <div>
                <strong>{alert.title}</strong>
                <span className={`status-badge status-${alert.severity}`}>
                  {alert.severity}
                </span>
                <span className="status-badge status-local">{alert.status.replace("_", " ")}</span>
              </div>
              <p>{alert.summary}</p>
              <p>
                {alert.alert_type.replaceAll("_", " ")} ·{" "}
                {new Date(alert.created_at).toLocaleString()} · notification:{" "}
                {alert.notification_status.replace("_", " ")}
              </p>
              <p>
                Actor: {alert.actor_id ?? "unattributed"} · Fingerprint:{" "}
                {alert.artifact_sha256
                  ? <code>{alert.artifact_sha256}</code>
                  : "not applicable"}
              </p>
              <p>Approved response workflow: {alert.response_workflow_status.replace("_", " ")}</p>
              <ul>
                {alert.indicators.map((indicator) => (
                  <li key={indicator.rule_id}>
                    <strong>{indicator.rule_id}</strong>: {indicator.description}
                    {indicator.evidence_redacted && <span> (matched evidence withheld)</span>}
                  </li>
                ))}
              </ul>
              {canManage && alert.status === "open" && (
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={busyAlert === alert.alert_id}
                  onClick={() => void update(alert, "acknowledged")}
                >
                  Acknowledge
                </button>
              )}
              {canManage && (alert.status === "open" || alert.status === "acknowledged") && (
                <>
                  <button
                    className="button button-secondary"
                    type="button"
                    disabled={busyAlert === alert.alert_id}
                    onClick={() => void update(alert, "resolved")}
                  >
                    Resolve
                  </button>
                  <button
                    className="button button-secondary"
                    type="button"
                    disabled={busyAlert === alert.alert_id}
                    onClick={() => void update(alert, "false_positive")}
                  >
                    Mark false positive
                  </button>
                </>
              )}
              {canManage
                && alert.status === "acknowledged"
                && alert.response_workflow_status !== "sent" && (
                  <button
                    className="button button-secondary"
                    type="button"
                    disabled={busyAlert === alert.alert_id}
                    onClick={() => void dispatchApprovedWorkflow(alert)}
                  >
                    Request approved response
                  </button>
                )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
