import type { Board, BoardActivity, BoardDay, BoardGap, BoardLodging } from "../../lib/api";
import { gapResolvedBy, isGapOpen, lodgingForNight, shortDate } from "../../lib/api";
import GapSlot from "./GapSlot";
import PlanItem from "./PlanItem";

type GapProps = {
  onOpenGap: (gap: BoardGap, opts?: { startResearch?: boolean }) => void;
  onChange: (gap: BoardGap) => void;
  startingGapIds: Set<string>;
  busy: boolean;
};

function placeOf(board: Board, placeId: string | null) {
  return board.places.find((p) => p.id === placeId);
}

function placeName(board: Board, placeId: string | null): string {
  return placeOf(board, placeId)?.name ?? "";
}

function stayItem(board: Board, stay: BoardLodging, props: GapProps) {
  const place = placeOf(board, stay.place_id);
  const gap = gapResolvedBy(board, stay.id);
  const nights = Math.round((Date.parse(stay.check_out) - Date.parse(stay.check_in)) / 86_400_000);
  const links = [
    stay.booking_url ? { label: "Book", url: stay.booking_url } : null,
    place?.website_url && place.website_url !== stay.booking_url ? { label: "Website", url: place.website_url } : null,
  ].filter((l): l is { label: string; url: string } => !!l);
  return (
    <PlanItem
      key={stay.id}
      title={place?.name ?? "Stay"}
      detail={`${nights} night${nights === 1 ? "" : "s"} from ${shortDate(stay.check_in)}`}
      notes={[stay.notes, place?.address].filter(Boolean).join(" · ")}
      links={links}
      onChange={gap ? () => props.onChange(gap) : undefined}
      busy={props.busy}
    />
  );
}

function activityItem(board: Board, a: BoardActivity, props: GapProps) {
  const place = placeOf(board, a.place_id);
  const gap = gapResolvedBy(board, a.id);
  const links = [
    a.booking_url ? { label: "Book", url: a.booking_url } : null,
    place?.website_url && place.website_url !== a.booking_url ? { label: "Website", url: place.website_url } : null,
  ].filter((l): l is { label: string; url: string } => !!l);
  return (
    <PlanItem
      key={a.id}
      title={a.name}
      detail={a.start_time ? `in the ${a.start_time}` : undefined}
      notes={a.notes}
      links={links}
      onChange={gap ? () => props.onChange(gap) : undefined}
      busy={props.busy}
    />
  );
}

export function OverviewTab({ board, onOpenDay, onOpenGap }: { board: Board; onOpenDay: (day: BoardDay) => void; onOpenGap: (gap: BoardGap) => void }) {
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
            const count = g.candidates.length;
            return (
              <li key={g.id}>
                <button type="button" className="row-button" onClick={() => onOpenGap(g)}>
                  <span className="day-date">{day ? shortDate(day.date) : "Whole trip"}</span>
                  <span>{g.prompt}</span>
                  <span className={count ? "gaps has-gaps" : "muted small"}>
                    {count ? `${count} to compare` : g.kind === "lodging" ? "Stay" : "Plans"}
                  </span>
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
          const city = placeName(board, d.base_place_id);
          return (
            <li key={d.id}>
              <button type="button" className="row-button" onClick={() => onOpenDay(d)}>
                <span className="day-date">{shortDate(d.date)}</span>
                <span>
                  <strong>{d.title}</strong>
                  {city && city !== d.title && <span className="muted"> · {city}</span>}
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

export function DayTab({ board, day, ...props }: { board: Board; day: BoardDay } & GapProps) {
  const isLastDay = board.days[board.days.length - 1]?.id === day.id;
  const activities = board.activities.filter((a) => a.day_id === day.id);
  const activityGaps = board.gaps.filter((g) => g.kind === "activity" && g.day_id === day.id && isGapOpen(g));
  const stay = lodgingForNight(board, day.date);
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
        {activities.map((a) => activityItem(board, a, props))}
        {activityGaps.map((g) => (
          <GapSlot key={g.id} gap={g} onOpen={props.onOpenGap} starting={props.startingGapIds.has(g.id)} />
        ))}
        {activities.length === 0 && activityGaps.length === 0 && <p className="muted">Nothing planned.</p>}
      </section>

      <section className="slot-group">
        <h4>Where you're sleeping</h4>
        {stay ? (
          stayItem(board, stay, props)
        ) : lodgingGap ? (
          <GapSlot gap={lodgingGap} onOpen={props.onOpenGap} starting={props.startingGapIds.has(lodgingGap.id)} />
        ) : isLastDay ? (
          <p className="muted">Last day of the trip. No night to book.</p>
        ) : (
          <p className="muted">Nothing to book.</p>
        )}
      </section>
    </div>
  );
}

export function LodgingTab({ board, onOpenDay, ...props }: { board: Board; onOpenDay: (day: BoardDay) => void } & GapProps) {
  const dayById = new Map(board.days.map((d) => [d.id, d]));
  const stays = board.gaps.filter((g) => g.kind === "lodging");
  if (stays.length === 0) return <div className="tab-body"><p className="muted">No nights to book on this trip.</p></div>;

  return (
    <div className="tab-body">
      <ul className="stay-list">
        {stays.map((g) => {
          const nights = g.covers_day_ids.map((id) => dayById.get(id)).filter((d): d is BoardDay => !!d);
          const first = nights[0];
          const chosen = g.resolved_by_kind === "lodging" ? board.lodgings.find((l) => l.id === g.resolved_by_id) : undefined;
          return (
            <li key={g.id} className="stay-row">
              <div>
                <strong>{first ? placeName(board, first.base_place_id) : "Stay"}</strong>
                <p className="muted small">
                  {first && shortDate(first.date)} · {nights.length} night{nights.length === 1 ? "" : "s"}
                </p>
                {first && (
                  <button type="button" className="link-button small" onClick={() => onOpenDay(first)}>
                    View day
                  </button>
                )}
              </div>
              {chosen ? (
                stayItem(board, chosen, props)
              ) : isGapOpen(g) ? (
                <GapSlot gap={g} onOpen={props.onOpenGap} starting={props.startingGapIds.has(g.id)} />
              ) : (
                <span className="gaps">Sorted</span>
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
