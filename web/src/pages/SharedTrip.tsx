import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import SharedMap from "../components/share/SharedMap";
import { api, ApiError, formatDateRange, shortDate } from "../lib/api";
import {
  googleMapsUrl,
  stayForNight,
  timeLabel,
  type PublicDay,
  type PublicPlace,
  type PublicTrip,
} from "../lib/share";

/** Adds a <meta> tag for as long as the page is mounted. */
function useMeta(name: string, content: string) {
  useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = name;
    meta.content = content;
    document.head.appendChild(meta);
    return () => meta.remove();
  }, [name, content]);
}

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

type LinkItem = { label: string; url: string };

function Links({ links }: { links: LinkItem[] }) {
  if (links.length === 0) return null;
  return (
    <p className="shared-links">
      {links.map((l) => (
        <a key={l.label + l.url} href={l.url} target="_blank" rel="noreferrer">
          {l.label}
        </a>
      ))}
    </p>
  );
}

function placeLinks(place: PublicPlace | null, bookingUrl: string, websiteUrl: string, near?: string): LinkItem[] {
  const links: LinkItem[] = [];
  if (bookingUrl) links.push({ label: "Booking", url: bookingUrl });
  if (websiteUrl && websiteUrl !== bookingUrl) links.push({ label: "Website", url: websiteUrl });
  if (place) links.push({ label: "Google Maps", url: googleMapsUrl(place, near) });
  return links;
}

function DayDetails({ trip, day, isLast }: { trip: PublicTrip; day: PublicDay; isLast: boolean }) {
  const stay = stayForNight(trip, day.date);
  const near = day.city?.name;
  return (
    <div className="shared-day-body">
      {day.summary && <p className="shared-summary">{day.summary}</p>}

      <h3>Where you're sleeping</h3>
      {stay ? (
        <div className="shared-item stay">
          <strong>{stay.place.name}</strong>
          <p className="muted small">
            {stay.nights} night{stay.nights === 1 ? "" : "s"} · check in {shortDate(stay.check_in)}, check out {shortDate(stay.check_out)}
          </p>
          {stay.place.address && <p className="small">{stay.place.address}</p>}
          <Links links={placeLinks(stay.place, stay.booking_url, stay.website_url, near)} />
        </div>
      ) : (
        <p className="muted small">{isLast ? "Last day of the trip." : "Not listed yet."}</p>
      )}

      <h3>Plans</h3>
      {day.plans.length === 0 ? (
        <p className="muted small">Nothing planned. Free time!</p>
      ) : (
        <ul className="shared-plans">
          {day.plans.map((plan, i) => (
            <li key={i} className="shared-item">
              <span className="shared-time">{timeLabel(plan.time)}</span>
              <strong>{plan.name}</strong>
              {plan.place && (plan.place.name !== plan.name || plan.place.address) && (
                <p className="muted small">
                  {[plan.place.name !== plan.name ? plan.place.name : "", plan.place.address].filter(Boolean).join(" · ")}
                </p>
              )}
              {plan.notes && <p className="small">{plan.notes}</p>}
              <Links links={placeLinks(plan.place, plan.booking_url, plan.website_url, near)} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function SharedTrip() {
  const { slug = "" } = useParams();
  const [trip, setTrip] = useState<PublicTrip | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing" | "error">("loading");
  const [expanded, setExpanded] = useState<string | null>(null);

  useMeta("robots", "noindex");
  // Links out shouldn't tell other sites the private share URL.
  useMeta("referrer", "no-referrer");

  const load = useCallback(async () => {
    setState("loading");
    try {
      const data = await api<PublicTrip>(`/share/${encodeURIComponent(slug)}`, null);
      setTrip(data);
      setState("ready");
      // Open today's day while traveling, otherwise the first day.
      const today = todayIso();
      setExpanded((data.days.find((d) => d.date === today) ?? data.days[0])?.date ?? null);
    } catch (e) {
      setState(e instanceof ApiError && e.status === 404 ? "missing" : "error");
    }
  }, [slug]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const previous = document.title;
    if (trip) document.title = trip.title;
    return () => {
      document.title = previous;
    };
  }, [trip]);

  const showDay = (date: string, scroll: boolean) => {
    setExpanded(date);
    if (scroll) {
      window.requestAnimationFrame(() => document.getElementById(`day-${date}`)?.scrollIntoView({ behavior: "smooth", block: "start" }));
    }
  };

  if (state === "missing") {
    return (
      <main className="shared-page shared-message">
        <h1>This link isn't working</h1>
        <p>It may have been turned off or replaced with a new one. Ask the person who shared it to send you the latest link.</p>
      </main>
    );
  }
  if (state === "error") {
    return (
      <main className="shared-page shared-message">
        <h1>We couldn't load this trip</h1>
        <p>Check your connection and try again.</p>
        <button type="button" onClick={() => void load()}>Try again</button>
      </main>
    );
  }
  if (!trip) {
    return (
      <main className="shared-page shared-message">
        <p className="muted">Loading the trip…</p>
      </main>
    );
  }

  return (
    <main className="shared-page">
      <header className="shared-header">
        <h1>{trip.title}</h1>
        <p className="muted">{formatDateRange(trip.start_date, trip.end_date)}</p>
      </header>

      <div className="shared-layout">
        <SharedMap trip={trip} expandedDate={expanded} onSelectDate={(date) => showDay(date, true)} />

        <ol className="shared-days">
          {trip.days.length === 0 && <li className="muted">No days planned yet.</li>}
          {trip.days.map((day, i) => {
            const open = expanded === day.date;
            return (
              <li key={day.date} id={`day-${day.date}`} className={open ? "shared-day open" : "shared-day"}>
                <button
                  type="button"
                  className="shared-day-toggle"
                  aria-expanded={open}
                  aria-controls={`day-body-${day.date}`}
                  onClick={() => (open ? setExpanded(null) : showDay(day.date, false))}
                >
                  <span className="shared-day-date">{shortDate(day.date)}</span>
                  <span className="shared-day-title">
                    {day.title || `Day ${i + 1}`}
                    {day.city && day.city.name !== day.title && <span className="muted"> · {day.city.name}</span>}
                  </span>
                  <span className="shared-chevron" aria-hidden="true">{open ? "−" : "+"}</span>
                </button>
                {open && (
                  <div id={`day-body-${day.date}`}>
                    <DayDetails trip={trip} day={day} isLast={i === trip.days.length - 1} />
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </div>
    </main>
  );
}
