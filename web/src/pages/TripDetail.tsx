import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import TopBar from "../components/TopBar";
import { ApiError, dayLabel, formatDateRange, STATUS_LABELS, useApi, type DayOut, type Trip } from "../lib/api";

/** Placeholder until the planning board epic (travelplanner-7lr). */
export default function TripDetail() {
  const { tripId } = useParams();
  const api = useApi();
  const navigate = useNavigate();
  const [trip, setTrip] = useState<Trip | null>(null);
  const [days, setDays] = useState<DayOut[]>([]);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api<Trip>(`/trips/${tripId}`), api<DayOut[]>(`/trips/${tripId}/days`)])
      .then(([t, d]) => {
        if (cancelled) return;
        setTrip(t);
        setDays(d);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) setNotFound(true);
        else setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [api, tripId]);

  async function onDelete() {
    if (!trip || !window.confirm(`Delete "${trip.title}"? This can't be undone.`)) return;
    try {
      await api(`/trips/${trip.id}`, { method: "DELETE" });
      navigate("/trips", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <main className="page">
      <TopBar />
      <p>
        <Link to="/trips">← All trips</Link>
      </p>
      {notFound && <p>We couldn't find that trip.</p>}
      {error && <p className="error">{error}</p>}
      {!trip && !notFound && !error && <p className="muted">Loading…</p>}
      {trip && (
        <>
          <div className="page-heading">
            <div>
              <span className={`status-pill status-${trip.status}`}>{STATUS_LABELS[trip.status]}</span>
              <h1>{trip.title}</h1>
              <p className="muted">{formatDateRange(trip.start_date, trip.end_date)}</p>
            </div>
          </div>
          {days.length > 0 ? (
            <ol className="day-summary">
              {days.map((d, i) => (
                <li key={d.id}>
                  <span className="day-date">{dayLabel(trip.start_date, i)}</span>
                  <span>
                    <strong>{d.title}</strong>
                    {d.base_city && d.base_city !== d.title && <span className="muted"> · {d.base_city}</span>}
                  </span>
                  <span className={d.open_gap_count > 0 ? "gaps has-gaps" : "gaps"}>
                    {d.open_gap_count > 0 ? `${d.open_gap_count} to fill` : "All set"}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <section className="empty">
              <p>This trip has no days yet.</p>
            </section>
          )}
          <p className="muted small">The map and planning board for this trip are coming next.</p>
          <p>
            <button className="danger" onClick={onDelete}>
              Delete trip
            </button>
          </p>
        </>
      )}
    </main>
  );
}
