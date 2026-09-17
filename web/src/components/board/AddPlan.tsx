import { useState, type FormEvent } from "react";
import { TIME_OF_DAY_OPTIONS, type NewPlan, type TimeOfDay } from "../../lib/api";

type Props = {
  city: string;
  busy: boolean;
  /** Prefilled "Find ideas" request, e.g. on an empty day. Editable before sending. */
  suggestedRequest?: string;
  /** Starts research, which costs money: only ever called from the "Find ideas" button. */
  onFindIdeas: (request: string, timeOfDay: TimeOfDay) => Promise<void>;
  onAdd: (plan: NewPlan) => Promise<void>;
};

type Mode = "closed" | "ideas" | "manual";

const EMPTY: NewPlan = { name: "", time_of_day: "", address: "", link: "", notes: "" };

export function TimeOfDaySelect({ value, onChange, disabled }: { value: TimeOfDay; onChange: (t: TimeOfDay) => void; disabled?: boolean }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value as TimeOfDay)} disabled={disabled}>
      {TIME_OF_DAY_OPTIONS.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export default function AddPlan({ city, busy, suggestedRequest = "", onFindIdeas, onAdd }: Props) {
  const [mode, setMode] = useState<Mode>("closed");
  const [request, setRequest] = useState("");
  const [requestTime, setRequestTime] = useState<TimeOfDay>("");
  const [plan, setPlan] = useState<NewPlan>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  function switchTo(next: Mode) {
    if (next === "ideas" && !request) setRequest(suggestedRequest);
    setMode(next);
    setError(null);
  }

  async function submitIdeas(e: FormEvent) {
    e.preventDefault();
    if (!request.trim()) {
      setError("Tell us what you're looking for.");
      return;
    }
    try {
      await onFindIdeas(request.trim(), requestTime);
      setRequest("");
      setRequestTime("");
      switchTo("closed");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function submitPlan(e: FormEvent) {
    e.preventDefault();
    if (!plan.name.trim()) {
      setError("Give your plan a name.");
      return;
    }
    try {
      await onAdd({ ...plan, name: plan.name.trim() });
      setPlan(EMPTY);
      switchTo("closed");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (mode === "closed") {
    return (
      <button type="button" className="button secondary small-button add-plan-button" onClick={() => switchTo("ideas")}>
        + Add a plan
      </button>
    );
  }

  return (
    <div className="add-plan">
      <div className="add-plan-header">
        <div className="segmented" role="tablist" aria-label="How to add a plan">
          <button type="button" role="tab" aria-selected={mode === "ideas"} className={mode === "ideas" ? "active" : ""} onClick={() => switchTo("ideas")}>
            Find ideas
          </button>
          <button type="button" role="tab" aria-selected={mode === "manual"} className={mode === "manual" ? "active" : ""} onClick={() => switchTo("manual")}>
            Add it yourself
          </button>
        </div>
        <button type="button" className="link-button" onClick={() => switchTo("closed")} disabled={busy}>
          Cancel
        </button>
      </div>

      {mode === "ideas" ? (
        <form className="plan-form" onSubmit={submitIdeas}>
          <label>
            What are you looking for?
            <input
              value={request}
              onChange={(e) => setRequest(e.target.value)}
              placeholder={city ? `e.g. dinner near our hotel, something for a rainy morning in ${city}` : "e.g. dinner near our hotel"}
              maxLength={300}
              disabled={busy}
              autoFocus
            />
          </label>
          <label>
            When?
            <TimeOfDaySelect value={requestTime} onChange={setRequestTime} disabled={busy} />
          </label>
          <p className="muted small">We'll search the web and bring back a few ideas to compare. This takes a minute or two.</p>
          {error && <p className="error small">{error}</p>}
          <div className="form-actions">
            <button type="submit" disabled={busy}>Find ideas</button>
          </div>
        </form>
      ) : (
        <form className="plan-form" onSubmit={submitPlan}>
          <label>
            What's the plan?
            <input
              value={plan.name}
              onChange={(e) => setPlan({ ...plan, name: e.target.value })}
              placeholder="e.g. Lunch at Time Out Market"
              maxLength={200}
              disabled={busy}
              required
              autoFocus
            />
          </label>
          <label>
            When?
            <TimeOfDaySelect value={plan.time_of_day} onChange={(t) => setPlan({ ...plan, time_of_day: t })} disabled={busy} />
          </label>
          <label>
            Address <span className="muted small">(optional, helps us put it on the map)</span>
            <input value={plan.address} onChange={(e) => setPlan({ ...plan, address: e.target.value })} maxLength={300} disabled={busy} />
          </label>
          <label>
            Link <span className="muted small">(optional)</span>
            <input
              value={plan.link}
              onChange={(e) => setPlan({ ...plan, link: e.target.value })}
              placeholder="e.g. a booking or website"
              maxLength={1000}
              inputMode="url"
              disabled={busy}
            />
          </label>
          <label>
            Notes <span className="muted small">(optional)</span>
            <textarea value={plan.notes} onChange={(e) => setPlan({ ...plan, notes: e.target.value })} rows={2} maxLength={2000} disabled={busy} />
          </label>
          {error && <p className="error small">{error}</p>}
          <div className="form-actions">
            <button type="submit" disabled={busy}>Add plan</button>
          </div>
        </form>
      )}
    </div>
  );
}
