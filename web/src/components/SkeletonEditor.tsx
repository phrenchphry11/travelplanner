import type { DraftDay, TripDraft } from "../lib/api";
import { dayLabel } from "../lib/api";

type Props = {
  draft: TripDraft;
  onChange: (draft: TripDraft) => void;
  disabled?: boolean;
};

export default function SkeletonEditor({ draft, onChange, disabled }: Props) {
  const update = (patch: Partial<TripDraft>) => onChange({ ...draft, ...patch });

  const setDay = (index: number, patch: Partial<DraftDay>) =>
    update({ days: draft.days.map((d, i) => (i === index ? { ...d, ...patch } : d)) });

  const move = (index: number, delta: -1 | 1) => {
    const target = index + delta;
    if (target < 0 || target >= draft.days.length) return;
    const days = [...draft.days];
    [days[index], days[target]] = [days[target], days[index]];
    update({ days });
  };

  const remove = (index: number) => update({ days: draft.days.filter((_, i) => i !== index) });

  const addDay = () => {
    const last = draft.days[draft.days.length - 1];
    update({ days: [...draft.days, { base_city: last?.base_city ?? "", title: "", summary: "" }] });
  };

  return (
    <section className="skeleton" aria-label="Trip days">
      <div className="form-row">
        <label>
          <span>Trip name</span>
          <input value={draft.title} disabled={disabled} maxLength={200} onChange={(e) => update({ title: e.target.value })} />
        </label>
        <label>
          <span>First day</span>
          <input
            type="date"
            value={draft.start_date ?? ""}
            disabled={disabled}
            onChange={(e) => update({ start_date: e.target.value || null })}
            required
          />
        </label>
        <label>
          <span>Travelers</span>
          <input
            type="number"
            min={1}
            max={50}
            value={draft.travelers ?? ""}
            disabled={disabled}
            onChange={(e) => update({ travelers: e.target.value ? Number(e.target.value) : null })}
          />
        </label>
      </div>

      <ol className="day-list">
        {draft.days.map((day, i) => (
          <li key={i} className="day-row">
            <span className="day-date">{dayLabel(draft.start_date, i)}</span>
            <input
              className="day-city"
              aria-label={`Place for day ${i + 1}`}
              placeholder="Where"
              value={day.base_city}
              disabled={disabled}
              maxLength={120}
              onChange={(e) => setDay(i, { base_city: e.target.value })}
            />
            <input
              className="day-title"
              aria-label={`Title for day ${i + 1}`}
              placeholder="What's the day about?"
              value={day.title}
              disabled={disabled}
              maxLength={200}
              onChange={(e) => setDay(i, { title: e.target.value })}
            />
            <span className="day-actions">
              <button type="button" className="icon" aria-label={`Move day ${i + 1} up`} disabled={disabled || i === 0} onClick={() => move(i, -1)}>↑</button>
              <button type="button" className="icon" aria-label={`Move day ${i + 1} down`} disabled={disabled || i === draft.days.length - 1} onClick={() => move(i, 1)}>↓</button>
              <button type="button" className="icon" aria-label={`Remove day ${i + 1}`} disabled={disabled || draft.days.length === 1} onClick={() => remove(i)}>✕</button>
            </span>
          </li>
        ))}
      </ol>
      <button type="button" className="button secondary" disabled={disabled || draft.days.length >= 60} onClick={addDay}>
        + Add a day
      </button>
    </section>
  );
}
