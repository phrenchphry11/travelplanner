import { useState, type FormEvent } from "react";
import { isJobActive, nightsLabel, timeOfDayLabel, type Board, type BoardCandidate, type BoardGap, type NewLodging } from "../../lib/api";
import AddLodging from "./AddLodging";
import CandidateCard from "./CandidateCard";

type Props = {
  board: Board;
  gap: BoardGap;
  busy: boolean;
  starting: boolean;
  hoveredId: string | null;
  onHover: (candidateId: string | null) => void;
  onClose: () => void;
  onChoose: (c: BoardCandidate) => void;
  onReject: (c: BoardCandidate, reason: string) => void;
  onRestore: (candidateId: string) => void;
  onFindMore: (nudge: string) => void;
  /** Drop a "Find ideas" request nobody wants any more. */
  onDismiss: () => void;
  onAddLodging?: (lodging: NewLodging) => Promise<void>;
};

export default function CompareDrawer(props: Props) {
  const { board, gap, busy, starting, hoveredId, onHover, onClose } = props;
  const [nudge, setNudge] = useState("");
  const looking = starting || isJobActive(gap.job);
  const failed = gap.job?.status === "failed" && !looking;
  const answered = gap.status === "answered";
  const located = new Set(board.places.filter((p) => p.lat !== null).map((p) => p.id));
  const hasOptions = gap.candidates.length > 0;

  function submitFindMore(e: FormEvent) {
    e.preventDefault();
    props.onFindMore(nudge.trim());
    setNudge("");
  }

  return (
    <section className="drawer" aria-label="Compare options">
      <header className="drawer-header">
        <button type="button" className="link-button" onClick={onClose}>
          ← Back to the board
        </button>
        <h3>{gap.prompt}</h3>
        <p className="muted small">
          {nightsLabel(board, gap)}
          {gap.time_of_day && ` · ${timeOfDayLabel(gap.time_of_day)}`}
        </p>
      </header>

      {answered && <p className="notice">You've chosen something for this. Use Change on the Day tab to pick again.</p>}

      {hasOptions && (
        <div className="compare-row">
          {gap.candidates.map((c) => (
            <CandidateCard
              key={c.id}
              candidate={c}
              hasPin={c.place_id ? located.has(c.place_id) : false}
              highlighted={hoveredId === c.id}
              onHover={(on) => onHover(on ? c.id : null)}
              actions={{
                onChoose: () => props.onChoose(c),
                onReject: (reason) => props.onReject(c, reason),
                busy,
                canChoose: !answered,
              }}
            />
          ))}
        </div>
      )}

      {!hasOptions && !looking && !failed && (
        <div className="empty">
          <p>No options yet. We'll search the web and bring back a few to compare, with sources.</p>
        </div>
      )}

      {looking && (
        <p className="gap-status" role="status">
          <span className="dot-pulse" aria-hidden /> Looking for {hasOptions ? "more " : ""}options… this can take a minute or two.
        </p>
      )}
      {failed && <p className="gap-status error small">{gap.job?.error || "That didn't work. Try again."}</p>}

      {!answered && !looking && (
        <form className="find-more" onSubmit={submitFindMore}>
          <input
            value={nudge}
            onChange={(e) => setNudge(e.target.value)}
            placeholder={hasOptions ? "Anything specific? e.g. cheaper, closer to the river" : "Anything specific? Optional"}
            maxLength={500}
            disabled={busy}
          />
          <button type="submit" disabled={busy}>
            {failed ? "Try again" : hasOptions ? "Find more" : "Find options"}
          </button>
        </form>
      )}

      {gap.kind === "lodging" && !answered && props.onAddLodging && (
        <AddLodging busy={busy} onAdd={props.onAddLodging} />
      )}

      {gap.hidden.length > 0 && (
        <details className="hidden-options">
          <summary>Hidden ({gap.hidden.length})</summary>
          <ul>
            {gap.hidden.map((h) => (
              <li key={h.id}>
                <span>
                  <strong>{h.name}</strong>
                  {h.reason && <span className="muted"> · {h.reason}</span>}
                </span>
                <button type="button" className="link-button" disabled={busy} onClick={() => props.onRestore(h.id)}>
                  Bring back
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}

      {gap.origin === "request" && !answered && (
        <p className="small">
          <button type="button" className="link-button" disabled={busy} onClick={props.onDismiss}>
            Remove this request
          </button>
        </p>
      )}
    </section>
  );
}
