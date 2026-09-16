import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ActivitiesTab, DayTab, LodgingTab, OverviewTab } from "../components/board/tabs";
import TripMap from "../components/board/TripMap";
import TopBar from "../components/TopBar";
import {
  ApiError,
  formatDateRange,
  isJobActive,
  STATUS_LABELS,
  useApi,
  type Board,
  type BoardDay,
  type BoardGap,
} from "../lib/api";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "day", label: "Day" },
  { id: "lodging", label: "Where to stay" },
  { id: "activities", label: "Things to do" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const POLL_MS = 3000;
const MAX_POLLS = 60; // stop after ~3 minutes of nothing changing

export default function TripBoard() {
  const { tripId } = useParams();
  const api = useApi();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [board, setBoard] = useState<Board | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startingGapIds, setStartingGapIds] = useState<Set<string>>(new Set());
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

  const openDay = (day: BoardDay) => setParams({ tab: "day", day: day.date });
  const setTab = (id: TabId) => {
    const next: Record<string, string> = { tab: id };
    if (selectedDay) next.day = selectedDay.date;
    setParams(next);
  };
  const selectPlace = (placeId: string) => {
    const day = board?.days.find((d) => d.base_place_id === placeId);
    if (day) openDay(day);
  };

  async function findOptions(gap: BoardGap) {
    setStartingGapIds((s) => new Set(s).add(gap.id));
    try {
      await api(`/gaps/${gap.id}/research`, { method: "POST" });
      polls.current = 0;
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStartingGapIds((s) => {
        const next = new Set(s);
        next.delete(gap.id);
        return next;
      });
    }
  }

  async function deleteTrip() {
    if (!board || !window.confirm(`Delete "${board.trip.title}"? This can't be undone.`)) return;
    try {
      await api(`/trips/${board.trip.id}`, { method: "DELETE" });
      navigate("/trips", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
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

  const selectedPlaceId = tab === "day" ? selectedDay?.base_place_id ?? null : null;
  const gapProps = { onFindOptions: findOptions, startingGapIds };

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
        <button type="button" className="danger small-button" onClick={deleteTrip}>
          Delete trip
        </button>
      </div>
      {error && <p className="error">{error}</p>}

      <div className="board">
        <TripMap days={board.days} places={board.places} selectedPlaceId={selectedPlaceId} onSelectPlace={selectPlace} />

        <section className="board-panel">
          {board.days.length > 0 && (
            <label className="day-picker">
              <span className="muted small">Day</span>
              <select
                value={selectedDay?.date ?? ""}
                onChange={(e) => setParams({ tab: "day", day: e.target.value })}
              >
                {board.days.map((d) => (
                  <option key={d.id} value={d.date}>
                    {new Date(`${d.date}T00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })} · {d.title}
                  </option>
                ))}
              </select>
            </label>
          )}

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

          {tab === "overview" && <OverviewTab board={board} onOpenDay={openDay} />}
          {tab === "day" && selectedDay && <DayTab board={board} day={selectedDay} {...gapProps} />}
          {tab === "lodging" && <LodgingTab board={board} onOpenDay={openDay} {...gapProps} />}
          {tab === "activities" && <ActivitiesTab board={board} onOpenDay={openDay} />}
        </section>
      </div>
    </main>
  );
}
