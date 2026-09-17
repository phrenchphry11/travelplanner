import { useEffect, useRef, useState, type FormEvent } from "react";

type Props = {
  open: boolean;
  catalog: string[];
  cards: string[] | null;
  busy: boolean;
  error: string | null;
  onSave: (cards: string[]) => Promise<void>;
  onClose: () => void;
};

function dedupe(names: string[]): string[] {
  const seen = new Map<string, string>();
  for (const name of names) {
    const trimmed = name.trim();
    if (trimmed && !seen.has(trimmed.toLowerCase())) seen.set(trimmed.toLowerCase(), trimmed);
  }
  return [...seen.values()];
}

/** Which cards and loyalty programs the traveler holds, for perk research. Native <dialog>, like CollaboratorsDialog. */
export default function CardsDialog({ open, catalog, cards, busy, error, onSave, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [others, setOthers] = useState<string[]>([]);
  const [otherInput, setOtherInput] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    if (!open || cards === null) return;
    const catalogLower = new Set(catalog.map((c) => c.toLowerCase()));
    setChecked(new Set(cards.filter((c) => catalogLower.has(c.toLowerCase()))));
    setOthers(cards.filter((c) => !catalogLower.has(c.toLowerCase())));
    setOtherInput("");
    setFormError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, cards]);

  function toggle(name: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function addOther(e?: FormEvent) {
    e?.preventDefault();
    const name = otherInput.trim();
    if (!name) return;
    setOthers((prev) => dedupe([...prev, name]));
    setOtherInput("");
  }

  function removeOther(name: string) {
    setOthers((prev) => prev.filter((o) => o !== name));
  }

  async function save() {
    try {
      await onSave(dedupe([...checked, ...others]));
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <dialog
      ref={ref}
      className="confirm-dialog share-dialog"
      aria-labelledby="cards-dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current && !busy) onClose();
      }}
    >
      <div className="confirm-dialog-body">
        <h2 id="cards-dialog-title">Cards & loyalty programs</h2>
        <p className="small muted">
          We'll flag a candidate when a public, dated benefit may apply &mdash; travel-portal bookings, dining
          credits, and the like. We never access your accounts or book anything for you.
        </p>

        <ul className="card-catalog-list">
          {catalog.map((name) => (
            <li key={name}>
              <label>
                <input type="checkbox" checked={checked.has(name)} onChange={() => toggle(name)} disabled={busy} />
                {name}
              </label>
            </li>
          ))}
        </ul>

        {others.length > 0 && (
          <ul className="collaborator-list">
            {others.map((name) => (
              <li key={name}>
                <span>{name}</span>
                <button type="button" className="link-button small" onClick={() => removeOther(name)} disabled={busy}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}

        <form className="invite-form" onSubmit={addOther}>
          <label htmlFor="other-card" className="muted small">
            Not listed? Add it by name
          </label>
          <div className="share-link-row">
            <input
              id="other-card"
              value={otherInput}
              onChange={(e) => setOtherInput(e.target.value)}
              placeholder="e.g. Costco Anywhere Visa"
              disabled={busy}
            />
            <button type="submit" disabled={busy || !otherInput.trim()}>
              Add
            </button>
          </div>
        </form>

        {(formError || error) && <p className="error small">{formError || error}</p>}
        <div className="form-actions">
          <button type="button" className="button secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" onClick={() => void save()} disabled={busy}>
            Save
          </button>
        </div>
      </div>
    </dialog>
  );
}
