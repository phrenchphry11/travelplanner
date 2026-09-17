import { useState, type FormEvent } from "react";
import { timeOfDayLabel, type BoardActivity, type BoardPlace, type PlanChanges } from "../../lib/api";
import { TimeOfDaySelect } from "./AddPlan";
import PlanItem from "./PlanItem";

type Props = {
  activity: BoardActivity;
  place: BoardPlace | undefined;
  chosen: boolean; // picked from research options
  canMoveUp: boolean;
  canMoveDown: boolean;
  busy: boolean;
  onEdit: (changes: PlanChanges) => Promise<void>;
  onMove: (direction: "up" | "down") => void;
  onRemove: () => void;
  onChange?: () => void;
};

/** One plan on the Day tab, with edit, move, and remove. */
export default function DayPlan({ activity: a, place, chosen, canMoveUp, canMoveDown, busy, ...actions }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<PlanChanges>({ name: a.name, time_of_day: a.time_of_day, link: a.booking_url, notes: a.notes });
  const [error, setError] = useState<string | null>(null);

  function startEditing() {
    setDraft({ name: a.name, time_of_day: a.time_of_day, link: a.booking_url, notes: a.notes });
    setError(null);
    setEditing(true);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!draft.name.trim()) {
      setError("Give your plan a name.");
      return;
    }
    try {
      await actions.onEdit({ ...draft, name: draft.name.trim() });
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (editing) {
    return (
      <form className="plan-item plan-form editing" onSubmit={save}>
        <label>
          Name
          <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} maxLength={200} disabled={busy} required autoFocus />
        </label>
        <label>
          When?
          <TimeOfDaySelect value={draft.time_of_day} onChange={(t) => setDraft({ ...draft, time_of_day: t })} disabled={busy} />
        </label>
        <label>
          Link
          <input value={draft.link} onChange={(e) => setDraft({ ...draft, link: e.target.value })} maxLength={1000} inputMode="url" disabled={busy} />
        </label>
        <label>
          Notes
          <textarea value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} rows={2} maxLength={2000} disabled={busy} />
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

  const links = [
    a.booking_url ? { label: chosen ? "Book" : "Link", url: a.booking_url } : null,
    place?.website_url && place.website_url !== a.booking_url ? { label: "Website", url: place.website_url } : null,
  ].filter((l): l is { label: string; url: string } => !!l);

  return (
    <PlanItem
      title={a.name}
      detail={a.time_of_day ? timeOfDayLabel(a.time_of_day) : undefined}
      notes={[a.notes, place?.address].filter(Boolean).join(" · ")}
      links={links}
      busy={busy}
      actions={
        <>
          <span className="move-buttons">
            <button type="button" className="icon" onClick={() => actions.onMove("up")} disabled={busy || !canMoveUp} aria-label={`Move ${a.name} earlier`} title="Move earlier">
              ↑
            </button>
            <button type="button" className="icon" onClick={() => actions.onMove("down")} disabled={busy || !canMoveDown} aria-label={`Move ${a.name} later`} title="Move later">
              ↓
            </button>
          </span>
          <button type="button" className="link-button" onClick={startEditing} disabled={busy}>
            Edit
          </button>
          {actions.onChange && (
            <button type="button" className="link-button" onClick={actions.onChange} disabled={busy}>
              Change
            </button>
          )}
          <button type="button" className="link-button" onClick={actions.onRemove} disabled={busy}>
            Remove
          </button>
        </>
      }
    />
  );
}
