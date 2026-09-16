import { isJobActive, type BoardGap } from "../../lib/api";

type Props = {
  gap: BoardGap;
  onFindOptions: (gap: BoardGap) => void;
  starting: boolean;
};

export default function GapSlot({ gap, onFindOptions, starting }: Props) {
  const looking = starting || isJobActive(gap.job);
  const failed = gap.job?.status === "failed" && gap.status === "open";

  return (
    <div className={`gap-slot${looking ? " looking" : ""}`}>
      <p className="gap-prompt">{gap.prompt}</p>
      {looking ? (
        <p className="gap-status" role="status">
          <span className="dot-pulse" aria-hidden /> Looking for options…
        </p>
      ) : (
        <>
          {failed && <p className="gap-status error small">{gap.job?.error || "That didn't work. Try again."}</p>}
          <div className="gap-actions">
            <button type="button" onClick={() => onFindOptions(gap)}>
              {failed ? "Try again" : "Find options"}
            </button>
            <button type="button" className="link-button" disabled title="Coming soon">
              Add it yourself
            </button>
          </div>
        </>
      )}
    </div>
  );
}
