import { useState } from "react";
import type { BoardCandidate } from "../../lib/api";

function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

const CONFIDENCE_LABEL = { high: "Well sourced", medium: "Some sources", low: "Check details" } as const;

type Actions = {
  onChoose: () => void;
  onReject: (reason: string) => void;
  busy: boolean;
  canChoose: boolean;
};

type Props = {
  candidate: BoardCandidate;
  hasPin?: boolean;
  highlighted?: boolean;
  onHover?: (hovering: boolean) => void;
  actions?: Actions;
};

export default function CandidateCard({ candidate: c, hasPin, highlighted, onHover, actions }: Props) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const meta = [c.price_range, c.neighborhood, c.best_time && c.best_time !== "any" ? `Best in the ${c.best_time}` : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <article
      id={`candidate-${c.id}`}
      className={`candidate-card${highlighted ? " highlighted" : ""}`}
      onMouseEnter={() => onHover?.(true)}
      onMouseLeave={() => onHover?.(false)}
      onFocus={() => onHover?.(true)}
      onBlur={() => onHover?.(false)}
    >
      <header>
        <h5>{c.name}</h5>
        <span className={`confidence confidence-${c.unverified ? "low" : c.confidence}`}>
          {c.unverified ? "Unverified" : CONFIDENCE_LABEL[c.confidence]}
        </span>
      </header>
      {meta && <p className="muted small">{meta}</p>}
      <p>{c.summary}</p>
      {(c.pros.length > 0 || c.cons.length > 0) && (
        <ul className="pros-cons">
          {c.pros.map((p, i) => (
            <li key={`p${i}`} className="pro">{p}</li>
          ))}
          {c.cons.map((p, i) => (
            <li key={`c${i}`} className="con">{p}</li>
          ))}
        </ul>
      )}
      <footer className="small">
        {c.website_url && (
          <a href={c.website_url} target="_blank" rel="noreferrer">Website</a>
        )}
        {hasPin === false && <span className="muted">Not on the map</span>}
        {c.sources.length > 0 ? (
          <span className="muted">
            Sources:{" "}
            {c.sources.map((s, i) => (
              <span key={s.url}>
                {i > 0 && ", "}
                <a href={s.url} target="_blank" rel="noreferrer" title={s.note || s.title}>
                  {hostname(s.url)}
                </a>
              </span>
            ))}
          </span>
        ) : (
          <span className="muted">No sources we could confirm. Double-check before booking.</span>
        )}
      </footer>

      {actions && !rejecting && (
        <div className="card-actions">
          <button type="button" onClick={actions.onChoose} disabled={actions.busy || !actions.canChoose}>
            Choose
          </button>
          <button type="button" className="button secondary" onClick={() => setRejecting(true)} disabled={actions.busy}>
            Not this one
          </button>
        </div>
      )}
      {actions && rejecting && (
        <form
          className="reject-form"
          onSubmit={(e) => {
            e.preventDefault();
            actions.onReject(reason);
          }}
        >
          <label className="small">
            <span>Why not? Optional, helps the next search.</span>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Too far from the center"
              maxLength={300}
              autoFocus
            />
          </label>
          <div className="card-actions">
            <button type="submit" disabled={actions.busy}>Hide it</button>
            <button type="button" className="button secondary" onClick={() => setRejecting(false)}>Cancel</button>
          </div>
        </form>
      )}
    </article>
  );
}
