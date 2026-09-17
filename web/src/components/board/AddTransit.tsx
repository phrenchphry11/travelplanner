import { useState, type FormEvent } from "react";
import { TRANSIT_METHODS, type NewTransit, type TransitMethod } from "../../lib/api";

type Props = {
  busy: boolean;
  onAdd: (leg: NewTransit) => Promise<void>;
};

const EMPTY: NewTransit = { name: "", method: "train", depart_time: "", arrive_time: "", link: "", confirmation_code: "", notes: "" };

export default function AddTransit({ busy, onAdd }: Props) {
  const [open, setOpen] = useState(false);
  const [leg, setLeg] = useState<NewTransit>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!leg.name.trim()) {
      setError("Give this leg a name.");
      return;
    }
    try {
      await onAdd({ ...leg, name: leg.name.trim() });
      setLeg(EMPTY);
      setOpen(false);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (!open) {
    return (
      <button type="button" className="button secondary small-button" onClick={() => setOpen(true)} disabled={busy}>
        + Add transit
      </button>
    );
  }

  return (
    <form className="add-plan plan-form" onSubmit={submit}>
      <div className="add-plan-header">
        <strong>Add a travel leg</strong>
        <button type="button" className="link-button" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
      </div>
      <label>
        What's the leg?
        <input
          value={leg.name}
          onChange={(e) => setLeg({ ...leg, name: e.target.value })}
          placeholder="e.g. Lisbon to Porto"
          maxLength={200}
          disabled={busy}
          required
          autoFocus
        />
      </label>
      <label>
        How
        <select value={leg.method} onChange={(e) => setLeg({ ...leg, method: e.target.value as TransitMethod })} disabled={busy}>
          {TRANSIT_METHODS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </label>
      <div className="form-row">
        <label>
          Departs <span className="muted small">(optional, HH:MM)</span>
          <input value={leg.depart_time} onChange={(e) => setLeg({ ...leg, depart_time: e.target.value })} placeholder="10:47" maxLength={5} disabled={busy} />
        </label>
        <label>
          Arrives <span className="muted small">(optional)</span>
          <input value={leg.arrive_time} onChange={(e) => setLeg({ ...leg, arrive_time: e.target.value })} placeholder="12:55" maxLength={5} disabled={busy} />
        </label>
      </div>
      <label>
        Link <span className="muted small">(optional)</span>
        <input
          value={leg.link}
          onChange={(e) => setLeg({ ...leg, link: e.target.value })}
          placeholder="e.g. a booking confirmation"
          maxLength={1000}
          inputMode="url"
          disabled={busy}
        />
      </label>
      <label>
        Confirmation number <span className="muted small">(optional)</span>
        <input value={leg.confirmation_code} onChange={(e) => setLeg({ ...leg, confirmation_code: e.target.value })} maxLength={100} disabled={busy} />
      </label>
      <label>
        Notes <span className="muted small">(optional)</span>
        <textarea value={leg.notes} onChange={(e) => setLeg({ ...leg, notes: e.target.value })} rows={2} maxLength={2000} disabled={busy} />
      </label>
      {error && <p className="error small">{error}</p>}
      <div className="form-actions">
        <button type="submit" disabled={busy}>Save</button>
      </div>
    </form>
  );
}
