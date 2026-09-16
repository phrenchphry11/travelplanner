import type { Board, BoardDay, BoardGap } from "../../lib/api";
import { isGapOpen, shortDate } from "../../lib/api";
import GapSlot from "./GapSlot";

type GapProps = {
  onFindOptions: (gap: BoardGap) => void;
  startingGapIds: Set<string>;
};

function placeName(board: Board, placeId: string | null): string {
  return board.places.find((p) => p.id === placeId)?.name ?? "";
}

export function OverviewTab({ board, onOpenDay }: { board: Board; onOpenDay: (day: BoardDay) => void }) {
  const dayById = new Map(board.days.map((d) => [d.id, d]));
  const dayIndex = new Map(board.days.map((d, i) => [d.id, i]));
  const missing = board.gaps
    .filter(isGapOpen)
    .sort((a, b) => (dayIndex.get(a.day_id ?? "") ?? 0) - (dayIndex.get(b.day_id ?? "") ?? 0));

  return (
    <div className="tab-body">
      <h3>What's still missing</h3>
      {missing.length === 0 ? (
        <p className="muted">Nothing. Every day has a plan and a place to stay.</p>
      ) : (
        <ul className="missing-list">
          {missing.map((g) => {
            const day = g.day_id ? dayById.get(g.day_id) : undefined;
            return (
              <li key={g.id}>
                <button type="button" className="row-button" onClick={() => day && onOpenDay(day)}>
                  <span className="day-date">{day ? shortDate(day.date) : "Whole trip"}</span>
                  <span>{g.prompt}</span>
                  <span className="muted small">{g.kind === "lodging" ? "Stay" : "Plans"}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <h3>Days</h3>
      <ol className="day-summary">
        {board.days.map((d) => {
          const open = board.gaps.filter((g) => isGapOpen(g) && g.day_id === d.id).length;
          return (
            <li key={d.id}>
              <button type="button" className="row-button" onClick={() => onOpenDay(d)}>
                <span className="day-date">{shortDate(d.date)}</span>
                <span>
                  <strong>{d.title}</strong>
                  {placeName(board, d.base_place_id) && placeName(board, d.base_place_id) !== d.title && (
                    <span className="muted"> · {placeName(board, d.base_place_id)}</span>
                  )}
                </span>
                <span className={open > 0 ? "gaps has-gaps" : "gaps"}>{open > 0 ? `${open} to fill` : "All set"}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function DayTab({ board, day, ...gapProps }: { board: Board; day: BoardDay } & GapProps) {
  const isLastDay = board.days[board.days.length - 1]?.id === day.id;
  const activities = board.activities.filter((a) => a.day_id === day.id);
  const activityGaps = board.gaps.filter((g) => g.kind === "activity" && g.day_id === day.id && isGapOpen(g));
  const lodgingGap = board.gaps.find((g) => g.kind === "lodging" && isGapOpen(g) && g.covers_day_ids.includes(day.id));
  const city = placeName(board, day.base_place_id);

  return (
    <div className="tab-body">
      <header className="day-header">
        <p className="muted small">{shortDate(day.date)}{city && ` · ${city}`}</p>
        <h3>{day.title}</h3>
        {day.summary && <p>{day.summary}</p>}
      </header>

      <section className="slot-group">
        <h4>Plans for the day</h4>
        {activities.map((a) => (
          <div key={a.id} className="plan-item">
            {a.start_time && <span className="muted small">{a.start_time}</span>} <strong>{a.name}</strong>
          </div>
        ))}
        {activityGaps.map((g) => (
          <GapSlot key={g.id} gap={g} onFindOptions={gapProps.onFindOptions} starting={gapProps.startingGapIds.has(g.id)} />
        ))}
        {activities.length === 0 && activityGaps.length === 0 && <p className="muted">Nothing planned.</p>}
      </section>

      <section className="slot-group">
        <h4>Where you're sleeping</h4>
        {lodgingGap ? (
          <GapSlot gap={lodgingGap} onFindOptions={gapProps.onFindOptions} starting={gapProps.startingGapIds.has(lodgingGap.id)} />
        ) : isLastDay ? (
          <p className="muted">Last day of the trip. No night to book.</p>
        ) : (
          <p className="muted">Sorted.</p>
        )}
      </section>
    </div>
  );
}

export function LodgingTab({ board, onOpenDay, ...gapProps }: { board: Board; onOpenDay: (day: BoardDay) => void } & GapProps) {
  const dayById = new Map(board.days.map((d) => [d.id, d]));
  const stays = board.gaps.filter((g) => g.kind === "lodging");
  if (stays.length === 0) return <div className="tab-body"><p className="muted">No nights to book on this trip.</p></div>;

  return (
    <div className="tab-body">
      <ul className="stay-list">
        {stays.map((g) => {
          const nights = g.covers_day_ids.map((id) => dayById.get(id)).filter((d): d is BoardDay => !!d);
          const first = nights[0];
          return (
            <li key={g.id} className="stay-row">
              <div>
                <strong>{first ? placeName(board, first.base_place_id) : "Stay"}</strong>
                <p className="muted small">
                  {first && shortDate(first.date)} · {nights.length} night{nights.length === 1 ? "" : "s"}
                </p>
              </div>
              {isGapOpen(g) ? (
                <GapSlot gap={g} onFindOptions={gapProps.onFindOptions} starting={gapProps.startingGapIds.has(g.id)} />
              ) : (
                <span className="gaps">Sorted</span>
              )}
              {first && (
                <button type="button" className="link-button" onClick={() => onOpenDay(first)}>
                  View day
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function ActivitiesTab({ board, onOpenDay }: { board: Board; onOpenDay: (day: BoardDay) => void }) {
  return (
    <div className="tab-body">
      <ol className="day-summary">
        {board.days.map((d) => {
          const planned = board.activities.filter((a) => a.day_id === d.id);
          const open = board.gaps.some((g) => g.kind === "activity" && g.day_id === d.id && isGapOpen(g));
          return (
            <li key={d.id}>
              <button type="button" className="row-button" onClick={() => onOpenDay(d)}>
                <span className="day-date">{shortDate(d.date)}</span>
                <span>
                  {planned.length > 0 ? planned.map((a) => a.name).join(", ") : <span className="muted">{d.title}</span>}
                </span>
                <span className={open ? "gaps has-gaps" : "gaps"}>{open ? "Needs plans" : "Planned"}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
