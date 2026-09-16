import { isJobActive, type BoardGap } from "../../lib/api";
import CandidateCard from "./CandidateCard";

type Props = {
  gap: BoardGap;
  onFindOptions: (gap: BoardGap) => void;
  starting: boolean;
};

export default function GapSlot({ gap, onFindOptions, starting }: Props) {
  const looking = starting || isJobActive(gap.job);
  const failed = gap.job?.status === "failed" && gap.status === "open";
  const hasOptions = gap.candidates.length > 0;

  return (
    <div className={`gap-slot${looking ? " looking" : ""}${hasOptions ? " has-options" : ""}`}>
      <p className="gap-prompt">{gap.prompt}</p>

      {hasOptions && (
        <>
          <p className="muted small">
            {gap.candidates.length} option{gap.candidates.length === 1 ? "" : "s"} to compare. Picking one is coming soon.
          </p>
          <div className="candidate-list">
            {gap.candidates.map((c) => (
              <CandidateCard key={c.id} candidate={c} />
            ))}
          </div>
        </>
      )}

      {looking ? (
        <p className="gap-status" role="status">
          <span className="dot-pulse" aria-hidden /> Looking for options… this can take a minute or two.
        </p>
      ) : (
        <>
          {failed && <p className="gap-status error small">{gap.job?.error || "That didn't work. Try again."}</p>}
          <div className="gap-actions">
            <button type="button" className={hasOptions ? "button secondary" : undefined} onClick={() => onFindOptions(gap)}>
              {failed ? "Try again" : hasOptions ? "Find more" : "Find options"}
            </button>
            {!hasOptions && (
              <button type="button" className="link-button" disabled title="Coming soon">
                Add it yourself
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
