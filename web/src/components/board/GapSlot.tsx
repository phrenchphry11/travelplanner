import { isJobActive, timeOfDayLabel, type BoardGap } from "../../lib/api";

type Props = {
  gap: BoardGap;
  onOpen: (gap: BoardGap, opts?: { startResearch?: boolean }) => void;
  starting: boolean;
};

export default function GapSlot({ gap, onOpen, starting }: Props) {
  const looking = starting || isJobActive(gap.job);
  const failed = gap.job?.status === "failed" && gap.status === "open";
  const count = gap.candidates.length;

  return (
    <div className={`gap-slot${looking ? " looking" : ""}${count ? " has-options" : ""}`}>
      <p className="gap-prompt">
        {gap.prompt}
        {gap.time_of_day && <span className="muted small"> · {timeOfDayLabel(gap.time_of_day)}</span>}
      </p>
      {looking && (
        <p className="gap-status" role="status">
          <span className="dot-pulse" aria-hidden /> Looking for options…
        </p>
      )}
      {!looking && failed && count === 0 && (
        <p className="gap-status error small">{gap.job?.error || "That didn't work. Try again."}</p>
      )}
      <div className="gap-actions">
        <button
          type="button"
          className={count ? undefined : "button secondary"}
          onClick={() => onOpen(gap, { startResearch: count === 0 && !looking })}
        >
          {count ? `Compare ${count} option${count === 1 ? "" : "s"}` : looking ? "View progress" : "Find options"}
        </button>
      </div>
    </div>
  );
}
