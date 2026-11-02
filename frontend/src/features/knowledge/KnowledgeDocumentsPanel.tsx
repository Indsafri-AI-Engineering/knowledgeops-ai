import {
  useEffect,
  useRef,
  useState,
  type DragEvent,
  type FormEvent,
} from "react";
import {
  deleteKnowledgeDocument,
  ingestKnowledgeDocument,
  listKnowledgeDocuments,
  type KnowledgeDocument,
  type VirusTotalDocumentSummary,
  type VirusTotalURLResult,
} from "../../api/knowledge";
import { ApiError } from "../../api/auth";
import { getSystemStatus, type SystemStatus } from "../../api/system";

type KnowledgeScope = "general" | "hr" | "it" | "recruitment";
type BatchUploadResult = {
  filename: string;
  size: number;
  status: "stored" | "blocked" | "duplicate" | "failed";
  detail: string;
  scan: VirusTotalDocumentSummary | null;
  securityAlertId: string | null;
};

const MAX_BATCH_DOCUMENTS = 50;
const SUPPORTED_TYPES = ".pdf,.docx,.txt,.md,.html,.xlsx,.pptx";

type Props = {
  onUrlScan: (summary: VirusTotalDocumentSummary | null) => void;
};

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isVirusTotalChecked(result: VirusTotalURLResult): boolean {
  return result.analysis_status === "completed";
}

function resultTone(status: VirusTotalURLResult["status"]): string {
  if (status === "malicious") return "danger";
  if (status === "suspicious") return "warning";
  if (status === "clean") return "clean";
  return "unknown";
}

function resultLabel(status: VirusTotalURLResult["status"]): string {
  return status.replaceAll("_", " ");
}

export function KnowledgeDocumentsPanel({ onUrlScan }: Props) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [scope, setScope] = useState<KnowledgeScope>("general");
  const [files, setFiles] = useState<File[]>([]);
  const [uploadResults, setUploadResults] = useState<BatchUploadResult[]>([]);
  const [uploadProgress, setUploadProgress] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [systemStatusError, setSystemStatusError] = useState<string | null>(null);

  function selectFiles(selected: File[]) {
    setFiles(selected);
    setUploadResults([]);
    setNotice(null);
    setError(
      selected.length > MAX_BATCH_DOCUMENTS
        ? `Select no more than ${MAX_BATCH_DOCUMENTS} documents per batch.`
        : null,
    );
  }

  async function refreshDocuments() {
    setDocuments(await listKnowledgeDocuments());
  }

  useEffect(() => {
    let active = true;
    listKnowledgeDocuments()
      .then((items) => {
        if (active) setDocuments(items);
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : "Documents could not be loaded.");
        }
      });
    getSystemStatus()
      .then((status) => {
        if (active) {
          setSystemStatus(status);
          setSystemStatusError(null);
        }
      })
      .catch(() => {
        if (active) setSystemStatusError("Scanner connection status could not be loaded.");
      });
    return () => {
      active = false;
    };
  }, []);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (files.length === 0) {
      setError("Choose at least one supported document to ingest.");
      return;
    }
    if (files.length > MAX_BATCH_DOCUMENTS) {
      setError(`Select no more than ${MAX_BATCH_DOCUMENTS} documents per batch.`);
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    onUrlScan(null);
    setUploadResults([]);
    const results: BatchUploadResult[] = [];

    for (const [index, file] of files.entries()) {
      setUploadProgress(`Processing ${index + 1} of ${files.length}: ${file.name}`);
      const form = new FormData();
      form.set("file", file);
      form.set("access_scope", scope);
      try {
        const result = await ingestKnowledgeDocument(form);
        onUrlScan(result.url_scan);
        results.push({
          filename: file.name,
          size: file.size,
          status: "stored",
          detail: `${result.document.chunk_count} searchable chunks stored as "${result.document.title}".`,
          scan: result.url_scan,
          securityAlertId: result.security_alert_id,
        });
      } catch (cause) {
        if (cause instanceof ApiError) {
          const body = cause.responseBody;
          const response = (
            typeof body === "object" && body !== null
              ? body
              : {}
          ) as {
            url_scan?: VirusTotalDocumentSummary | null;
            ingestion_blocked?: boolean;
            security_alert_id?: string | null;
          };
          const duplicate = cause.status === 409;
          const blocked = response.ingestion_blocked === true;
          results.push({
            filename: file.name,
            size: file.size,
            status: duplicate ? "duplicate" : blocked ? "blocked" : "failed",
            detail: duplicate
              ? "Duplicate content; not ingested."
              : cause.message,
            scan: response.url_scan ?? null,
            securityAlertId: response.security_alert_id ?? null,
          });
          if (response.url_scan) onUrlScan(response.url_scan);
        } else {
          results.push({
            filename: file.name,
            size: file.size,
            status: "failed",
            detail: "Document ingestion failed.",
            scan: null,
            securityAlertId: null,
          });
        }
      }
      setUploadResults([...results]);
    }

    setUploadResults(results);
    setFiles([]);
    if (fileInput.current) fileInput.current.value = "";
    setUploadProgress(null);
    const refreshErrors: string[] = [];
    try {
      await refreshDocuments();
    } catch {
      refreshErrors.push("The stored-document list could not be refreshed.");
    }
    try {
      setSystemStatus(await getSystemStatus());
      setSystemStatusError(null);
    } catch {
      setSystemStatusError("Scanner connection status could not be refreshed.");
    }
    const stored = results.filter((result) => result.status === "stored").length;
    const duplicates = results.filter((result) => result.status === "duplicate").length;
    const blocked = results.filter((result) => result.status === "blocked").length;
    const failed = results.filter((result) => result.status === "failed").length;
    setNotice(
      `Batch complete: ${stored} stored, ${blocked} blocked, ${duplicates} duplicate(s) skipped, ${failed} failed.`,
    );
    if (refreshErrors.length) setError(refreshErrors.join(" "));
    setBusy(false);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    selectFiles(Array.from(event.dataTransfer.files));
  }

  async function handleDelete(document: KnowledgeDocument) {
    if (!window.confirm(`Delete ${document.title} and its searchable chunks?`)) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await deleteKnowledgeDocument(document.document_id);
      await refreshDocuments();
      setNotice(`${document.title} and its searchable chunks were deleted.`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Document deletion failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="knowledge-documents-heading">
      <p className="eyebrow">KNOWLEDGE INGESTION</p>
      <h2 id="knowledge-documents-heading">Knowledge documents</h2>
      <p>
        Select up to 50 PDF, DOCX, TXT, Markdown, HTML, XLSX, or PPTX files.
        Files are processed one at a time in the selected access scope. Each
        document title defaults to its filename without the extension. The
        backend inspects content and eligible URLs before indexing. Original
        files are not retained. Upload progress is indeterminate because the
        backend does not expose per-stage progress.
      </p>
      <div className="scanner-provider" aria-live="polite">
        <span className="scanner-provider-icon" aria-hidden="true">盾</span>
        <div>
          <strong>VirusTotal URL reputation</strong>
          {systemStatus ? (
            <p>
              {systemStatus.virustotal.enabled
                ? systemStatus.virustotal.connection_status.replaceAll("_", " ")
                : "disabled"}
              {" · "}
              {systemStatus.virustotal.api_key_configured
                ? "API key configured"
                : "API key not configured"}
            </p>
          ) : (
            <p>{systemStatusError ?? "Checking provider status…"}</p>
          )}
        </div>
        <span
          className={`scanner-status-dot ${
            systemStatus?.virustotal.connection_status === "connected"
              ? "is-connected"
              : systemStatus?.virustotal.enabled &&
                  systemStatus.virustotal.api_key_configured
                ? "is-pending"
                : "is-unavailable"
          }`}
          aria-hidden="true"
        />
      </div>
      <form className="question-form" onSubmit={(event) => void handleUpload(event)}>
        <label htmlFor="knowledge-scope">Access scope</label>
        <select
          id="knowledge-scope"
          value={scope}
          onChange={(event) => setScope(event.target.value as KnowledgeScope)}
        >
          <option value="general">General</option>
          <option value="hr">HR</option>
          <option value="it">IT</option>
          <option value="recruitment">Recruitment</option>
        </select>
        <div
          className={`scanner-dropzone${isDragging ? " is-dragging" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
              setIsDragging(false);
            }
          }}
          onDrop={handleDrop}
        >
          <input
            ref={fileInput}
            id="knowledge-document"
            className="scanner-file-input"
            type="file"
            accept={SUPPORTED_TYPES}
            multiple
            onChange={(event) => selectFiles(Array.from(event.target.files ?? []))}
          />
          <span className="scanner-upload-icon" aria-hidden="true">↑</span>
          <strong>Drop documents here to scan</strong>
          <span>or select files from your device</span>
          <button
            className="button button-secondary"
            type="button"
            onClick={() => fileInput.current?.click()}
            disabled={busy}
          >
            Browse files
          </button>
          <small>
            PDF · DOCX · TXT · MD · HTML · XLSX · PPTX
            <br />
            Up to {MAX_BATCH_DOCUMENTS} files · 10 MiB each
          </small>
        </div>
        <div className="scanner-queue" aria-live="polite">
          <div className="scanner-queue-heading">
            <strong>Selected files</strong>
            <span>{files.length} / {MAX_BATCH_DOCUMENTS}</span>
          </div>
          {files.length ? (
            <ul>
              {files.map((file, index) => (
                <li key={`${file.name}-${file.lastModified}-${index}`}>
                  <span className="scanner-file-name">{file.name}</span>
                  <span>{formatFileSize(file.size)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p>No files selected.</p>
          )}
        </div>
        <button className="button" type="submit" disabled={busy || files.length === 0}>
          {busy ? "Scanning and ingesting…" : "Scan and ingest selected"}
        </button>
      </form>
      {busy && (
        <section className="scanner-progress" role="status" aria-live="polite">
          <div className="scanner-progress-heading">
            <span className="scanner-pulse" aria-hidden="true">◈</span>
            <div>
              <strong>Security analysis in progress</strong>
              <p>{uploadProgress}</p>
            </div>
            <span className="scanner-indeterminate-label">Processing</span>
          </div>
          <div
            className="scanner-progress-track is-indeterminate"
            role="progressbar"
            aria-label="Document security analysis progress"
            aria-valuetext="Progress is indeterminate; waiting for backend result"
          >
            <span />
          </div>
          <p>
            The backend is validating the document, inspecting extracted content
            and eligible URLs, applying security rules, and indexing only if
            permitted. Detailed stage progress is not available.
          </p>
        </section>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="success-message" role="status">{notice}</p>}
      {uploadResults.length > 0 && (
        <section className="scanner-results" aria-label="Security analysis results">
          <div className="scanner-results-heading">
            <div>
              <p className="eyebrow">ANALYSIS REPORT</p>
              <h3>Document security results</h3>
            </div>
            <span className="scanner-report-count">
              {uploadResults.length} file{uploadResults.length === 1 ? "" : "s"}
            </span>
          </div>
          {uploadResults.map((result, index) => (
            <article
              className={`scanner-report scanner-report-${result.status}`}
              key={`${result.filename}-${index}`}
            >
              <div className="scanner-report-header">
                <div className="scanner-report-file">
                  <span className="scanner-report-file-icon" aria-hidden="true">▤</span>
                  <div>
                    <strong>{result.filename}</strong>
                    <span>{formatFileSize(result.size)}</span>
                  </div>
                </div>
                <span className={`scanner-verdict scanner-verdict-${result.status}`}>
                  {result.status === "stored" ? "Processed" : result.status}
                </span>
              </div>
              <p className="scanner-report-detail">{result.detail}</p>
              {result.scan ? (
                <SecurityAnalysis scan={result.scan} ingestionStatus={result.status} />
              ) : (
                <div className="scanner-no-scan">
                  <span className="scanner-verdict scanner-verdict-unknown">
                    Scan unavailable
                  </span>
                  <span>No VirusTotal URL scan result was returned for this file.</span>
                </div>
              )}
              {result.securityAlertId && (
                <p className="scanner-alert-reference">
                  Security alert created · <code>{result.securityAlertId}</code>
                </p>
              )}
            </article>
          ))}
        </section>
      )}
      <h3>Stored documents</h3>
      {documents.length === 0 ? (
        <p>No documents have been ingested yet.</p>
      ) : (
        <ul className="system-component-list">
          {documents.map((document) => (
            <li key={document.document_id}>
              <div>
                <strong>{document.title}</strong>
                <span className="status-badge status-local">{document.access_scope}</span>
              </div>
              <p>{document.filename} · {document.document_type} · {document.chunk_count} chunks</p>
              <button
                className="button button-secondary"
                type="button"
                onClick={() => void handleDelete(document)}
                disabled={busy}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SecurityAnalysis({
  scan,
  ingestionStatus,
}: {
  scan: VirusTotalDocumentSummary;
  ingestionStatus: BatchUploadResult["status"];
}) {
  const checked = scan.results.filter(isVirusTotalChecked).length;
  const inconclusive = scan.results.filter(
    (result) => !isVirusTotalChecked(result) &&
      result.status !== "malicious" &&
      result.status !== "suspicious" &&
      result.status !== "clean",
  ).length;
  const undetectedEngines = scan.results.reduce(
    (total, result) => total + (result.undetected ?? 0),
    0,
  );
  const noDetectionURLs = scan.results.filter(
    (result) => result.status === "clean",
  ).length;
  const maliciousResults = scan.results.filter((result) => result.status === "malicious");
  const providerFailed =
    scan.provider_unavailable_count > 0 ||
    scan.rate_limited_count > 0 ||
    scan.authentication_failure_count > 0 ||
    inconclusive > 0;
  const suspiciousResults = scan.results.filter(
    (result) => result.status === "suspicious",
  );
  const providerState = scan.enabled
    ? scan.provider_status.replaceAll("_", " ")
    : "disabled";
  const ingestionLabel = ingestionStatus === "blocked"
    ? "Blocked before indexing"
    : ingestionStatus === "stored"
      ? "Backend stored this document"
      : ingestionStatus === "duplicate"
        ? "Duplicate; not ingested"
        : "Not stored";

  return (
    <div className="scanner-analysis">
      {maliciousResults.length > 0 ? (
        <div className="scanner-threat-warning" role="alert">
          <strong>Malicious URL verdict detected</strong>
          <span>
            {ingestionStatus === "blocked"
              ? "The backend blocked this document before indexing."
              : "The backend returned a malicious verdict; review the reported ingestion outcome."}
          </span>
        </div>
      ) : (
        <div className={`scanner-overall scanner-overall-${
          providerFailed ? "unknown" : suspiciousResults.length ? "warning" : "clean"
        }`}>
          <strong>
            {providerFailed
              ? "URL analysis incomplete"
              : suspiciousResults.length > 0
                ? "Suspicious URL verdict detected"
              : scan.urls_detected === 0
                ? "No URLs discovered"
                : "No malicious verdict detected"}
          </strong>
          <span>
            {providerFailed
              ? "Some URLs were not analyzed or had inconclusive results. This is not a clean verdict."
              : suspiciousResults.length > 0
                ? "Review the suspicious URL findings and apply your organization’s security process."
              : scan.urls_detected === 0
                ? "No URL reputation lookups were needed."
                : "This result covers URL reputation only, not file malware scanning."}
          </span>
        </div>
      )}
      <div className="scanner-metrics">
        <Metric label="URLs discovered" value={scan.urls_detected} />
        <Metric label="Analyses completed" value={checked} />
        <Metric label="Malicious" value={scan.malicious_count} tone="danger" />
        <Metric label="Suspicious" value={scan.suspicious_count} tone="warning" />
        <Metric label="No-detection URLs" value={noDetectionURLs} tone="clean" />
        <Metric label="Undetected engines" value={undetectedEngines} />
        <Metric label="Inconclusive / unavailable" value={inconclusive} />
      </div>
      <div className="scanner-ingestion-state">
        <span className={`scanner-status-dot ${ingestionStatus === "stored" ? "is-connected" : "is-unavailable"}`} />
        <span>{ingestionLabel}</span>
        <span className="scanner-provider-state">
          VirusTotal: {providerState}
        </span>
      </div>
      {maliciousResults.length > 0 && scan.ingestion_blocked && (
        <p className="scanner-policy-note">
          The backend confirms this document was blocked before indexing.
        </p>
      )}
      <div className="scanner-table-wrap">
        <table className="scanner-table">
          <thead>
            <tr>
              <th scope="col">URL / host</th>
              <th scope="col">Provider</th>
              <th scope="col">Result</th>
              <th scope="col">Detections</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {scan.results.length === 0 ? (
              <tr>
                <td colSpan={5} className="scanner-empty-table">
                  No URLs were extracted from this document.
                </td>
              </tr>
            ) : scan.results.map((result, index) => (
              <tr key={`${result.redacted_url}-${index}`}>
                <td className="scanner-url-cell">{result.redacted_url}</td>
                <td>
                  {["disabled", "privacy_filtered", "not_configured"].includes(result.status)
                    ? "Not queried"
                    : "VirusTotal"}
                </td>
                <td>
                  <span className={`scanner-verdict scanner-verdict-${resultTone(result.status)}`}>
                    {resultLabel(result.status)}
                  </span>
                </td>
                <td>{result.detection_ratio ?? "—"}</td>
                <td>{isVirusTotalChecked(result) ? "Analysis completed" : result.reason?.replaceAll("_", " ") ?? "Inconclusive"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "danger" | "warning" | "clean";
}) {
  return (
    <div className={`scanner-metric${tone ? ` scanner-metric-${tone}` : ""}`}>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}
