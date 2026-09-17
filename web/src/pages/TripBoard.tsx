import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import CompareDrawer from "../components/board/CompareDrawer";
import ConfirmDialog from "../components/ConfirmDialog";
import ShareDialog from "../components/ShareDialog";
import { ActivitiesTab, DayTab, LodgingTab, OverviewTab, SavedPlacesTab } from "../components/board/tabs";
import TripMap, { type MapOption } from "../components/board/TripMap";
import TopBar from "../components/TopBar";
import {
  ApiError,
  formatDateRange,
  isJobActive,
  shortDate,
  STATUS_LABELS,
  useApi,
  type Board,
  type BoardActivity,
  type BoardCandidate,
  type BoardDay,
  type BoardGap,
  type BoardPlace,
  type NewLodging,
  type NewSavedPlace,
  type NewPlan,
  type PlanChanges,
  type SavedPlaceChanges,
  type TimeOfDay,
} from "../lib/api";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "day", label: "Day" },
  { id: "lodging", label: "Where to stay" },
  { id: "activities", label: "Things to do" },
  { id: "saved", label: "Saved places" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const POLL_MS = 3000;
const MAX_POLLS = 80; // stop after ~4 minutes of nothing changing

export default function TripBoard() {
  const { tripId } = useParams();
  const api = useApi();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [board, setBoard] = useState<Board | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startingGapIds, setStartingGapIds] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [hoveredCandidateId, setHoveredCandidateId] = useState<string | null>(null);
  const [pendingChange, setPendingChange] = useState<BoardGap | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const [shareBusy, setShareBusy] = useState(false);
  const [shareError, setShareError] = useState<string | null>(null);
  const [pendingRemove, setPendingRemove] = useState<BoardActivity | null>(null);
  const [pendingDismiss, setPendingDismiss] = useState<BoardGap | null>(null);
  const [pendingRemovePlace, setPendingRemovePlace] = useState<BoardPlace | null>(null);
  const [pendingDeleteTrip, setPendingDeleteTrip] = useState(false);
  const polls = useRef(0);

  const load = useCallback(async () => {
    try {
      const data = await api<Board>(`/trips/${tripId}/board`);
      setBoard(data);
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setNotFound(true);
      else setError(e instanceof Error ? e.message : String(e));
    }
  }, [api, tripId]);

  useEffect(() => {
    void load();
  }, [load]);

  const needsPolling = useMemo(
    () => !!board && (board.places.some((p) => p.locating) || board.gaps.some((g) => isJobActive(g.job))),
    [board],
  );

  useEffect(() => {
    if (!needsPolling) {
      polls.current = 0;
      return;
    }
    if (polls.current >= MAX_POLLS) return;
    const t = window.setTimeout(() => {
      polls.current += 1;
      void load();
    }, POLL_MS);
    return () => window.clearTimeout(t);
  }, [needsPolling, board, load]);

  const tab: TabId = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "overview") as TabId;
  const selectedDay: BoardDay | undefined =
    board?.days.find((d) => d.date === params.get("day")) ?? board?.days[0];
  const openGap: BoardGap | undefined = board?.gaps.find((g) => g.id === params.get("gap"));

  const nav = (next: { tab?: TabId; day?: string; gap?: string | null }) => {
    const p: Record<string, string> = {};
    p.tab = next.tab ?? tab;
    const day = next.day ?? selectedDay?.date;
    if (day) p.day = day;
    const gap = next.gap === undefined ? params.get("gap") : next.gap;
    if (gap) p.gap = gap;
    setParams(p);
  };
  const openDay = (day: BoardDay) => nav({ tab: "day", day: day.date, gap: null });
  const setTab = (id: TabId) => nav({ tab: id, gap: null });
  const closeDrawer = () => {
    setHoveredCandidateId(null);
    nav({ gap: null });
  };
  const selectPlace = (placeId: string) => {
    const day = board?.days.find((d) => d.base_place_id === placeId);
    if (day) openDay(day);
  };

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      polls.current = 0;
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  /** Like act(), but errors go back to the caller so a form can show them next to its fields. */
  async function submit<T>(fn: () => Promise<T>): Promise<T> {
    setBusy(true);
    try {
      const result = await fn();
      polls.current = 0;
      await load();
      return result;
    } finally {
      setBusy(false);
    }
  }

  // Research costs money: this runs only from the "Find ideas" button.
  async function findIdeas(day: BoardDay, request: string, timeOfDay: TimeOfDay) {
    const out = await submit(() =>
      api<{ gap_id: string }>(`/days/${day.id}/plan-requests`, {
        method: "POST",
        body: JSON.stringify({ request, time_of_day: timeOfDay }),
      }),
    );
    nav({ gap: out.gap_id, day: day.date });
  }

  async function addPlan(day: BoardDay, plan: NewPlan) {
    await submit(() => api(`/days/${day.id}/plans`, { method: "POST", body: JSON.stringify(plan) }));
  }

  async function addLodging(gap: BoardGap, lodging: NewLodging) {
    await submit(() => api(`/gaps/${gap.id}/lodging`, { method: "POST", body: JSON.stringify(lodging) }));
  }

  async function editPlan(activity: BoardActivity, changes: PlanChanges) {
    await submit(() => api(`/activities/${activity.id}`, { method: "PATCH", body: JSON.stringify(changes) }));
  }

  function movePlan(activity: BoardActivity, direction: "up" | "down") {
    void act(() => api(`/activities/${activity.id}/move`, { method: "POST", body: JSON.stringify({ direction }) }));
  }

  async function confirmRemove() {
    if (!pendingRemove) return;
    const activity = pendingRemove;
    await act(() => api(`/activities/${activity.id}`, { method: "DELETE" }));
    setPendingRemove(null);
  }

  async function confirmDismiss() {
    if (!pendingDismiss) return;
    const gap = pendingDismiss;
    await act(() => api(`/gaps/${gap.id}/dismiss`, { method: "POST" }));
    setPendingDismiss(null);
    closeDrawer();
  }

  async function addSavedPlace(place: NewSavedPlace) {
    await submit(() => api(`/trips/${board!.trip.id}/places`, { method: "POST", body: JSON.stringify(place) }));
  }

  async function editSavedPlace(placeId: string, changes: SavedPlaceChanges) {
    await submit(() => api(`/places/${placeId}`, { method: "PATCH", body: JSON.stringify(changes) }));
  }

  async function confirmRemovePlace() {
    if (!pendingRemovePlace) return;
    const place = pendingRemovePlace;
    await act(() => api(`/places/${place.id}`, { method: "DELETE" }));
    setPendingRemovePlace(null);
  }

  async function startResearch(gap: BoardGap, nudge = "") {
    setStartingGapIds((s) => new Set(s).add(gap.id));
    await act(() => api(`/gaps/${gap.id}/research`, { method: "POST", body: JSON.stringify({ nudge }) }));
    setStartingGapIds((s) => {
      const next = new Set(s);
      next.delete(gap.id);
      return next;
    });
  }

  function openGapDrawer(gap: BoardGap, opts: { startResearch?: boolean } = {}) {
    const day = board?.days.find((d) => d.id === gap.day_id);
    nav({ gap: gap.id, day: day?.date });
    // Research costs money, so it only starts from a button that says "Find options".
    if (opts.startResearch) void startResearch(gap);
  }

  async function choose(c: BoardCandidate) {
    await act(() => api(`/candidates/${c.id}/choose`, { method: "POST" }));
    closeDrawer();
  }

  function changeChoice(gap: BoardGap) {
    setPendingChange(gap);
  }

  async function confirmChange() {
    if (!pendingChange) return;
    const gap = pendingChange;
    await act(() => api(`/gaps/${gap.id}/reopen`, { method: "POST" }));
    setPendingChange(null);
    nav({ gap: gap.id });
  }

  function describeChoice(gap: BoardGap): { name: string; when: string } {
    if (!board) return { name: "This choice", when: "" };
    if (gap.resolved_by_kind === "lodging") {
      const stay = board.lodgings.find((l) => l.id === gap.resolved_by_id);
      const place = board.places.find((p) => p.id === stay?.place_id);
      const nights = stay ? Math.round((Date.parse(stay.check_out) - Date.parse(stay.check_in)) / 86_400_000) : 0;
      return {
        name: place?.name ?? "This stay",
        when: stay ? `your ${nights} night${nights === 1 ? "" : "s"} from ${new Date(`${stay.check_in}T00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}` : "this stay",
      };
    }
    const activity = board.activities.find((a) => a.id === gap.resolved_by_id);
    const day = board.days.find((d) => d.id === activity?.day_id);
    return {
      name: activity?.name ?? "This plan",
      when: day ? new Date(`${day.date}T00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }) : "this day",
    };
  }

  async function share(method: "POST" | "DELETE", path = "") {
    if (!board) return;
    setShareBusy(true);
    setShareError(null);
    try {
      await api(`/trips/${board.trip.id}/share${path}`, { method });
      await load();
    } catch (e) {
      setShareError(e instanceof Error ? e.message : String(e));
    } finally {
      setShareBusy(false);
    }
  }

  async function confirmDeleteTrip() {
    if (!board) return;
    await act(() => api(`/trips/${board.trip.id}`, { method: "DELETE" }));
    setPendingDeleteTrip(false);
    navigate("/trips", { replace: true });
  }

  if (notFound) {
    return (
      <main className="page">
        <TopBar />
        <p>We couldn't find that trip.</p>
        <Link to="/trips">← All trips</Link>
      </main>
    );
  }

  if (!board) {
    return (
      <main className="page">
        <TopBar />
        {error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}
      </main>
    );
  }

  const selectedPlaceId = tab === "day" || openGap ? selectedDay?.base_place_id ?? null : null;
  const chosenPlaceIds = new Set<string>([
    ...board.lodgings.map((l) => l.place_id),
    ...board.activities.map((a) => a.place_id).filter((id): id is string => !!id),
  ]);
  const placeById = new Map(board.places.map((p) => [p.id, p]));
  const mapOptions: MapOption[] = openGap
    ? openGap.candidates
        .map((candidate) => ({ candidate, place: candidate.place_id ? placeById.get(candidate.place_id) : undefined }))
        .filter((o): o is MapOption => !!o.place && o.place.lat !== null && o.place.lng !== null)
    : [];
  const gapProps = { onOpenGap: openGapDrawer, onChange: changeChoice, onAddLodging: addLodging, startingGapIds, busy };
  const planProps = {
    onFindIdeas: findIdeas,
    onAddPlan: addPlan,
    onEditPlan: editPlan,
    onMovePlan: movePlan,
    onRemovePlan: setPendingRemove,
  };
  const removingChosen = pendingRemove ? board.gaps.some((g) => g.resolved_by_id === pendingRemove.id) : false;
  const removingDay = pendingRemove ? board.days.find((d) => d.id === pendingRemove.day_id) : undefined;

  return (
    <main className="page wide">
      <TopBar />
      <div className="board-heading">
        <div>
          <Link to="/trips" className="small">← All trips</Link>
          <h1>{board.trip.title}</h1>
          <p className="muted">
            <span className={`status-pill status-${board.trip.status}`}>{STATUS_LABELS[board.trip.status]}</span>{" "}
            {formatDateRange(board.trip.start_date, board.trip.end_date)} ·{" "}
            {board.trip.open_gap_count === 0 ? "Nothing missing" : `${board.trip.open_gap_count} things still missing`}
          </p>
        </div>
        <div className="board-actions">
          <button
            type="button"
            className="small-button"
            onClick={() => {
              setShareError(null);
              setShareOpen(true);
            }}
          >
            Share{board.trip.share_slug && <span className="share-on"> · link on</span>}
          </button>
          <button type="button" className="danger small-button" onClick={() => setPendingDeleteTrip(true)} disabled={busy}>
            Delete trip
          </button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}

      <div className="board">
        <TripMap
          days={board.days}
          places={board.places}
          lodgings={board.lodgings}
          chosenPlaceIds={chosenPlaceIds}
          selectedPlaceId={selectedPlaceId}
          onSelectPlace={selectPlace}
          options={mapOptions}
          highlightedCandidateId={hoveredCandidateId}
          onHoverOption={setHoveredCandidateId}
          onSelectOption={(id) => {
            setHoveredCandidateId(id);
            document.getElementById(`candidate-${id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
          }}
        />

        <section className="board-panel">
          {openGap ? (
            <CompareDrawer
              board={board}
              gap={openGap}
              busy={busy}
              starting={startingGapIds.has(openGap.id)}
              hoveredId={hoveredCandidateId}
              onHover={setHoveredCandidateId}
              onClose={closeDrawer}
              onChoose={choose}
              onReject={(c, reason) => act(() => api(`/candidates/${c.id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }))}
              onRestore={(id) => act(() => api(`/candidates/${id}/restore`, { method: "POST" }))}
              onFindMore={(nudge) => startResearch(openGap, nudge)}
              onDismiss={() => setPendingDismiss(openGap)}
              onAddLodging={(lodging) => addLodging(openGap, lodging)}
            />
          ) : (
            <>
              <nav className="tabs" role="tablist" aria-label="Trip views">
                {TABS.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    role="tab"
                    aria-selected={tab === t.id}
                    className={tab === t.id ? "tab active" : "tab"}
                    onClick={() => setTab(t.id)}
                  >
                    {t.label}
                  </button>
                ))}
              </nav>

              {tab === "overview" && <OverviewTab board={board} onOpenDay={openDay} onOpenGap={openGapDrawer} />}
              {tab === "day" && selectedDay && (
                <>
                  <label className="day-picker">
                    <span className="muted small">Day</span>
                    <select value={selectedDay.date} onChange={(e) => nav({ tab: "day", day: e.target.value, gap: null })}>
                      {board.days.map((d) => (
                        <option key={d.id} value={d.date}>
                          {new Date(`${d.date}T00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })} · {d.title}
                        </option>
                      ))}
                    </select>
                  </label>
                  <DayTab board={board} day={selectedDay} {...gapProps} {...planProps} />
                </>
              )}
              {tab === "lodging" && <LodgingTab board={board} onOpenDay={openDay} {...gapProps} />}
              {tab === "activities" && <ActivitiesTab board={board} onOpenDay={openDay} />}
              {tab === "saved" && (
                <SavedPlacesTab
                  board={board}
                  busy={busy}
                  onAddSavedPlace={addSavedPlace}
                  onEditSavedPlace={editSavedPlace}
                  onRemoveSavedPlace={(placeId) => setPendingRemovePlace(board.places.find((p) => p.id === placeId) ?? null)}
                />
              )}
            </>
          )}
        </section>
      </div>

      <ShareDialog
        open={shareOpen}
        slug={board.trip.share_slug}
        busy={shareBusy}
        error={shareError}
        onPublish={() => share("POST")}
        onRegenerate={() => share("POST", "/regenerate")}
        onUnpublish={() => share("DELETE")}
        onClose={() => setShareOpen(false)}
      />

      <ConfirmDialog
        open={pendingChange !== null}
        title="Change your choice?"
        confirmLabel="Change it"
        busy={busy}
        onConfirm={confirmChange}
        onCancel={() => setPendingChange(null)}
      >
        {pendingChange && (
          <p>
            <strong>{describeChoice(pendingChange).name}</strong> will be removed from {describeChoice(pendingChange).when}.
            Your other options are still there, so you can pick again.
          </p>
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={pendingRemove !== null}
        title="Remove this plan?"
        confirmLabel="Remove it"
        tone={removingChosen ? "default" : "danger"}
        busy={busy}
        onConfirm={confirmRemove}
        onCancel={() => setPendingRemove(null)}
      >
        {pendingRemove && (
          <p>
            <strong>{pendingRemove.name}</strong> will be removed from {removingDay ? shortDate(removingDay.date) : "this day"}.{" "}
            {removingChosen ? "The other ideas we found are still there if you want to pick again." : "This can't be undone."}
          </p>
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={pendingDismiss !== null}
        title="Remove this request?"
        confirmLabel="Remove it"
        tone="danger"
        busy={busy}
        onConfirm={confirmDismiss}
        onCancel={() => setPendingDismiss(null)}
      >
        {pendingDismiss && (
          <p>
            <strong>{pendingDismiss.prompt}</strong> and the ideas we found for it will be removed from your day.
          </p>
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={pendingRemovePlace !== null}
        title="Remove this saved place?"
        confirmLabel="Remove it"
        tone="danger"
        busy={busy}
        onConfirm={confirmRemovePlace}
        onCancel={() => setPendingRemovePlace(null)}
      >
        {pendingRemovePlace && (
          <p>
            <strong>{pendingRemovePlace.name}</strong> will be removed from your saved places. This can't be undone.
          </p>
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={pendingDeleteTrip}
        title="Delete this trip?"
        confirmLabel="Delete it"
        tone="danger"
        busy={busy}
        onConfirm={confirmDeleteTrip}
        onCancel={() => setPendingDeleteTrip(false)}
      >
        <p>
          <strong>{board.trip.title}</strong> goes to your trash. You can restore it from the trip
          list for 30 days, after which it's gone for good.
        </p>
      </ConfirmDialog>
    </main>
  );
}
