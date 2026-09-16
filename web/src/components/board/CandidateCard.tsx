import type { BoardCandidate } from "../../lib/api";

function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

const CONFIDENCE_LABEL = { high: "Well sourced", medium: "Some sources", low: "Check details" } as const;

export default function CandidateCard({ candidate: c }: { candidate: BoardCandidate }) {
  const meta = [c.price_range, c.neighborhood, c.best_time && c.best_time !== "any" ? `Best in the ${c.best_time}` : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <article className="candidate-card">
      <header>
        <h5>{c.name}</h5>
        <span className={`confidence confidence-${c.unverified ? "low" : c.confidence}`}>
          {c.unverified ? "Unverified" : CONFIDENCE_LABEL[c.confidence]}
        </span>
      </header>
      {meta && <p className="muted small">{meta}</p>}
      <p>{c.summary}</p>
      {(c.pros.length > 0 || c.cons.length > 0) && (
        <ul className="pros-cons">
          {c.pros.map((p, i) => (
            <li key={`p${i}`} className="pro">
              {p}
            </li>
          ))}
          {c.cons.map((p, i) => (
            <li key={`c${i}`} className="con">
              {p}
            </li>
          ))}
        </ul>
      )}
      <footer className="small">
        {c.website_url && (
          <a href={c.website_url} target="_blank" rel="noreferrer">
            Website
          </a>
        )}
        {c.sources.length > 0 ? (
          <span className="muted">
            Sources:{" "}
            {c.sources.map((s, i) => (
              <span key={s.url}>
                {i > 0 && ", "}
                <a href={s.url} target="_blank" rel="noreferrer" title={s.note || s.title}>
                  {hostname(s.url)}
                </a>
              </span>
            ))}
          </span>
        ) : (
          <span className="muted">No sources we could confirm. Double-check before booking.</span>
        )}
      </footer>
    </article>
  );
}
