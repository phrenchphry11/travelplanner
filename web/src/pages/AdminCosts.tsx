import { useEffect, useState } from "react";
import TopBar from "../components/TopBar";
import { ApiError, useApi, type CostSummary, type CostTotals } from "../lib/api";

function usd(n: number): string {
  return n < 1 ? `$${n.toFixed(3)}` : `$${n.toFixed(2)}`;
}

// Timestamps are naive UTC from the API.
function when(iso: string): string {
  return new Date(iso.endsWith("Z") ? iso : `${iso}Z`).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

function tripName(t: { trip_id: string | null; title: string | null; deleted: boolean }): string {
  if (!t.trip_id) return "Not yet a trip";
  if (t.title === null) return "Purged trip";
  return t.deleted ? `${t.title} (in trash)` : t.title;
}

function Totals({ label, t }: { label: string; t: CostTotals }) {
  return (
    <section className="admin-tile">
      <h2>{label}</h2>
      <p className="admin-big">{usd(t.cost_usd)}</p>
      <p className="muted small">
        Intake {usd(t.intake_cost_usd)} · Research {usd(t.research_cost_usd)}
      </p>
      <p className="muted small">
        {t.runs} runs ({t.failed_runs} failed) · {t.searches} searches
      </p>
    </section>
  );
}

export default function AdminCosts() {
  const api = useApi();
  const [data, setData] = useState<CostSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<CostSummary>("/admin/costs")
      .then(setData)
      .catch((e: Error) => setError(e instanceof ApiError && e.status === 404 ? "This page is for admins only." : e.message));
  }, [api]);

  return (
    <main className="page wide">
      <TopBar />
      <div className="page-heading">
        <h1>Agent costs</h1>
        <p className="muted small">Estimates from list prices. Internal only.</p>
      </div>
      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && (
        <>
          <div className="admin-tiles">
            <Totals label="Last 30 days" t={data.totals.last_30_days} />
            <Totals label="All time" t={data.totals.all_time} />
          </div>

          <h2>By trip</h2>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr><th>Trip</th><th>Owner</th><th className="num">Intake turns</th><th className="num">Research runs</th><th className="num">Searches</th><th className="num">Cost</th><th>Last run</th></tr>
              </thead>
              <tbody>
                {data.trips.map((t) => (
                  <tr key={t.trip_id}>
                    <td>{tripName(t)}</td>
                    <td>{t.owner_email ?? "—"}</td>
                    <td className="num">{t.intake_turns}</td>
                    <td className="num">{t.research_runs}</td>
                    <td className="num">{t.searches}</td>
                    <td className="num">{usd(t.cost_usd)}</td>
                    <td>{when(t.last_run_at)}</td>
                  </tr>
                ))}
                {data.trips.length === 0 && <tr><td colSpan={7} className="muted">No agent runs yet.</td></tr>}
              </tbody>
            </table>
          </div>

          <h2>By user</h2>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr><th>User</th><th className="num">Trips</th><th className="num">Runs</th><th className="num">Cost</th><th>Last run</th></tr>
              </thead>
              <tbody>
                {data.users.map((u) => (
                  <tr key={u.user_id}>
                    <td>{u.email ?? "Unknown user"}</td>
                    <td className="num">{u.trips}</td>
                    <td className="num">{u.runs}</td>
                    <td className="num">{usd(u.cost_usd)}</td>
                    <td>{when(u.last_run_at)}</td>
                  </tr>
                ))}
                {data.users.length === 0 && <tr><td colSpan={5} className="muted">No agent runs yet.</td></tr>}
              </tbody>
            </table>
          </div>

          <h2>Recent runs</h2>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr><th>When</th><th>Kind</th><th>Trip</th><th>User</th><th>Model</th><th className="num">Tokens in / out</th><th className="num">Searches</th><th className="num">Cost</th></tr>
              </thead>
              <tbody>
                {data.recent.map((r) => (
                  <tr key={r.id} className={r.ok ? undefined : "failed"}>
                    <td>{when(r.created_at)}</td>
                    <td>{r.kind}{r.ok ? "" : " (failed)"}</td>
                    <td>{tripName(r)}</td>
                    <td>{r.user_email ?? "—"}</td>
                    <td>{r.model || "—"}</td>
                    <td className="num">{r.input_tokens.toLocaleString()} / {r.output_tokens.toLocaleString()}</td>
                    <td className="num">{r.searches}</td>
                    <td className="num">{usd(r.cost_usd)}</td>
                  </tr>
                ))}
                {data.recent.length === 0 && <tr><td colSpan={8} className="muted">No agent runs yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </main>
  );
}
