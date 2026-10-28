import { useEffect, useState, type FormEvent } from "react";
import {
  askQuestion,
  getConversation,
  type ConversationTurn,
  type RetrievalMode,
  type SourceCitation,
} from "../../api/chat";
import { ApiError } from "../../api/auth";

function formatSourceMetadata(source: SourceCitation): string {
  return [
    source.owner ? `Owner: ${source.owner}` : null,
    source.version ? `Version: ${source.version}` : null,
    source.effective_date ? `Effective: ${source.effective_date}` : null,
    source.next_review ? `Review due: ${source.next_review}` : null,
    source.environment,
  ].filter((item): item is string => Boolean(item)).join(" · ");
}

type ChatPanelProps = {
  userId: string;
};

export function ChatPanel({ userId }: ChatPanelProps) {
  const [question, setQuestion] = useState("");
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>("hybrid");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const storageKey = `knowledgeops:conversation:${userId}`;

  useEffect(() => {
    let active = true;
    const savedConversationId = window.localStorage.getItem(storageKey);

    if (savedConversationId) {
      getConversation(savedConversationId)
        .then((conversation) => {
          if (!active) return;
          setConversationId(conversation.conversation_id);
          setTurns(conversation.turns);
        })
        .catch((requestError: unknown) => {
          if (!active) return;
          if (requestError instanceof ApiError && requestError.status === 404) {
            window.localStorage.removeItem(storageKey);
          } else {
            setError("Conversation history could not be loaded.");
          }
        });
    }

    return () => {
      active = false;
    };
  }, [storageKey]);

  async function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim()) return;

    setBusy(true);
    setError(null);
    try {
      const response = await askQuestion(
        question.trim(),
        retrievalMode,
        conversationId,
      );
      setConversationId(response.conversation_id);
      window.localStorage.setItem(storageKey, response.conversation_id);
      setTurns(response.history);
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
      <p>Answers use permission-filtered documents and include source references when available.</p>
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
      {turns.length > 0 && (
        <div className="conversation" aria-live="polite" aria-label="Conversation">
          {turns.map((turn, index) => (
            <article className="answer" key={`${index}-${turn.intent}`}>
              <h3>You asked</h3>
              <p>{turn.question}</p>
              <h3>Answer</h3>
              <p className="eyebrow">Intent: {turn.intent}</p>
              <p>{turn.answer}</p>
              {turn.sources.length > 0 && (
                <>
                  <h3>Sources</h3>
                  <ul className="source-list">
                    {turn.sources.map((source) => (
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
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
