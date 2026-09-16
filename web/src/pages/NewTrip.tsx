import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import SkeletonEditor from "../components/SkeletonEditor";
import TopBar from "../components/TopBar";
import { useApi, type ChatMessage, type IntakeTurnResponse, type Trip, type TripDraft } from "../lib/api";

const OPENING = "Tell me about the trip you're thinking about. Where, roughly when, who's going, and what you like to do.";
const EXAMPLE = "Portugal, 10 days in May, two of us, we like food, wine, and walking. Fly into Lisbon.";

function missingForConfirm(draft: TripDraft): string | null {
  if (!draft.title.trim()) return "Give the trip a name.";
  if (!draft.start_date) return "Pick the first day of the trip.";
  if (draft.days.length === 0) return "Add at least one day.";
  if (draft.days.some((d) => !d.base_city.trim())) return "Every day needs a place.";
  return null;
}

export default function NewTrip() {
  const api = useApi();
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [draft, setDraft] = useState<TripDraft | null>(null);
  const [thinking, setThinking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, thinking]);

  async function send(e?: FormEvent) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || thinking) return;
    const next: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setThinking(true);
    setError(null);
    try {
      const res = await api<IntakeTurnResponse>("/intake/turn", {
        method: "POST",
        body: JSON.stringify({ messages: next, current_draft: draft }),
      });
      setMessages([...next, { role: "assistant", content: res.reply, kind: res.kind }]);
      if (res.draft) {
        // Keep a start date the traveler already picked if the new draft has none.
        setDraft({ ...res.draft, start_date: res.draft.start_date ?? draft?.start_date ?? null });
      }
    } catch (err) {
      // Roll back the unanswered message so the conversation stays valid.
      setMessages(messages);
      setInput(text);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setThinking(false);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  async function confirm() {
    if (!draft || missingForConfirm(draft)) return;
    setSaving(true);
    setError(null);
    try {
      const trip = await api<Trip>("/intake/confirm", {
        method: "POST",
        body: JSON.stringify({
          title: draft.title,
          start_date: draft.start_date,
          travelers: draft.travelers,
          destinations: draft.destinations,
          interests: draft.interests,
          days: draft.days,
        }),
      });
      navigate(`/trips/${trip.id}`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSaving(false);
    }
  }

  const blocker = draft ? missingForConfirm(draft) : null;
  const busy = thinking || saving;

  return (
    <main className="page narrow-wide">
      <TopBar />
      <h1>Start a trip</h1>

      <section className="chat" aria-live="polite">
        <div className="bubble assistant">{OPENING}</div>
        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            {m.content}
          </div>
        ))}
        {thinking && <div className="bubble assistant thinking">Thinking…</div>}
        <div ref={bottomRef} />
      </section>

      <form className="chat-input" onSubmit={send}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={draft ? "Ask for changes, like \"make it 12 days\" or \"add a night in Évora\"" : EXAMPLE}
          rows={3}
          maxLength={4000}
          disabled={busy}
          autoFocus
        />
        <div className="chat-actions">
          {messages.length === 0 && (
            <button type="button" className="button secondary" disabled={busy} onClick={() => setInput(EXAMPLE)}>
              Use an example
            </button>
          )}
          <button type="submit" disabled={busy || !input.trim()}>
            Send
          </button>
        </div>
      </form>

      {error && <p className="error">{error}</p>}

      {draft && (
        <>
          <h2>Your days</h2>
          <p className="muted small">Edit anything below, or keep chatting to change it.</p>
          <SkeletonEditor draft={draft} onChange={setDraft} disabled={busy} />
          <div className="form-actions sticky-actions">
            {blocker && <span className="muted small">{blocker}</span>}
            <Link to="/trips" className="button secondary">
              Cancel
            </Link>
            <button type="button" disabled={busy || !!blocker} onClick={confirm}>
              {saving ? "Creating…" : "Looks good, create trip"}
            </button>
          </div>
        </>
      )}
      {!draft && (
        <p>
          <Link to="/trips">Cancel</Link>
        </p>
      )}
    </main>
  );
}
