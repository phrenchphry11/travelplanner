import { useAuth, UserButton } from "@clerk/clerk-react";
import { useEffect, useState } from "react";
import { api, type Trip } from "../lib/api";

export default function TripList() {
  const { getToken } = useAuth();
  const [trips, setTrips] = useState<Trip[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = await getToken();
        const data = await api<Trip[]>("/trips", token);
        if (!cancelled) setTrips(data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  return (
    <main className="page">
      <header className="topbar">
        <h1>Your trips</h1>
        <UserButton />
      </header>
      {error && <p className="error">Could not load trips: {error}</p>}
      {trips === null && !error && <p>Loading…</p>}
      {trips && trips.length === 0 && (
        <section className="empty">
          <p>No trips yet.</p>
          <p>
            Tell us about a trip you're thinking about and we'll sketch the days, then help
            you fill in where to stay and what to do.
          </p>
          <button disabled title="Coming in the intake epic">
            Start a trip
          </button>
        </section>
      )}
      {trips && trips.length > 0 && (
        <ul className="trip-list">
          {trips.map((t) => (
            <li key={t.id}>
              <strong>{t.title}</strong>
              <span>
                {t.start_date ?? "?"} → {t.end_date ?? "?"} · {t.status}
              </span>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
