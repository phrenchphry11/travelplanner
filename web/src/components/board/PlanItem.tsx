import type { ReactNode } from "react";

type Props = {
  title: string;
  detail?: string;
  notes?: string;
  links: { label: string; url: string }[];
  onChange?: () => void;
  busy?: boolean;
  /** Replaces the Change button with custom controls. */
  actions?: ReactNode;
};

export default function PlanItem({ title, detail, notes, links, onChange, busy, actions }: Props) {
  return (
    <div className="plan-item">
      <div>
        <strong>{title}</strong>
        {detail && <span className="muted small"> · {detail}</span>}
        {notes && <p className="muted small">{notes}</p>}
        {links.length > 0 && (
          <p className="small plan-links">
            {links.map((l) => (
              <a key={l.url + l.label} href={l.url} target="_blank" rel="noreferrer">
                {l.label}
              </a>
            ))}
          </p>
        )}
      </div>
      {actions ? (
        <div className="plan-actions">{actions}</div>
      ) : (
        onChange && (
          <button type="button" className="link-button" onClick={onChange} disabled={busy}>
            Change
          </button>
        )
      )}
    </div>
  );
}
