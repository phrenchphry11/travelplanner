import { useEffect, useRef, type ReactNode } from "react";

type Props = {
  open: boolean;
  title: string;
  children?: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

/** In-app confirmation using the native <dialog>: Escape closes it, focus stays inside, background is inert. */
export default function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "default",
  busy,
  onConfirm,
  onCancel,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="confirm-dialog"
      aria-labelledby="confirm-dialog-title"
      onCancel={(e) => {
        e.preventDefault(); // keep React in charge of open state
        if (!busy) onCancel();
      }}
      onClick={(e) => {
        // Clicking the dimmed backdrop (the dialog element itself) cancels.
        if (e.target === ref.current && !busy) onCancel();
      }}
    >
      <div className="confirm-dialog-body">
        <h2 id="confirm-dialog-title">{title}</h2>
        {children && <div className="confirm-dialog-text">{children}</div>}
        <div className="form-actions">
          <button type="button" className="button secondary" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button type="button" className={tone === "danger" ? "danger-solid" : undefined} onClick={onConfirm} disabled={busy} autoFocus>
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  );
}
