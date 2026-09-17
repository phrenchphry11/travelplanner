/** Public share-link payload (GET /share/{slug}). Kept apart from Board types on purpose:
 * it is a stripped, id-free view and must not grow private fields by accident. */

export type PublicPlace = {
  name: string;
  address: string;
  lat: number | null; // null when not pinned on the map
  lng: number | null;
};

export type PublicStay = {
  place: PublicPlace;
  check_in: string;
  check_out: string;
  nights: number;
  booking_url: string;
  website_url: string;
};

export type PublicPlan = {
  name: string;
  time: string; // "morning" | "afternoon" | "evening" | free text | ""
  place: PublicPlace | null;
  booking_url: string;
  website_url: string;
  notes: string;
};

export type PublicDay = {
  date: string;
  title: string;
  summary: string;
  city: PublicPlace | null;
  plans: PublicPlan[]; // already ordered morning, afternoon, evening, then the rest
};

export type PublicTrip = {
  title: string;
  start_date: string | null;
  end_date: string | null;
  days: PublicDay[];
  stays: PublicStay[];
};

export type ShareState = { share_slug: string | null };

export function shareUrl(slug: string): string {
  return `${window.location.origin}/s/${slug}`;
}

export function isPinned(p: PublicPlace | null | undefined): p is PublicPlace & { lat: number; lng: number } {
  return !!p && p.lat !== null && p.lng !== null;
}

/** The stay covering the night of this date (check_in <= date < check_out). */
export function stayForNight(trip: PublicTrip, isoDate: string): PublicStay | undefined {
  return trip.stays.find((s) => s.check_in <= isoDate && isoDate < s.check_out);
}

/** Google Maps search link: exact coordinates when pinned, otherwise name and address. */
export function googleMapsUrl(place: PublicPlace, near?: string): string {
  const query = isPinned(place)
    ? `${place.lat},${place.lng}`
    : [place.name, place.address || near].filter(Boolean).join(", ");
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

const TIME_LABELS: Record<string, string> = { morning: "Morning", afternoon: "Afternoon", evening: "Evening" };

export function timeLabel(time: string): string {
  const t = time.trim();
  if (!t) return "Any time";
  return TIME_LABELS[t.toLowerCase()] ?? t;
}
