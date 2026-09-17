"""Research agent: finds 3-5 sourced options for one gap in a trip.

Claude searches the web with Anthropic's server-side web search tool, then
calls our `submit_candidates` tool once with its picks. We only keep sources
whose URLs actually appeared in the search results Claude received.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import anthropic
from pydantic import BaseModel, ValidationError

from app.config import get_settings

log = logging.getLogger(__name__)

SUBMIT_TOOL = "submit_candidates"
BLOCKED_DOMAINS = ["pinterest.com", "quora.com"]


class ResearchError(Exception):
    """A user-presentable research failure."""


# ---- Inputs -----------------------------------------------------------------

@dataclass
class ResearchContext:
    trip_title: str
    destinations: list[str]
    interests: list[str]
    travelers: int | None
    trip_start: date | None
    trip_end: date | None
    gap_kind: str  # lodging | activity | ...
    gap_prompt: str
    day_date: date | None
    base_city: str | None
    nearby_days: list[str] = field(default_factory=list)  # "Tue May 4: Train to Porto (Porto)"
    nudge: str = ""
    time_of_day: str = ""  # morning | afternoon | evening | "" when the traveler asked for a time
    is_request: bool = False  # the gap is the traveler's own ask, in their words
    planned_that_day: list[str] = field(default_factory=list)  # "Tasca do Chico (evening)"
    stay: str | None = None  # "Hotel A, Baixa, Rua A 1, Lisbon"
    already_suggested: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (name, reason)
    today: date = field(default_factory=date.today)
    user_cards: list[str] = field(default_factory=list)  # traveler's cards/loyalty programs, by name only (PRD 11a)


# ---- Outputs ----------------------------------------------------------------

class SourceIn(BaseModel):
    url: str
    title: str
    note: str


class PerkIn(BaseModel):
    card: str  # exactly one of the traveler's held cards/programs, as given
    note: str  # plain sentence on what the perk is, using "may apply" wording
    source_url: str
    source_title: str


class CandidateIn(BaseModel):
    name: str
    summary: str
    pros: list[str]
    cons: list[str]
    confidence: Literal["low", "medium", "high"]
    price_range: str | None
    address: str | None
    neighborhood: str | None
    lat: float | None
    lng: float | None
    website_url: str | None
    booking_url: str | None
    map_query: str | None = None  # a short name OpenStreetMap can find, for the map pin
    activity_kind: Literal["meal", "sight", "tour", "outdoors", "shopping", "rest", "other"] | None
    best_time: Literal["morning", "afternoon", "evening", "any"] | None
    sources: list[SourceIn]
    perks: list[PerkIn] = []  # card/loyalty perks that may apply, only when sourced (PRD 11a)
    unverified: bool = False  # set by us, not by the model


@dataclass
class ResearchUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    searches: int = 0

    def add(self, usage: Any) -> None:
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        self.cache_write_tokens += usage.cache_creation_input_tokens or 0
        self.cache_read_tokens += usage.cache_read_input_tokens or 0
        stu = getattr(usage, "server_tool_use", None)
        self.searches += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0

    def cost_usd(self) -> float:
        s = get_settings()
        return round(
            self.input_tokens / 1e6 * s.price_input_per_mtok
            + self.output_tokens / 1e6 * s.price_output_per_mtok
            + self.cache_write_tokens / 1e6 * s.price_cache_write_per_mtok
            + self.cache_read_tokens / 1e6 * s.price_cache_read_per_mtok
            + self.searches * s.price_per_search,
            4,
        )


@dataclass
class ResearchResult:
    candidates: list[CandidateIn]
    usage: ResearchUsage


# ---- Tool + prompt ----------------------------------------------------------

def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


SUBMIT_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "summary": {"type": "string", "description": "One or two plain sentences on why this fits."},
                    "pros": {"type": "array", "items": {"type": "string"}},
                    "cons": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "price_range": _nullable({"type": "string", "description": "e.g. '€120–160 per night' or 'Free'"}),
                    "address": _nullable({"type": "string"}),
                    "neighborhood": _nullable({"type": "string"}),
                    "lat": _nullable({"type": "number"}),
                    "lng": _nullable({"type": "number"}),
                    "website_url": _nullable({"type": "string"}),
                    "booking_url": _nullable({"type": "string"}),
                    "map_query": _nullable({
                        "type": "string",
                        "description": "A short, searchable place name for a map, e.g. 'Place de Jaude, Clermont-Ferrand' or 'Château de Chambord'. Not a description.",
                    }),
                    "activity_kind": _nullable({"type": "string", "enum": ["meal", "sight", "tour", "outdoors", "shopping", "rest", "other"]}),
                    "best_time": _nullable({"type": "string", "enum": ["morning", "afternoon", "evening", "any"]}),
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string", "description": "Exactly as it appeared in a search result."},
                                "title": {"type": "string"},
                                "note": {"type": "string", "description": "What this page supports."},
                            },
                            "required": ["url", "title", "note"],
                            "additionalProperties": False,
                        },
                    },
                    "perks": {
                        "type": "array",
                        "description": "Only when the traveler's held cards/programs were given and a real, current, sourced perk plausibly applies to this candidate. Empty array otherwise -- never guess.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "card": {"type": "string", "description": "Exactly one of the traveler's cards/programs, as given."},
                                "note": {"type": "string", "description": "Plain sentence on the perk, using 'may apply' wording, e.g. 'May be bookable through the card's travel portal.'"},
                                "source_url": {"type": "string", "description": "Exactly as it appeared in a search result."},
                                "source_title": {"type": "string"},
                            },
                            "required": ["card", "note", "source_url", "source_title"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "name", "summary", "pros", "cons", "confidence", "price_range", "address", "neighborhood",
                    "lat", "lng", "website_url", "booking_url", "map_query", "activity_kind", "best_time", "sources",
                    "perks",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["candidates"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You research options for one open item in someone's trip plan, such as where to stay for a few nights or what to do on a given day. The traveler will compare your options and pick one, so give them real choices that differ in a meaningful way (price, area, style, pace).

Search the web and prefer official sites, reputable guides, and recent pages. Check that each place is plausibly open and operating for the travel dates. Fit the options to the day's location, the travelers' interests, and the rest of the trip.

Every fact you state (price, location, hours, what it's like) should come from a page you found. List those pages as sources, using URLs exactly as they appeared in your search results. When you can't confirm a detail, use null instead of guessing. Only give coordinates when a source provides them or the place is a well-known landmark. Always give a map_query that a map search could find (a venue, landmark, square, or town name), even when the option itself is an area or a route.

Don't make bookings or recommend paying anyone. When the traveler's held cards or loyalty programs are given, check whether a real, current, public benefit plausibly applies to a candidate (bookable through the card's travel portal, a dining-credit program, an airline transfer partner) and note it as a perk with a live source -- never guess or recall a benefit from memory, since these change often; leave a candidate's perks empty rather than invent one.

When you're done, call submit_candidates once with 3 to 5 options. If you truly can't find 3 good ones, submit what you have."""


def _format_context(ctx: ResearchContext) -> str:
    lines = [f"Today is {ctx.today.isoformat()}.", "", f"Trip: {ctx.trip_title}"]
    if ctx.destinations:
        lines.append(f"Destinations: {', '.join(ctx.destinations)}")
    if ctx.trip_start and ctx.trip_end:
        lines.append(f"Dates: {ctx.trip_start.isoformat()} to {ctx.trip_end.isoformat()}")
    if ctx.travelers:
        lines.append(f"Travelers: {ctx.travelers}")
    if ctx.interests:
        lines.append(f"Interests: {', '.join(ctx.interests)}")
    if ctx.user_cards:
        lines.append(f"Traveler holds these cards/loyalty programs: {', '.join(ctx.user_cards)}")
    if ctx.is_request:
        lines += ["", f"Open item ({ctx.gap_kind}), in the traveler's words: {ctx.gap_prompt}"]
    else:
        lines += ["", f"Open item ({ctx.gap_kind}): {ctx.gap_prompt}"]
    if ctx.time_of_day:
        lines.append(f"Time of day: {ctx.time_of_day}")
    if ctx.day_date:
        lines.append(f"Day: {ctx.day_date:%A %B} {ctx.day_date.day}, {ctx.day_date.year}")
    if ctx.base_city:
        lines.append(f"Based in: {ctx.base_city}")
    if ctx.stay:
        lines.append(f"Staying that night at: {ctx.stay}")
    if ctx.planned_that_day:
        lines += ["", "Already planned that day (fit around these, don't repeat them):"]
        lines += [f"- {p}" for p in ctx.planned_that_day]
    if ctx.nearby_days:
        lines += ["", "Surrounding days:"] + [f"- {d}" for d in ctx.nearby_days]
    if ctx.gap_kind == "lodging":
        lines += ["", "For each place to stay, include the nightly price range if you can find it and the neighborhood."]
    elif ctx.gap_kind == "activity":
        lines += ["", "For each option, set activity_kind and best_time, and say roughly how long it takes in the summary."]
    if ctx.nudge:
        lines += ["", f"The traveler asked for: {ctx.nudge}"]
    if ctx.already_suggested:
        lines += ["", "Already suggested (don't repeat): " + "; ".join(ctx.already_suggested)]
    if ctx.rejected:
        lines += ["", "Rejected by the traveler (don't repeat, and learn from the reasons):"]
        lines += [f"- {name}" + (f": {reason}" if reason else "") for name, reason in ctx.rejected]
    return "\n".join(lines)


# ---- Source verification ----------------------------------------------------

def normalize_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower().removeprefix("www."), path, parts.query, ""))


def collect_result_urls(content: list[Any]) -> set[str]:
    urls: set[str] = set()
    for block in content:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        results = getattr(block, "content", None)
        if not isinstance(results, list):  # an error object, not results
            continue
        for r in results:
            url = getattr(r, "url", None)
            if url:
                urls.add(normalize_url(url))
    return urls


def verify_sources(candidates: list[CandidateIn], seen_urls: set[str]) -> list[CandidateIn]:
    """Drop sources (and perks) Claude didn't actually see. Unsourced options become low-confidence
    and unverified; an unsourced perk is dropped entirely rather than shown unverified, since an
    unconfirmed benefit claim is worse than none (PRD 11a: never promise a credit will work)."""
    checked = []
    for c in candidates:
        kept = [s for s in c.sources if normalize_url(s.url) in seen_urls]
        dropped = len(c.sources) - len(kept)
        if dropped:
            log.info("dropped %d unseen source(s) for %r", dropped, c.name)
        kept_perks = [p for p in c.perks if normalize_url(p.source_url) in seen_urls]
        if len(kept_perks) != len(c.perks):
            log.info("dropped %d unsourced perk(s) for %r", len(c.perks) - len(kept_perks), c.name)
        update: dict[str, Any] = {"sources": kept, "perks": kept_perks}
        if not kept:
            update.update(unverified=True, confidence="low")
        checked.append(c.model_copy(update=update))
    return checked


# ---- Loop -------------------------------------------------------------------

@lru_cache
def _client() -> anthropic.Anthropic:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise ResearchError("The research assistant isn't configured yet.")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=300, max_retries=2)


def research_gap(ctx: ResearchContext, client: Any = None) -> ResearchResult:
    settings = get_settings()
    client = client or _client()
    tools = [
        {
            "type": "web_search_20260318",
            "name": "web_search",
            "max_uses": settings.research_max_searches_per_request,
            "blocked_domains": BLOCKED_DOMAINS,
        },
        {
            "name": SUBMIT_TOOL,
            "description": "Submit your final 3 to 5 options for this open item. Call this exactly once, at the end.",
            "strict": True,
            "input_schema": SUBMIT_SCHEMA,
        },
    ]
    messages: list[dict[str, Any]] = [{"role": "user", "content": _format_context(ctx)}]
    usage = ResearchUsage()
    seen_urls: set[str] = set()

    for turn in range(settings.research_max_turns):
        try:
            response = client.beta.messages.create(
                model=settings.research_model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=tools,
                output_config={"effort": settings.research_effort},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as exc:
            raise ResearchError("The research assistant is busy right now. Try again in a minute.") from exc
        except anthropic.APIStatusError as exc:
            log.exception("research API error")
            raise ResearchError("The research assistant hit a problem. Try again.") from exc
        except anthropic.APIConnectionError as exc:
            raise ResearchError("Couldn't reach the research assistant. Try again.") from exc

        usage.add(response.usage)
        seen_urls |= collect_result_urls(response.content)
        log.info(
            "research turn=%d stop=%s in=%d out=%d searches_so_far=%d",
            turn, response.stop_reason, response.usage.input_tokens, response.usage.output_tokens, usage.searches,
        )

        if response.stop_reason == "refusal":
            raise ResearchError("The research assistant couldn't help with this one.")

        submit = next(
            (b for b in response.content if getattr(b, "type", None) == "tool_use" and b.name == SUBMIT_TOOL),
            None,
        )
        if submit is not None:
            try:
                raw = submit.input.get("candidates", []) if isinstance(submit.input, dict) else []
                candidates = [CandidateIn.model_validate(c) for c in raw]
            except ValidationError as exc:
                log.warning("invalid submit_candidates input: %s", exc)
                raise ResearchError("The research assistant gave an unexpected answer. Try again.") from exc
            return ResearchResult(candidates=verify_sources(candidates[:5], seen_urls), usage=usage)

        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "pause_turn":
            continue  # server-side search loop paused; resend to resume
        # Finished talking without submitting (end_turn, max_tokens, or another tool).
        messages.append({"role": "user", "content": f"Please call {SUBMIT_TOOL} now with the best options you found."})

    raise ResearchError("The research assistant didn't finish in time. Try again.")


ResearchRunner = Callable[[ResearchContext], ResearchResult]
