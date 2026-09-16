import { useAuth } from "@clerk/clerk-react";
import { useCallback } from "react";

const API_URL = import.meta.env.VITE_API_URL ?? "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors: [{msg: "Value error, ..."}]
    if (Array.isArray(detail) && detail[0]?.msg) {
      return String(detail[0].msg).replace(/^Value error, /, "");
    }
  } catch {
    // fall through
  }
  return `Something went wrong (${res.status})`;
}

export async function api<T>(path: string, token: string | null, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) throw new ApiError(res.status, await readError(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Returns an api() bound to the signed-in user's Clerk token. */
export function useApi() {
  const { getToken } = useAuth();
  return useCallback(
    async <T,>(path: string, init: RequestInit = {}) => api<T>(path, await getToken(), init),
    [getToken],
  );
}

export type Trip = {
  id: string;
  title: string;
  start_date: string | null;
  end_date: string | null;
  status: "dreaming" | "planning" | "booked" | "done";
  open_gap_count: number;
};

export const STATUS_LABELS: Record<Trip["status"], string> = {
  dreaming: "Dreaming",
  planning: "Planning",
  booked: "Booked",
  done: "Done",
};

function parseDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** "May 1 – 10, 2027", "Apr 28 – May 3, 2027", or "Dates not set". */
export function formatDateRange(start: string | null, end: string | null): string {
  if (!start && !end) return "Dates not set";
  const fmt = (d: Date, opts: Intl.DateTimeFormatOptions) => d.toLocaleDateString(undefined, opts);
  if (start && !end) return `From ${fmt(parseDate(start), { month: "short", day: "numeric", year: "numeric" })}`;
  if (!start && end) return `Until ${fmt(parseDate(end), { month: "short", day: "numeric", year: "numeric" })}`;
  const s = parseDate(start!);
  const e = parseDate(end!);
  if (s.getFullYear() !== e.getFullYear()) {
    return `${fmt(s, { month: "short", day: "numeric", year: "numeric" })} – ${fmt(e, { month: "short", day: "numeric", year: "numeric" })}`;
  }
  if (s.getMonth() === e.getMonth()) {
    return `${fmt(s, { month: "short", day: "numeric" })} – ${e.getDate()}, ${e.getFullYear()}`;
  }
  return `${fmt(s, { month: "short", day: "numeric" })} – ${fmt(e, { month: "short", day: "numeric" })}, ${e.getFullYear()}`;
}

export type DraftDay = { base_city: string; title: string; summary: string };

export type TripDraft = {
  title: string;
  destinations: string[];
  start_date: string | null;
  travelers: number | null;
  interests: string[];
  days: DraftDay[];
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  kind?: "question" | "draft";
};

export type IntakeTurnResponse = {
  reply: string;
  kind: "question" | "draft";
  draft: TripDraft | null;
};

/** Add n days to a YYYY-MM-DD string and format like "Sat, May 1". */
export function dayLabel(startIso: string | null, offset: number): string {
  if (!startIso) return `Day ${offset + 1}`;
  const [y, m, d] = startIso.split("-").map(Number);
  const date = new Date(y, m - 1, d + offset);
  return date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

export type DayOut = {
  id: string;
  date: string;
  title: string;
  summary: string;
  base_city: string | null;
  open_gap_count: number;
};
