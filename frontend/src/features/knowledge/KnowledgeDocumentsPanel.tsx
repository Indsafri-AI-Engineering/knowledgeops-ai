import { useEffect, useState, type FormEvent } from "react";
import {
  deleteKnowledgeDocument,
  ingestKnowledgeDocument,
  listKnowledgeDocuments,
  type KnowledgeDocument,
} from "../../api/knowledge";
import { ApiError } from "../../api/auth";

type KnowledgeScope = "general" | "hr" | "it" | "recruitment";

export function KnowledgeDocumentsPanel() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [title, setTitle] = useState("");
  const [scope, setScope] = useState<KnowledgeScope>("general");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

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
    return () => {
      active = false;
    };
  }, []);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    if (!file) {
      setError("Choose a supported document to ingest.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    const form = new FormData();
    form.set("file", file);
    form.set("title", title);
    form.set("access_scope", scope);
    try {
      const result = await ingestKnowledgeDocument(form);
      await refreshDocuments();
      setTitle("");
      setFile(null);
      formElement.reset();
      setNotice(
        result.security_status === "alert_created"
          ? `Stored ${result.document.filename} (title: ${result.document.title}) locally as ${result.document.chunk_count} searchable chunks. Security alert ${result.security_alert_id} was created for analyst review.`
          : `Stored ${result.document.filename} (title: ${result.document.title}) locally as ${result.document.chunk_count} searchable chunks. Security inspection found no configured indicators.`,
      );
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Document ingestion failed.");
    } finally {
      setBusy(false);
    }
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
        Upload a PDF, DOCX, TXT, Markdown, HTML, XLSX, or PPTX file. The
        original file is not retained; extracted text is stored in the
        configured knowledge store and indexed for search. Configured AI
        providers may process document content during indexing.
      </p>
      <form className="question-form" onSubmit={(event) => void handleUpload(event)}>
        <label htmlFor="knowledge-title">Document title</label>
        <input
          id="knowledge-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          maxLength={200}
          required
        />
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
        <label htmlFor="knowledge-document">
          PDF, DOCX, TXT, MD, HTML, XLSX, or PPTX (maximum 10 MiB)
        </label>
        <input
          id="knowledge-document"
          type="file"
          accept=".pdf,.docx,.txt,.md,.html,.xlsx,.pptx"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          required
        />
        <button className="button" type="submit" disabled={busy}>
          {busy ? "Processing…" : "Ingest document"}
        </button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="success-message" role="status">{notice}</p>}
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
