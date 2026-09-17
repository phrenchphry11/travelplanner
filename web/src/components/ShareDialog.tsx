import { useEffect, useRef, useState } from "react";
import { shareUrl } from "../lib/share";

type Props = {
  open: boolean;
  slug: string | null;
  busy: boolean;
  error: string | null;
  onPublish: () => void;
  onRegenerate: () => void;
  onUnpublish: () => void;
  onClose: () => void;
};

/** Publish, copy, replace, or turn off a trip's read-only link. Native <dialog>, like ConfirmDialog. */
export default function ShareDialog({ open, slug, busy, error, onPublish, onRegenerate, onUnpublish, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // Remember which link the message is about, so a new link starts fresh.
  const [copied, setCopied] = useState<{ url: string; status: "copied" | "manual" } | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const url = slug ? shareUrl(slug) : "";
  const copy = open && copied?.url === url ? copied.status : "idle";

  useEffect(() => {
    if (copy !== "copied") return;
    const t = window.setTimeout(() => setCopied(null), 2500);
    return () => window.clearTimeout(t);
  }, [copy]);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied({ url, status: "copied" });
      return;
    } catch {
      // Clipboard API missing or blocked (e.g. not https): fall back below.
    }
    const input = inputRef.current;
    input?.focus();
    input?.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {
      ok = false;
    }
    setCopied({ url, status: ok ? "copied" : "manual" });
  }

  return (
    <dialog
      ref={ref}
      className="confirm-dialog share-dialog"
      aria-labelledby="share-dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current && !busy) onClose();
      }}
    >
      <div className="confirm-dialog-body">
        <h2 id="share-dialog-title">Share this trip</h2>
        {slug ? (
          <>
            <p className="confirm-dialog-text">
              Anyone with this link can see your days, where you're staying, and your plans. They can't change anything.
            </p>
            <div className="share-link">
              <label htmlFor="share-link-input" className="muted small">Your link</label>
              <div className="share-link-row">
                <input
                  id="share-link-input"
                  ref={inputRef}
                  type="text"
                  readOnly
                  value={url}
                  onFocus={(e) => e.currentTarget.select()}
                />
                <button type="button" onClick={copyLink} disabled={busy}>
                  {copy === "copied" ? "Copied" : "Copy"}
                </button>
              </div>
              <p className="small muted" role="status">
                {copy === "copied" && "Link copied. Paste it into a text or email."}
                {copy === "manual" && "Couldn't copy automatically. The link is selected, so copy it from there."}
              </p>
              <a className="button secondary share-open" href={url} target="_blank" rel="noreferrer">
                Open link
              </a>
            </div>
            <div className="share-manage">
              <div>
                <button type="button" className="button secondary small-button" onClick={onRegenerate} disabled={busy}>
                  Make a new link
                </button>
                <p className="small muted">The old link will stop working.</p>
              </div>
              <div>
                <button type="button" className="danger small-button" onClick={onUnpublish} disabled={busy}>
                  Stop sharing
                </button>
                <p className="small muted">Nobody can open the link after this.</p>
              </div>
            </div>
          </>
        ) : (
          <p className="confirm-dialog-text">
            Create a link you can send to the people you're traveling with. They'll see your days, where you're
            staying, and your plans on their phone, without signing in or being able to change anything.
          </p>
        )}
        {error && <p className="error small">{error}</p>}
        <div className="form-actions">
          <button type="button" className="button secondary" onClick={onClose} disabled={busy}>
            {slug ? "Done" : "Not now"}
          </button>
          {!slug && (
            <button type="button" onClick={onPublish} disabled={busy} autoFocus>
              {busy ? "Working…" : "Create link"}
            </button>
          )}
        </div>
      </div>
    </dialog>
  );
}
