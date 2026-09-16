import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import TopBar from "../components/TopBar";
import { useApi, type Trip } from "../lib/api";

/**
 * Simple create-trip form. The conversational intake epic
 * (travelplanner-o4y) replaces this with the "tell us about your trip" flow.
 */
export default function NewTrip() {
  const api = useApi();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const trip = await api<Trip>("/trips", {
        method: "POST",
        body: JSON.stringify({
          title,
          start_date: startDate || null,
          end_date: endDate || null,
        }),
      });
      navigate(`/trips/${trip.id}`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSaving(false);
    }
  }

  return (
    <main className="page narrow">
      <TopBar />
      <h1>Start a trip</h1>
      <form className="form" onSubmit={onSubmit}>
        <label>
          <span>Where are you going?</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Portugal in May"
            required
            maxLength={200}
            autoFocus
          />
        </label>
        <div className="form-row">
          <label>
            <span>First day</span>
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label>
            <span>Last day</span>
            <input
              type="date"
              value={endDate}
              min={startDate || undefined}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </label>
        </div>
        <p className="muted small">Not sure of dates yet? Leave them blank.</p>
        {error && <p className="error">{error}</p>}
        <div className="form-actions">
          <Link to="/trips" className="button secondary">
            Cancel
          </Link>
          <button type="submit" disabled={saving || !title.trim()}>
            {saving ? "Creating…" : "Create trip"}
          </button>
        </div>
      </form>
    </main>
  );
}
