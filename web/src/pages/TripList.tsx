import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import TopBar from "../components/TopBar";
import { formatDateRange, STATUS_LABELS, useApi, type Trip } from "../lib/api";

function gapLabel(count: number): string {
  if (count === 0) return "Nothing missing";
  return count === 1 ? "1 thing still missing" : `${count} things still missing`;
}

export default function TripList() {
  const api = useApi();
  const [trips, setTrips] = useState<Trip[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Trip[]>("/trips")
      .then((data) => !cancelled && setTrips(data))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [api]);

  return (
    <main className="page">
      <TopBar />
      <div className="page-heading">
        <h1>Your trips</h1>
        {trips && trips.length > 0 && (
          <Link to="/trips/new" className="button">
            Start a trip
          </Link>
        )}
      </div>

      {error && <p className="error">We couldn't load your trips. {error}</p>}
      {trips === null && !error && <p className="muted">Loading…</p>}

      {trips && trips.length === 0 && (
        <section className="empty">
          <h2>Plan your first trip</h2>
          <p>
            Tell us about a trip you're thinking about. We'll sketch out the days, then help you
            find where to stay and what to do. You pick everything.
          </p>
          <Link to="/trips/new" className="button">
            Start a trip
          </Link>
        </section>
      )}

      {trips && trips.length > 0 && (
        <ul className="trip-grid">
          {trips.map((t) => (
            <li key={t.id}>
              <Link to={`/trips/${t.id}`} className="trip-card">
                <span className={`status-pill status-${t.status}`}>{STATUS_LABELS[t.status]}</span>
                <h2>{t.title}</h2>
                <p className="muted">{formatDateRange(t.start_date, t.end_date)}</p>
                <p className={t.open_gap_count > 0 ? "gaps has-gaps" : "gaps"}>
                  {gapLabel(t.open_gap_count)}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
