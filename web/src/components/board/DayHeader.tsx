import { useState, type FormEvent } from "react";
import { shortDate, type BoardDay, type DayChanges } from "../../lib/api";

type Props = {
  day: BoardDay;
  city: string;
  busy: boolean;
  onEdit: (changes: DayChanges) => Promise<void>;
};

/** The Day tab's header: date and city are fixed, title and summary can be renamed. */
export default function DayHeader({ day, city, busy, onEdit }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<DayChanges>({ title: day.title, summary: day.summary });
  const [error, setError] = useState<string | null>(null);

  function startEditing() {
    setDraft({ title: day.title, summary: day.summary });
    setError(null);
    setEditing(true);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!draft.title.trim()) {
      setError("Give the day a title.");
      return;
    }
    try {
      await onEdit({ ...draft, title: draft.title.trim() });
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (editing) {
    return (
      <form className="day-header plan-form" onSubmit={save}>
        <p className="muted small">{shortDate(day.date)}{city && ` · ${city}`}</p>
        <label>
          Title
          <input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} maxLength={200} disabled={busy} required autoFocus />
        </label>
        <label>
          Summary <span className="muted small">(optional)</span>
          <textarea value={draft.summary} onChange={(e) => setDraft({ ...draft, summary: e.target.value })} rows={2} maxLength={1000} disabled={busy} />
        </label>
        {error && <p className="error small">{error}</p>}
        <div className="form-actions">
          <button type="button" className="button secondary small-button" onClick={() => setEditing(false)} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="small-button" disabled={busy}>
            Save
          </button>
        </div>
      </form>
    );
  }

  return (
    <header className="day-header">
      <p className="muted small">{shortDate(day.date)}{city && ` · ${city}`}</p>
      <div className="day-header-title">
        <h3>{day.title}</h3>
        <button type="button" className="link-button small" onClick={startEditing} disabled={busy}>
          Edit
        </button>
      </div>
      {day.summary && <p>{day.summary}</p>}
    </header>
  );
}
