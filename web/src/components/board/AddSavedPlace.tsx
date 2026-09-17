import { useState, type FormEvent } from "react";
import { SAVED_PLACE_KINDS, type NewSavedPlace, type SavedPlaceKind } from "../../lib/api";

type Props = {
  busy: boolean;
  onAdd: (place: NewSavedPlace) => Promise<void>;
};

const EMPTY: NewSavedPlace = { name: "", kind: "coffee", address: "", link: "", notes: "" };

export default function AddSavedPlace({ busy, onAdd }: Props) {
  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState<NewSavedPlace>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!place.name.trim()) {
      setError("Give it a name.");
      return;
    }
    try {
      await onAdd({ ...place, name: place.name.trim() });
      setPlace(EMPTY);
      setOpen(false);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (!open) {
    return (
      <button type="button" className="button secondary small-button" onClick={() => setOpen(true)} disabled={busy}>
        + Save a place
      </button>
    );
  }

  return (
    <form className="add-plan plan-form" onSubmit={submit}>
      <div className="add-plan-header">
        <strong>Save a place</strong>
        <button type="button" className="link-button" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
      </div>
      <label>
        What is it?
        <input
          value={place.name}
          onChange={(e) => setPlace({ ...place, name: e.target.value })}
          placeholder="e.g. A Brasileira"
          maxLength={200}
          disabled={busy}
          required
          autoFocus
        />
      </label>
      <label>
        Kind
        <select value={place.kind} onChange={(e) => setPlace({ ...place, kind: e.target.value as SavedPlaceKind })} disabled={busy}>
          {SAVED_PLACE_KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Address <span className="muted small">(optional, helps us put it on the map)</span>
        <input value={place.address} onChange={(e) => setPlace({ ...place, address: e.target.value })} maxLength={300} disabled={busy} />
      </label>
      <label>
        Link <span className="muted small">(optional)</span>
        <input
          value={place.link}
          onChange={(e) => setPlace({ ...place, link: e.target.value })}
          placeholder="e.g. a website or menu"
          maxLength={1000}
          inputMode="url"
          disabled={busy}
        />
      </label>
      <label>
        Notes <span className="muted small">(optional)</span>
        <textarea value={place.notes} onChange={(e) => setPlace({ ...place, notes: e.target.value })} rows={2} maxLength={2000} disabled={busy} />
      </label>
      {error && <p className="error small">{error}</p>}
      <div className="form-actions">
        <button type="submit" disabled={busy}>Save</button>
      </div>
    </form>
  );
}
