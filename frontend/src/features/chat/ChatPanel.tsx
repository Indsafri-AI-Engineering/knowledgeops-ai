import { useState, type FormEvent } from "react";
import {
  askQuestion,
  type ChatResponse,
  type RetrievalMode,
  type SourceCitation,
} from "../../api/chat";

function formatSourceMetadata(source: SourceCitation): string {
  return [
    source.owner ? `Owner: ${source.owner}` : null,
    source.version ? `Version: ${source.version}` : null,
    source.effective_date ? `Effective: ${source.effective_date}` : null,
    source.next_review ? `Review due: ${source.next_review}` : null,
    source.environment,
  ].filter((item): item is string => Boolean(item)).join(" · ");
}

export function ChatPanel() {
  const [question, setQuestion] = useState("");
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>("hybrid");
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim()) return;

    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await askQuestion(question.trim(), retrievalMode);
      setResult(response);
      setQuestion("");
    } catch {
      setError("The question could not be answered. Check the API connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel chat-panel" aria-labelledby="chat-heading">
      <h2 id="chat-heading">Ask the knowledge base</h2>
      <p>
        Each question is handled independently. Questions and answers are not
        saved as chat history; answers use permission-filtered documents and
        include source references when available.
      </p>
      <form className="question-form" onSubmit={submitQuestion}>
        <label htmlFor="question">Your question</label>
        <textarea
          id="question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask a question about your authorized knowledge sources."
          maxLength={2000}
          required
          rows={3}
        />
        <label htmlFor="retrieval-mode">Retrieval mode</label>
        <select
          id="retrieval-mode"
          value={retrievalMode}
          onChange={(event) => {
            const mode = event.currentTarget.value;
            if (mode === "vector" || mode === "keyword" || mode === "hybrid") {
              setRetrievalMode(mode);
            }
          }}
        >
          <option value="hybrid">Hybrid (vector + BM25)</option>
          <option value="vector">Vector only</option>
          <option value="keyword">BM25 keyword only</option>
        </select>
        <button className="button" type="submit" disabled={busy || !question.trim()}>
          {busy ? "Searching…" : "Ask"}
        </button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {result && (
        <div className="answer" aria-live="polite" aria-label="Answer">
          <h3>You asked</h3>
          <p>{result.question}</p>
          <h3>Answer</h3>
          <p className="eyebrow">Intent: {result.intent}</p>
          <p>{result.answer}</p>
          {result.sources.length > 0 && (
            <>
              <h3>Sources</h3>
              <ul className="source-list">
                {result.sources.map((source) => (
                  <li key={source.document_id}>
                    <strong>{source.title}</strong>
                    <span>{source.source} · {source.section}</span>
                    {formatSourceMetadata(source) && (
                      <span>{formatSourceMetadata(source)}</span>
                    )}
                    <code>{source.source_path}</code>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </section>
  );
}
