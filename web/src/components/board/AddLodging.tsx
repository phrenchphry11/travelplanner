import { useState, type FormEvent } from "react";
import type { NewLodging } from "../../lib/api";

type Props = {
  busy: boolean;
  onAdd: (lodging: NewLodging) => Promise<void>;
};

const EMPTY: NewLodging = { name: "", address: "", link: "", confirmation_code: "", notes: "" };

export default function AddLodging({ busy, onAdd }: Props) {
  const [open, setOpen] = useState(false);
  const [lodging, setLodging] = useState<NewLodging>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!lodging.name.trim()) {
      setError("Give the place a name.");
      return;
    }
    try {
      await onAdd({ ...lodging, name: lodging.name.trim() });
      setLodging(EMPTY);
      setOpen(false);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (!open) {
    return (
      <button type="button" className="link-button small" onClick={() => setOpen(true)} disabled={busy}>
        Already booked something? Add it yourself
      </button>
    );
  }

  return (
    <form className="add-plan plan-form" onSubmit={submit}>
      <div className="add-plan-header">
        <strong>Add where you're staying</strong>
        <button type="button" className="link-button" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
      </div>
      <label>
        Where are you staying?
        <input
          value={lodging.name}
          onChange={(e) => setLodging({ ...lodging, name: e.target.value })}
          placeholder="e.g. The Balmoral, or my aunt's flat"
          maxLength={200}
          disabled={busy}
          required
          autoFocus
        />
      </label>
      <label>
        Address <span className="muted small">(optional, helps us put it on the map)</span>
        <input value={lodging.address} onChange={(e) => setLodging({ ...lodging, address: e.target.value })} maxLength={300} disabled={busy} />
      </label>
      <label>
        Link <span className="muted small">(optional)</span>
        <input
          value={lodging.link}
          onChange={(e) => setLodging({ ...lodging, link: e.target.value })}
          placeholder="e.g. a booking confirmation or website"
          maxLength={1000}
          inputMode="url"
          disabled={busy}
        />
      </label>
      <label>
        Confirmation number <span className="muted small">(optional)</span>
        <input
          value={lodging.confirmation_code}
          onChange={(e) => setLodging({ ...lodging, confirmation_code: e.target.value })}
          maxLength={100}
          disabled={busy}
        />
      </label>
      <label>
        Notes <span className="muted small">(optional)</span>
        <textarea value={lodging.notes} onChange={(e) => setLodging({ ...lodging, notes: e.target.value })} rows={2} maxLength={2000} disabled={busy} />
      </label>
      {error && <p className="error small">{error}</p>}
      <div className="form-actions">
        <button type="submit" disabled={busy}>Save</button>
      </div>
    </form>
  );
}
