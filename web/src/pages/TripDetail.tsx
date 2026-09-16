import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import TopBar from "../components/TopBar";
import { ApiError, formatDateRange, STATUS_LABELS, useApi, type Trip } from "../lib/api";

/** Placeholder until the planning board epic (travelplanner-7lr). */
export default function TripDetail() {
  const { tripId } = useParams();
  const api = useApi();
  const navigate = useNavigate();
  const [trip, setTrip] = useState<Trip | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Trip>(`/trips/${tripId}`)
      .then((data) => !cancelled && setTrip(data))
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
          <section className="empty">
            <p>The planning board for this trip is coming soon.</p>
          </section>
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
