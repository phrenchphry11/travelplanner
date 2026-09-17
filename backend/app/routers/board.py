"""Everything the planning board needs in one call, plus starting research on a gap."""
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.auth import current_user
from app.db import get_session
from app.geocoding import get_trip_locator, needs_lookup
from app.models import Activity, Candidate, Day, Gap, Lodging, Place, ResearchJob, Source, TripMember, User
from app.planning import OPEN_GAP_STATUSES, counts_as_missing, lodging_coverage, plan_order_key
from app.routers.trips import TripOut, get_member_trip, to_trip_out

router = APIRouter(tags=["board"])

ACTIVE_JOB_STATUSES = ("queued", "running")


class BoardDay(BaseModel):
    id: str
    date: date
    title: str
    summary: str
    base_place_id: str | None


class BoardPlace(BaseModel):
    id: str
    name: str
    kind: str
    lat: float | None
    lng: float | None
    precision: str
    locating: bool  # a lookup is pending or in flight
    address: str
    website_url: str
    summary: str
    notes: str
    saved: bool


class BoardJob(BaseModel):
    id: str
    status: str
    error: str


class BoardSource(BaseModel):
    title: str
    url: str
    note: str


class BoardCandidate(BaseModel):
    id: str
    name: str
    summary: str
    pros: list[str]
    cons: list[str]
    confidence: str
    unverified: bool
    price_range: str | None
    address: str | None
    neighborhood: str | None
    website_url: str | None
    booking_url: str | None
    activity_kind: str | None
    best_time: str | None
    place_id: str | None
    sources: list[BoardSource]


class BoardGap(BaseModel):
    id: str
    day_id: str | None
    kind: str
    prompt: str
    origin: str  # starter | request
    time_of_day: str
    status: str
    missing: bool  # counts toward "What's still missing"
    # Lodging gaps: the days whose night this stay covers. Others: just their day.
    covers_day_ids: list[str]
    job: BoardJob | None
    candidates: list[BoardCandidate]  # proposed options waiting for review
    hidden: list["BoardHidden"]  # options the traveler said no to
    resolved_by_kind: str | None  # lodging | activity, once an option is chosen
    resolved_by_id: str | None


class BoardHidden(BaseModel):
    id: str
    name: str
    reason: str


class BoardLodging(BaseModel):
    id: str
    place_id: str
    check_in: date
    check_out: date
    status: str
    booking_url: str
    confirmation_code: str
    notes: str


class BoardActivity(BaseModel):
    id: str
    day_id: str
    name: str
    kind: str
    place_id: str | None
    start_time: str
    time_of_day: str
    sort_order: int
    status: str
    booking_url: str
    notes: str


class Board(BaseModel):
    trip: TripOut
    days: list[BoardDay]
    places: list[BoardPlace]
    gaps: list[BoardGap]
    lodgings: list[BoardLodging]
    activities: list[BoardActivity]


@router.get("/trips/{trip_id}/board", response_model=Board)
def get_board(
    trip_id: str,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    locate: Callable[[str], None] = Depends(get_trip_locator),
) -> Board:
    trip = get_member_trip(session, trip_id, user)
    days = list(session.exec(select(Day).where(Day.trip_id == trip.id).order_by(Day.date)))
    places = list(session.exec(select(Place).where(Place.trip_id == trip.id)))
    gaps = list(session.exec(select(Gap).where(Gap.trip_id == trip.id).order_by(Gap.created_at)))
    lodgings = list(session.exec(select(Lodging).where(Lodging.trip_id == trip.id).order_by(Lodging.check_in)))
    # Each day's plans in the order they happen: morning, afternoon, evening, anytime.
    activities = sorted(
        session.exec(select(Activity).where(Activity.trip_id == trip.id)),
        key=lambda a: (a.day_id, *plan_order_key(a), a.id),
    )
    days_with_plans = {a.day_id for a in activities}

    # Latest job per gap.
    jobs: dict[str, ResearchJob] = {}
    for job in session.exec(
        select(ResearchJob).where(ResearchJob.trip_id == trip.id).order_by(ResearchJob.created_at)
    ):
        jobs[job.gap_id] = job

    candidates_by_gap: dict[str, list[Candidate]] = {}
    hidden_by_gap: dict[str, list[Candidate]] = {}
    for c in session.exec(
        select(Candidate)
        .where(Candidate.trip_id == trip.id, Candidate.status.in_(("proposed", "rejected")))
        .order_by(Candidate.created_at)
    ):
        bucket = candidates_by_gap if c.status == "proposed" else hidden_by_gap
        bucket.setdefault(c.gap_id, []).append(c)
    sources_by_candidate: dict[str, list[Source]] = {}
    for src in session.exec(select(Source).where(Source.trip_id == trip.id, Source.subject_kind == "candidate")):
        sources_by_candidate.setdefault(src.subject_id, []).append(src)

    pending_lookup = [p for p in places if needs_lookup(p)]
    if pending_lookup:
        background.add_task(locate, trip.id)

    missing = {g.id for g in gaps if counts_as_missing(g, days_with_plans)}
    return Board(
        trip=to_trip_out(trip, open_gap_count=len(missing)),
        days=[BoardDay(id=d.id, date=d.date, title=d.title, summary=d.summary, base_place_id=d.base_place_id) for d in days],
        places=[
            BoardPlace(
                id=p.id, name=p.name, kind=p.kind, lat=p.lat, lng=p.lng, precision=p.precision,
                locating=p in pending_lookup or (p.kind == "city" and p.lat is None and _recently_claimed(p)),
                address=p.address, website_url=p.website_url, summary=p.summary, notes=p.notes, saved=p.saved,
            )
            for p in places
        ],
        gaps=[
            BoardGap(
                id=g.id,
                day_id=g.day_id,
                kind=g.kind,
                prompt=g.prompt,
                origin=g.origin,
                time_of_day=g.time_of_day,
                status=g.status,
                missing=g.id in missing,
                covers_day_ids=[d.id for d in lodging_coverage(g, days)] if g.kind == "lodging" else ([g.day_id] if g.day_id else []),
                job=BoardJob(id=jobs[g.id].id, status=jobs[g.id].status, error=jobs[g.id].error) if g.id in jobs else None,
                candidates=[_candidate_out(c, sources_by_candidate.get(c.id, [])) for c in candidates_by_gap.get(g.id, [])],
                hidden=[
                    BoardHidden(id=c.id, name=(c.payload or {}).get("name", ""), reason=c.rejection_reason)
                    for c in hidden_by_gap.get(g.id, [])
                ],
                resolved_by_kind=g.resolved_by_kind,
                resolved_by_id=g.resolved_by_id,
            )
            for g in gaps
        ],
        lodgings=[
            BoardLodging(id=l.id, place_id=l.place_id, check_in=l.check_in, check_out=l.check_out,
                         status=l.status, booking_url=l.booking_url, confirmation_code=l.confirmation_code,
                         notes=l.notes)
            for l in lodgings
        ],
        activities=[
            BoardActivity(id=a.id, day_id=a.day_id, name=a.name, kind=a.kind, place_id=a.place_id,
                          start_time=a.start_time, time_of_day=a.time_of_day, sort_order=a.sort_order, status=a.status, booking_url=a.booking_url, notes=a.notes)
            for a in activities
        ],
    )


def _candidate_out(c: Candidate, sources: list[Source]) -> BoardCandidate:
    p = c.payload or {}
    return BoardCandidate(
        id=c.id,
        name=p.get("name", ""),
        summary=c.summary,
        pros=c.pros or [],
        cons=c.cons or [],
        confidence=c.confidence,
        unverified=bool(p.get("unverified")),
        price_range=p.get("price_range"),
        address=p.get("address"),
        neighborhood=p.get("neighborhood"),
        website_url=p.get("website_url"),
        booking_url=p.get("booking_url"),
        activity_kind=p.get("activity_kind"),
        best_time=p.get("best_time"),
        place_id=c.place_id,
        sources=[BoardSource(title=s.title, url=s.url, note=s.note) for s in sources],
    )


def _recently_claimed(place: Place) -> bool:
    """A lookup claimed in the last minute is probably still running."""
    claimed = place.geocoded_at
    if claimed is None:
        return False
    if claimed.tzinfo is None:
        claimed = claimed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - claimed < timedelta(minutes=1)


class JobOut(BaseModel):
    id: str
    gap_id: str
    status: str
    error: str


class ResearchRequest(BaseModel):
    nudge: str = Field(default="", max_length=500)


@router.post("/gaps/{gap_id}/research", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def start_research(
    gap_id: str,
    body: ResearchRequest | None = None,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> JobOut:
    gap = session.get(Gap, gap_id)
    if gap is None or session.get(TripMember, (gap.trip_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if gap.status not in OPEN_GAP_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "This is already filled in")

    active = session.exec(
        select(ResearchJob).where(ResearchJob.gap_id == gap.id, ResearchJob.status.in_(ACTIVE_JOB_STATUSES))
    ).first()
    job = active or ResearchJob(trip_id=gap.trip_id, gap_id=gap.id, nudge=(body.nudge.strip() if body else ""))
    if active is None:
        session.add(job)
    gap.status = "researching"
    session.add(gap)
    session.commit()
    session.refresh(job)
    return JobOut(id=job.id, gap_id=job.gap_id, status=job.status, error=job.error)
