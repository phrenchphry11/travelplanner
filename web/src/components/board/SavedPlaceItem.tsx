import { useState, type FormEvent } from "react";
import { SAVED_PLACE_KINDS, type BoardPlace, type SavedPlaceChanges, type SavedPlaceKind } from "../../lib/api";
import PlanItem from "./PlanItem";

type Props = {
  place: BoardPlace;
  busy: boolean;
  onEdit: (changes: SavedPlaceChanges) => Promise<void>;
  onRemove: () => void;
};

/** One saved place, with inline edit and remove. */
export default function SavedPlaceItem({ place, busy, ...actions }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<SavedPlaceChanges>({});
  const [error, setError] = useState<string | null>(null);

  function startEditing() {
    setDraft({ name: place.name, kind: place.kind as SavedPlaceKind, address: place.address, link: place.website_url, notes: place.notes });
    setError(null);
    setEditing(true);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!draft.name?.trim()) {
      setError("Give it a name.");
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
          Kind
          <select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as SavedPlaceKind })} disabled={busy}>
            {SAVED_PLACE_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Address
          <input value={draft.address} onChange={(e) => setDraft({ ...draft, address: e.target.value })} maxLength={300} disabled={busy} />
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

  const links = [place.website_url ? { label: "Link", url: place.website_url } : null].filter(
    (l): l is { label: string; url: string } => !!l,
  );

  return (
    <PlanItem
      title={place.name}
      notes={[place.notes, place.address].filter(Boolean).join(" · ")}
      links={links}
      busy={busy}
      actions={
        <>
          <button type="button" className="link-button" onClick={startEditing} disabled={busy}>
            Edit
          </button>
          <button type="button" className="link-button" onClick={actions.onRemove} disabled={busy}>
            Remove
          </button>
        </>
      }
    />
  );
}
