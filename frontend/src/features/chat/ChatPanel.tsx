import { useState, type FormEvent } from "react";
import {
  askQuestion,
  type ChatResponse,
  type SourceCitation,
} from "../../api/chat";
import { ApiError } from "../../api/auth";

const suggestedQuestions = [
  "Where can I find the latest team policies?",
  "What is the process for reporting an IT issue?",
  "Summarize the onboarding steps for a new employee.",
];

function formatSourceMetadata(source: SourceCitation): string {
  return [
    source.owner ? `Owner: ${source.owner}` : null,
    source.version ? `Version: ${source.version}` : null,
    source.effective_date ? `Effective: ${source.effective_date}` : null,
    source.next_review ? `Review due: ${source.next_review}` : null,
    source.environment,
  ].filter((item): item is string => Boolean(item)).join(" · ");
}

function getQuestionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const requestReference = error.requestId
      ? ` Request ID: ${error.requestId}.`
      : "";
    if (error.status === 401) {
      return `Your sign-in may have expired. Sign in again and retry.${requestReference}`;
    }
    if (error.status === 403) {
      return `Your account is not authorized to ask questions.${requestReference}`;
    }
    if (error.status === 422) {
      return `The API could not accept this question. Try shortening or rephrasing it.${requestReference}`;
    }
    if (error.status >= 500) {
      return `The API encountered an error while answering. Try again later.${requestReference}`;
    }
    return `The API rejected the question (HTTP ${error.status}).${requestReference}`;
  }
  if (error instanceof TypeError) {
    return "Could not connect to the API. Check that the backend is running and try again.";
  }
  return "The question request failed unexpectedly. Refresh the app and try again.";
}

export function ChatPanel() {
  const [question, setQuestion] = useState("");
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
      const response = await askQuestion(question.trim(), "hybrid");
      setResult(response);
      setQuestion("");
    } catch (requestError: unknown) {
      setError(getQuestionErrorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel chat-panel" aria-labelledby="chat-heading">
      <div className="chat-panel-heading">
        <span className="chat-assistant-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none">
            <path d="M5 5.75A2.75 2.75 0 0 1 7.75 3h8.5A2.75 2.75 0 0 1 19 5.75v8.5A2.75 2.75 0 0 1 16.25 17H12l-4.5 4v-4h-.25A2.75 2.75 0 0 1 5 14.25v-8.5Z" />
            <path d="m9 10 2 2 4-4" />
          </svg>
        </span>
        <div>
          <p className="eyebrow">KNOWLEDGE ASSISTANT</p>
          <h2 id="chat-heading">How can we help?</h2>
          <p>Ask a question and get a clear answer grounded in the knowledge you can access.</p>
        </div>
      </div>
      <form className="question-form" onSubmit={submitQuestion}>
        <label className="visually-hidden" htmlFor="question">Your question</label>
        <textarea
          id="question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about a policy, process, or team resource…"
          maxLength={2000}
          required
          rows={4}
        />
        <div className="question-form-footer">
          <span>Answers respect your workspace access.</span>
          <button className="button" type="submit" disabled={busy || !question.trim()}>
            {busy ? "Searching…" : "Ask"}
            {!busy && <span aria-hidden="true">→</span>}
          </button>
        </div>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {!result && !busy && (
        <div className="suggested-questions" aria-label="Suggested questions">
          <span className="suggestion-label">Need a starting point?</span>
          <div>
            {suggestedQuestions.map((suggestion) => (
              <button
                className="suggestion-chip"
                key={suggestion}
                type="button"
                onClick={() => setQuestion(suggestion)}
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      )}
      {result && (
        <div className="answer" aria-live="polite" aria-label="Answer">
          <div className="answer-question">
            <span className="answer-question-mark" aria-hidden="true">Q</span>
            <p>{result.question}</p>
          </div>
          <div className="answer-content">
            <div className="answer-heading">
              <span className="answer-heading-mark" aria-hidden="true">K</span>
              <h3>Answer</h3>
            </div>
            <p>{result.answer}</p>
          </div>
          {result.sources.length > 0 && (
            <>
              <h3 className="sources-heading">Sources</h3>
              <ul className="source-list">
                {result.sources.map((source) => (
                  <li key={source.document_id}>
                    <strong>{source.title}</strong>
                    <span>{source.section ? `${source.source} · ${source.section}` : source.source}</span>
                    {formatSourceMetadata(source) && (
                      <span>{formatSourceMetadata(source)}</span>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="answer-disclaimer">Review the source material when making important decisions.</p>
        </div>
      )}
    </section>
  );
}
