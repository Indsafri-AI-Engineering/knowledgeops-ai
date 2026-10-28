import { useEffect, useState } from "react";
import { getSystemStatus, type SystemStatus } from "../../api/system";

export function SystemStatusPanel() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getSystemStatus()
      .then((result) => {
        if (active) setStatus(result);
      })
      .catch(() => {
        if (active) setError("System component status could not be loaded.");
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <section className="panel" aria-labelledby="system-status-heading">
      <p className="eyebrow">ENVIRONMENT</p>
      <h2 id="system-status-heading">System components</h2>
      {error && <p className="error" role="alert">{error}</p>}
      {!status && !error && <p role="status">Loading component status…</p>}
      {status && (
        <>
          <p>
            {status.components.some((component) => component.external_connection)
              ? "One or more external AI providers are configured; review data handling before use."
              : "No external AI provider is currently selected."}
          </p>
          <ul className="system-component-list">
            {status.components.map((component) => (
              <li key={component.name}>
                <div>
                  <strong>{component.name}</strong>
                  <span className={`status-badge status-${component.mode}`}>
                    {component.mode}
                  </span>
                </div>
                <p>{component.description}</p>
                <span className="eyebrow">
                  External provider selected: {component.external_connection ? "yes" : "no"}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
