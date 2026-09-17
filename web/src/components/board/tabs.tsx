import type { Board, BoardActivity, BoardDay, BoardGap, BoardLodging, NewLodging, NewPlan, PlanChanges, TimeOfDay } from "../../lib/api";
import { gapResolvedBy, isGapOpen, isJobActive, lodgingForNight, shortDate } from "../../lib/api";
import AddPlan from "./AddPlan";
import DayPlan from "./DayPlan";
import GapSlot from "./GapSlot";
import PlanItem from "./PlanItem";

type GapProps = {
  onOpenGap: (gap: BoardGap, opts?: { startResearch?: boolean }) => void;
  onChange: (gap: BoardGap) => void;
  onAddLodging: (gap: BoardGap, lodging: NewLodging) => Promise<void>;
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
  const notes = [stay.notes, stay.confirmation_code && `Confirmation: ${stay.confirmation_code}`, place?.address]
    .filter(Boolean)
    .join(" · ");
  return (
    <PlanItem
      key={stay.id}
      title={place?.name ?? "Stay"}
      detail={`${nights} night${nights === 1 ? "" : "s"} from ${shortDate(stay.check_in)}`}
      notes={notes}
      links={links}
      onChange={gap ? () => props.onChange(gap) : undefined}
      busy={props.busy}
    />
  );
}

export type PlanProps = {
  onFindIdeas: (day: BoardDay, request: string, timeOfDay: TimeOfDay) => Promise<void>;
  onAddPlan: (day: BoardDay, plan: NewPlan) => Promise<void>;
  onEditPlan: (activity: BoardActivity, changes: PlanChanges) => Promise<void>;
  onMovePlan: (activity: BoardActivity, direction: "up" | "down") => void;
  onRemovePlan: (activity: BoardActivity) => void;
};

export function OverviewTab({ board, onOpenDay, onOpenGap }: { board: Board; onOpenDay: (day: BoardDay) => void; onOpenGap: (gap: BoardGap) => void }) {
  const dayById = new Map(board.days.map((d) => [d.id, d]));
  const dayIndex = new Map(board.days.map((d, i) => [d.id, i]));
  const missing = board.gaps
    .filter((g) => g.missing)
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
            // An empty day's plans are added from the Day tab's "Add a plan", not the options drawer.
            const opensDay = !!day && g.kind === "activity" && g.origin === "starter" && count === 0 && !isJobActive(g.job);
            return (
              <li key={g.id}>
                <button type="button" className="row-button" onClick={() => (opensDay ? onOpenDay(day) : onOpenGap(g))}>
                  <span className="day-date">{day ? shortDate(day.date) : "Whole trip"}</span>
                  <span>{g.prompt}</span>
                  <span className={count ? "gaps has-gaps" : "muted small"}>
                    {count ? `${count} to compare` : g.kind === "lodging" ? "Stay" : "Add plans"}
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
          const open = board.gaps.filter((g) => g.missing && g.day_id === d.id).length;
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

export function DayTab({ board, day, ...props }: { board: Board; day: BoardDay } & GapProps & PlanProps) {
  const isLastDay = board.days[board.days.length - 1]?.id === day.id;
  // Already in order: morning, afternoon, evening, any time.
  const activities = board.activities.filter((a) => a.day_id === day.id);
  // "Add a plan" is the single way to add plans. The starter "What to do in..." item only
  // marks an empty day as missing; it's shown here just when it already has options or a
  // search going from before. Requests the traveler made always show until resolved.
  const activityGaps = board.gaps.filter(
    (g) =>
      g.kind === "activity" &&
      g.day_id === day.id &&
      isGapOpen(g) &&
      (g.origin === "request" || g.candidates.length > 0 || isJobActive(g.job) || props.startingGapIds.has(g.id)),
  );
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
        {activities.map((a, i) => {
          const gap = gapResolvedBy(board, a.id);
          const prev = activities[i - 1];
          const next = activities[i + 1];
          return (
            <DayPlan
              key={a.id}
              activity={a}
              place={placeOf(board, a.place_id)}
              chosen={!!gap}
              canMoveUp={!!prev && prev.time_of_day === a.time_of_day}
              canMoveDown={!!next && next.time_of_day === a.time_of_day}
              busy={props.busy}
              onEdit={(changes) => props.onEditPlan(a, changes)}
              onMove={(direction) => props.onMovePlan(a, direction)}
              onRemove={() => props.onRemovePlan(a)}
              onChange={gap ? () => props.onChange(gap) : undefined}
            />
          );
        })}
        {activityGaps.map((g) => (
          <GapSlot key={g.id} gap={g} onOpen={props.onOpenGap} starting={props.startingGapIds.has(g.id)} busy={props.busy} onAddLodging={props.onAddLodging} />
        ))}
        {activities.length === 0 && activityGaps.length === 0 && <p className="muted">Nothing planned yet.</p>}
        <AddPlan
          key={day.id}
          city={city}
          busy={props.busy}
          suggestedRequest={activities.length === 0 ? (city ? `Things to do in ${city}` : "Things to do") : ""}
          onFindIdeas={(request, time) => props.onFindIdeas(day, request, time)}
          onAdd={(plan) => props.onAddPlan(day, plan)}
        />
      </section>

      <section className="slot-group">
        <h4>Where you're sleeping</h4>
        {stay ? (
          stayItem(board, stay, props)
        ) : lodgingGap ? (
          <GapSlot gap={lodgingGap} onOpen={props.onOpenGap} starting={props.startingGapIds.has(lodgingGap.id)} busy={props.busy} onAddLodging={props.onAddLodging} />
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
                <GapSlot gap={g} onOpen={props.onOpenGap} starting={props.startingGapIds.has(g.id)} busy={props.busy} onAddLodging={props.onAddLodging} />
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
          const toReview = board.gaps.some((g) => g.kind === "activity" && g.day_id === d.id && g.missing);
          const label = planned.length === 0 ? "Needs plans" : toReview ? "Ideas to review" : "Planned";
          return (
            <li key={d.id}>
              <button type="button" className="row-button" onClick={() => onOpenDay(d)}>
                <span className="day-date">{shortDate(d.date)}</span>
                <span>
                  {planned.length > 0 ? planned.map((a) => a.name).join(", ") : <span className="muted">{d.title}</span>}
                </span>
                <span className={label !== "Planned" ? "gaps has-gaps" : "gaps"}>{label}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
