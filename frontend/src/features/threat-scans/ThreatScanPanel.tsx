import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../../api/auth";
import { scanThreatArtifact, type ThreatScanResult } from "../../api/chat";
import type { VirusTotalDocumentSummary } from "../../api/knowledge";
import { getSystemStatus, type SystemStatus } from "../../api/system";
import { SecurityAlertQueue } from "./SecurityAlertQueue";

type ArtifactKind = "url" | "email" | "document";

type Props = {
  canScan: boolean;
  canManageAlerts: boolean;
  lastDocumentUrlScan: VirusTotalDocumentSummary | null;
};

export function ThreatScanPanel({
  canScan,
  canManageAlerts,
  lastDocumentUrlScan,
}: Props) {
  const [kind, setKind] = useState<ArtifactKind>("url");
  const [url, setUrl] = useState("");
  const [emailText, setEmailText] = useState("");
  const [filename, setFilename] = useState("sample.txt");
  const [documentText, setDocumentText] = useState("");
  const [result, setResult] = useState<ThreatScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [alertsVersion, setAlertsVersion] = useState(0);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [systemStatusError, setSystemStatusError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void getSystemStatus()
      .then((status) => {
        if (active) {
          setSystemStatus(status);
          setSystemStatusError(null);
        }
      })
      .catch(() => {
        if (active) {
          setSystemStatus(null);
          setSystemStatusError("VirusTotal provider status could not be loaded.");
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function submitScan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);
    setBusy(true);
    try {
      const scan = kind === "url"
        ? await scanThreatArtifact("urls", { url })
        : kind === "email"
          ? await scanThreatArtifact("emails", { email_text: emailText })
          : await scanThreatArtifact("documents", { filename, text: documentText });
      setResult(scan);
      if (scan.security_alert_id) setAlertsVersion((value) => value + 1);
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 422) {
        setError("The submitted input did not pass validation. Check its format and size.");
      } else if (requestError instanceof ApiError && requestError.status === 403) {
        setError("Your account is not authorized to run threat scans.");
      } else {
        setError("The scan failed. Check the API connection and try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
    <SecurityAlertQueue refreshKey={alertsVersion} canManage={canManageAlerts} />
    {canScan && <section className="panel threat-panel" aria-labelledby="threat-heading">
      <p className="eyebrow">THREAT ANALYSIS · NO URL FETCH OR FILE EXECUTION</p>
      <h2 id="threat-heading">Threat indicator scan</h2>
      {systemStatus && (
        <p role="status">
          VirusTotal: {systemStatus.virustotal.enabled ? "enabled" : "disabled"} ·{" "}
          {systemStatus.virustotal.connection_status.replaceAll("_", " ")} ·{" "}
          API key {systemStatus.virustotal.api_key_configured ? "configured" : "not configured"}
          {systemStatus.virustotal.last_successful_check
            ? ` · last successful check ${new Date(
              systemStatus.virustotal.last_successful_check,
            ).toLocaleString()}`
            : ""}
        </p>
      )}
      {systemStatusError && <p className="error" role="alert">{systemStatusError}</p>}
      {lastDocumentUrlScan && (
        <article className="answer" aria-live="polite">
          <h3>Latest ingested document URL analysis</h3>
          <p>
            {lastDocumentUrlScan.urls_detected} unique URL(s) · malicious{" "}
            {lastDocumentUrlScan.malicious_count} · suspicious{" "}
            {lastDocumentUrlScan.suspicious_count} · clean{" "}
            {lastDocumentUrlScan.clean_count} · unknown{" "}
            {lastDocumentUrlScan.unknown_count} · unavailable{" "}
            {lastDocumentUrlScan.provider_unavailable_count} · rate limited{" "}
            {lastDocumentUrlScan.rate_limited_count}
          </p>
          {lastDocumentUrlScan.results.map((item, index) => (
            <p key={`${item.redacted_url}-${index}`}>
              <strong>{item.status.replaceAll("_", " ")}</strong> ·{" "}
              {item.redacted_url}
              {item.detection_ratio ? ` · detections ${item.detection_ratio}` : ""}
            </p>
          ))}
          <p>
            Ingestion {lastDocumentUrlScan.ingestion_blocked
              ? "was blocked before indexing."
              : "was not blocked."}
          </p>
        </article>
      )}
      <p>
        Document uploads use local rules and, when enabled and privacy-eligible,
        VirusTotal URL reports. A missing report or provider error is unknown,
        never a clean result. Submitted artifact text is not stored.
      </p>
      <form className="question-form" onSubmit={(event) => void submitScan(event)}>
        <label htmlFor="artifact-kind">Artifact type</label>
        <select
          id="artifact-kind"
          value={kind}
          onChange={(event) => {
            const value = event.currentTarget.value;
            if (value === "url" || value === "email" || value === "document") setKind(value);
            setResult(null);
            setError(null);
          }}
        >
          <option value="url">URL</option>
          <option value="email">Email text</option>
          <option value="document">Plain-text document</option>
        </select>

        {kind === "url" ? (
          <>
            <label htmlFor="scan-url">URL</label>
            <input
              id="scan-url"
              type="url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              maxLength={2048}
              placeholder="https://example.com"
              required
            />
          </>
        ) : kind === "email" ? (
          <>
            <label htmlFor="scan-email">Email headers and body</label>
            <textarea
              id="scan-email"
              value={emailText}
              onChange={(event) => setEmailText(event.target.value)}
              maxLength={50000}
              rows={7}
              placeholder={"From: Example Sender <sender@example.com>\nSubject: Sample message\n\nEmail body"}
              required
            />
          </>
        ) : (
          <>
            <label htmlFor="scan-filename">Filename (.txt, .md, or .eml)</label>
            <input
              id="scan-filename"
              value={filename}
              onChange={(event) => setFilename(event.target.value)}
              maxLength={255}
              required
            />
            <label htmlFor="scan-document">Document text</label>
            <textarea
              id="scan-document"
              value={documentText}
              onChange={(event) => setDocumentText(event.target.value)}
              maxLength={100000}
              rows={7}
              placeholder="Paste harmless fictional sample text to inspect"
              required
            />
          </>
        )}
        <button className="button" type="submit" disabled={busy}>
          {busy ? "Scanning locally…" : "Scan artifact"}
        </button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {result && (
        <article className="answer" aria-live="polite">
          <h3>Scan result</h3>
          <p><strong>Verdict:</strong> {result.verdict} · <strong>Severity:</strong> {result.severity}</p>
          <p><strong>Scan ID:</strong> <code>{result.scan_id}</code></p>
          <p><strong>Detector:</strong> {result.detector_version} · {new Date(result.scanned_at).toLocaleString()}</p>
          <p><strong>Artifact fingerprint:</strong> <code>{result.artifact_sha256}</code></p>
          {result.security_alert_id && (
            <p>
              <strong>Security alert:</strong>{" "}
              <code>{result.security_alert_id}</code> was added to the review queue.
            </p>
          )}
          {result.indicators.length > 0 ? (
            <>
              <h3>Evidence</h3>
              <ul className="source-list">
                {result.indicators.map((indicator) => (
                  <li key={indicator.rule_id}>
                    <strong>{indicator.rule_id} · {indicator.severity}</strong>
                    <span>{indicator.description}</span>
                    <code>Matched: {indicator.evidence}</code>
                  </li>
                ))}
              </ul>
            </>
          ) : <p>No indicators were found by the local rules.</p>}
          {result.extracted_urls.length > 0 && (
            <>
              <h3>Extracted URLs (not fetched)</h3>
              <ul>{result.extracted_urls.map((item) => <li key={item}><code>{item}</code></li>)}</ul>
            </>
          )}
          <h3>Limitations</h3>
          <ul>{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        </article>
      )}
    </section>}
    </>
  );
}
