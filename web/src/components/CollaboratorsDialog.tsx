import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Collaborators } from "../lib/api";

type Props = {
  open: boolean;
  isOwner: boolean;
  collaborators: Collaborators | null;
  busy: boolean;
  error: string | null;
  onInvite: (email: string) => Promise<void>;
  onRemoveMember: (userId: string) => void;
  onCancelInvite: (inviteId: string) => void;
  onClose: () => void;
};

/** Who's planning this trip, and inviting more people by email. Native <dialog>, like ShareDialog. */
export default function CollaboratorsDialog({
  open,
  isOwner,
  collaborators,
  busy,
  error,
  onInvite,
  onRemoveMember,
  onCancelInvite,
  onClose,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [email, setEmail] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    if (!open) {
      setEmail("");
      setFormError(null);
    }
  }, [open]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim()) {
      setFormError("Enter an email address.");
      return;
    }
    try {
      await onInvite(email.trim());
      setEmail("");
      setFormError(null);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <dialog
      ref={ref}
      className="confirm-dialog share-dialog"
      aria-labelledby="collaborators-dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current && !busy) onClose();
      }}
    >
      <div className="confirm-dialog-body">
        <h2 id="collaborators-dialog-title">Who's planning this trip</h2>

        {collaborators && (
          <ul className="collaborator-list">
            {collaborators.members.map((m) => (
              <li key={m.user_id}>
                <span>
                  <strong>{m.display_name}</strong>
                  <span className="muted small"> · {m.role === "owner" ? "Owner" : "Can edit"}</span>
                </span>
                {isOwner && m.role !== "owner" && (
                  <button type="button" className="link-button small" onClick={() => onRemoveMember(m.user_id)} disabled={busy}>
                    Remove
                  </button>
                )}
              </li>
            ))}
            {collaborators.invites.map((i) => (
              <li key={i.id}>
                <span>
                  <strong>{i.email}</strong>
                  <span className="muted small"> · Invited, not signed in yet</span>
                </span>
                {isOwner && (
                  <button type="button" className="link-button small" onClick={() => onCancelInvite(i.id)} disabled={busy}>
                    Cancel
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}

        {isOwner && (
          <form className="invite-form" onSubmit={submit}>
            <label htmlFor="invite-email" className="muted small">
              Invite someone by email
            </label>
            <div className="share-link-row">
              <input
                id="invite-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="friend@example.com"
                disabled={busy}
              />
              <button type="submit" disabled={busy}>
                Invite
              </button>
            </div>
            <p className="small muted">
              They'll be able to see and edit everything on this trip. If they haven't used the app before, they get
              access the next time they sign in with that email.
            </p>
            {formError && <p className="error small">{formError}</p>}
          </form>
        )}

        {error && <p className="error small">{error}</p>}
        <div className="form-actions">
          <button type="button" className="button secondary" onClick={onClose} disabled={busy}>
            Done
          </button>
        </div>
      </div>
    </dialog>
  );
}
