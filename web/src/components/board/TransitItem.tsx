import { useState, type FormEvent } from "react";
import { TRANSIT_METHODS, type BoardTransit, type TransitChanges, type TransitMethod } from "../../lib/api";
import PlanItem from "./PlanItem";

type Props = {
  leg: BoardTransit;
  busy: boolean;
  onEdit: (changes: TransitChanges) => Promise<void>;
  onRemove: () => void;
};

const METHOD_LABEL: Record<string, string> = Object.fromEntries(TRANSIT_METHODS.map((m) => [m.value, m.label]));

/** One transit leg, with inline edit and remove. */
export default function TransitItem({ leg, busy, ...actions }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<TransitChanges>({});
  const [error, setError] = useState<string | null>(null);

  function startEditing() {
    setDraft({
      name: leg.name, method: leg.method, depart_time: leg.depart_time, arrive_time: leg.arrive_time,
      link: leg.booking_url, confirmation_code: leg.confirmation_code, notes: leg.notes,
    });
    setError(null);
    setEditing(true);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!draft.name?.trim()) {
      setError("Give this leg a name.");
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
          How
          <select value={draft.method} onChange={(e) => setDraft({ ...draft, method: e.target.value as TransitMethod })} disabled={busy}>
            {TRANSIT_METHODS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <div className="form-row">
          <label>
            Departs
            <input value={draft.depart_time} onChange={(e) => setDraft({ ...draft, depart_time: e.target.value })} placeholder="10:47" maxLength={5} disabled={busy} />
          </label>
          <label>
            Arrives
            <input value={draft.arrive_time} onChange={(e) => setDraft({ ...draft, arrive_time: e.target.value })} placeholder="12:55" maxLength={5} disabled={busy} />
          </label>
        </div>
        <label>
          Link
          <input value={draft.link} onChange={(e) => setDraft({ ...draft, link: e.target.value })} maxLength={1000} inputMode="url" disabled={busy} />
        </label>
        <label>
          Confirmation number
          <input value={draft.confirmation_code} onChange={(e) => setDraft({ ...draft, confirmation_code: e.target.value })} maxLength={100} disabled={busy} />
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

  const times = [leg.depart_time, leg.arrive_time].filter(Boolean).join(" – ");
  const links = [leg.booking_url ? { label: "Link", url: leg.booking_url } : null].filter(
    (l): l is { label: string; url: string } => !!l,
  );

  return (
    <PlanItem
      title={leg.name}
      detail={[METHOD_LABEL[leg.method], times].filter(Boolean).join(" · ")}
      notes={[leg.confirmation_code && `Confirmation: ${leg.confirmation_code}`, leg.notes].filter(Boolean).join(" · ")}
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
