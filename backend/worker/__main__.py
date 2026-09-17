"""Research worker.

Polls the research_jobs table and runs one job at a time: builds context for
the job's gap, asks the research agent for options, and saves them as
Candidate, Place, and Source rows. Several workers can run safely; jobs are
claimed with a compare-and-set.
"""
from __future__ import annotations

import logging
import signal
import time
from datetime import timedelta

from sqlalchemy import or_, update
from sqlmodel import Session, select

from app.agents.research import CandidateIn, ResearchContext, ResearchError, ResearchRunner, research_gap
from app.config import get_settings
from app.db import engine
from app import geocoding
from app.geocoding import Fetcher
from app.trash import purge_deleted_trips
from app.models import Candidate, Day, Gap, Lodging, Place, ResearchJob, Source, Trip, utcnow
from app.planning import ordered_day_plans

log = logging.getLogger("worker")
_running = True

STALE_AFTER = timedelta(minutes=15)
MAX_ATTEMPTS = 2
NEARBY_DAYS = 2

ACTIVITY_PLACE_KIND = {"meal": "food", "sight": "sight", "tour": "sight", "outdoors": "sight", "shopping": "shop"}


def _stop(*_args) -> None:
    global _running
    _running = False


def recover_stale_jobs(session: Session) -> None:
    """Requeue jobs left 'running' by a crashed worker, or fail them after MAX_ATTEMPTS."""
    cutoff = utcnow() - STALE_AFTER
    stale = session.exec(
        select(ResearchJob).where(
            ResearchJob.status == "running",
            or_(ResearchJob.started_at.is_(None), ResearchJob.started_at < cutoff),
        )
    ).all()
    for job in stale:
        if job.attempts >= MAX_ATTEMPTS:
            log.warning("job %s stuck after %d attempts; failing", job.id, job.attempts)
            _fail(session, job, "Finding options took too long. Try again.")
        else:
            log.warning("job %s stuck; requeueing", job.id)
            job.status = "queued"
            session.add(job)
            session.commit()


def claim_job(session: Session) -> ResearchJob | None:
    job = session.exec(
        select(ResearchJob)
        .where(ResearchJob.status == "queued")
        .order_by(ResearchJob.created_at)
        .limit(1)
    ).first()
    if job is None:
        return None
    # Compare-and-set so two workers never run the same job.
    result = session.exec(
        update(ResearchJob)
        .where(ResearchJob.id == job.id, ResearchJob.status == "queued")
        .values(status="running", started_at=utcnow(), attempts=job.attempts + 1)
    )
    session.commit()
    if result.rowcount != 1:
        return None
    session.refresh(job)
    return job


def build_context(session: Session, job: ResearchJob) -> ResearchContext:
    gap = session.get(Gap, job.gap_id)
    trip = session.get(Trip, job.trip_id)
    if gap is None or trip is None:
        raise ResearchError("This item no longer exists.")
    if trip.deleted_at is not None:
        raise ResearchError("This trip has been deleted.")
    if gap.status == "dismissed":
        raise ResearchError("This request was removed.")

    days = list(session.exec(select(Day).where(Day.trip_id == trip.id).order_by(Day.date)))
    places = {p.id: p.name for p in session.exec(select(Place).where(Place.trip_id == trip.id, Place.kind == "city"))}
    day = next((d for d in days if d.id == gap.day_id), None)

    nearby: list[str] = []
    if day is not None:
        i = days.index(day)
        for d in days[max(0, i - NEARBY_DAYS) : i + NEARBY_DAYS + 1]:
            city = places.get(d.base_place_id or "", "")
            nearby.append(f"{d.date:%a %b} {d.date.day}: {d.title}" + (f" ({city})" if city and city != d.title else ""))

    planned: list[str] = []
    stay: str | None = None
    if day is not None and gap.kind == "activity":
        planned = [
            a.name + (f" ({a.time_of_day})" if a.time_of_day else "")
            for a in ordered_day_plans(session, day.id)
        ]
        stay = _stay_description(session, trip.id, day)

    previous = list(session.exec(select(Candidate).where(Candidate.gap_id == gap.id)))
    return ResearchContext(
        trip_title=trip.title,
        destinations=list(trip.destinations or []),
        interests=list(trip.interests or []),
        travelers=trip.travelers,
        trip_start=trip.start_date,
        trip_end=trip.end_date,
        gap_kind=gap.kind,
        gap_prompt=gap.prompt,
        day_date=day.date if day else None,
        base_city=places.get(day.base_place_id or "") if day else None,
        nearby_days=nearby,
        nudge=job.nudge,
        time_of_day=gap.time_of_day,
        is_request=gap.origin == "request",
        planned_that_day=planned,
        stay=stay,
        already_suggested=[c.payload.get("name", "") for c in previous if c.status != "rejected" and c.payload.get("name")],
        rejected=[(c.payload.get("name", ""), c.rejection_reason) for c in previous if c.status == "rejected"],
    )


def _stay_description(session: Session, trip_id: str, day: Day) -> str | None:
    """The chosen stay for that night (or, on a departure day, the night before): name, area, address."""
    lodgings = session.exec(select(Lodging).where(Lodging.trip_id == trip_id)).all()
    stay = next((lodging for lodging in lodgings if lodging.check_in <= day.date < lodging.check_out), None)
    stay = stay or next((lodging for lodging in lodgings if lodging.check_out == day.date), None)
    if stay is None:
        return None
    place = session.get(Place, stay.place_id)
    if place is None:
        return None
    option = session.exec(select(Candidate).where(Candidate.place_id == place.id)).first()
    neighborhood = ((option.payload or {}).get("neighborhood") if option else None) or ""
    parts = [place.name, neighborhood, place.address]
    return ", ".join(p for p in parts if p)


def _place_kind(gap_kind: str, c: CandidateIn) -> str:
    if gap_kind == "lodging":
        return "lodging"
    return ACTIVITY_PLACE_KIND.get(c.activity_kind or "", "other")


def save_candidates(session: Session, job: ResearchJob, gap: Gap, candidates: list[CandidateIn]) -> list[tuple[Place, CandidateIn]]:
    now = utcnow()
    saved: list[tuple[Place, CandidateIn]] = []
    for c in candidates:
        place = Place(
            trip_id=job.trip_id,
            name=c.name,
            kind=_place_kind(gap.kind, c),
            lat=c.lat,
            lng=c.lng,
            precision="approximate" if c.lat is not None and c.lng is not None else "unknown",
            address=c.address or "",
            website_url=c.website_url or "",
            summary=c.summary,
        )
        session.add(place)
        session.flush()  # place before the candidate that references it
        saved.append((place, c))

        candidate = Candidate(
            trip_id=job.trip_id,
            gap_id=gap.id,
            target_kind=gap.kind if gap.kind in ("lodging", "transit", "activity") else "place",
            payload=c.model_dump(exclude={"sources", "pros", "cons", "summary", "confidence"}),
            place_id=place.id,
            summary=c.summary,
            pros=c.pros,
            cons=c.cons,
            confidence=c.confidence,
            created_by="agent",
        )
        session.add(candidate)
        session.flush()  # candidate before its sources

        for s in c.sources:
            session.add(Source(
                trip_id=job.trip_id,
                subject_kind="candidate",
                subject_id=candidate.id,
                title=s.title,
                url=s.url,
                note=s.note,
                fetched_at=now,
            ))
    return saved


def _fail(session: Session, job: ResearchJob, message: str) -> None:
    session.rollback()
    job = session.get(ResearchJob, job.id)
    job.status = "failed"
    job.error = message
    job.finished_at = utcnow()
    gap = session.get(Gap, job.gap_id)
    if gap is not None and gap.status == "researching":
        gap.status = "open"
        session.add(gap)
    session.add(job)
    session.commit()


def run_job(
    session: Session,
    job: ResearchJob,
    runner: ResearchRunner = research_gap,
    fetch: Fetcher | None = None,
) -> None:
    log.info("running job %s for gap %s (attempt %d)", job.id, job.gap_id, job.attempts)
    try:
        ctx = build_context(session, job)
        result = runner(ctx)
    except ResearchError as exc:
        _fail(session, job, str(exc))
        return

    gap = session.get(Gap, job.gap_id)
    job.input_tokens = result.usage.input_tokens
    job.output_tokens = result.usage.output_tokens
    job.search_count = result.usage.searches
    job.cost_usd = result.usage.cost_usd()

    if not result.candidates:
        job.status = "failed"
        job.error = "We couldn't find good options this time. Try again."
    else:
        save_candidates(session, job, gap, result.candidates)
        session.commit()  # keep options even if locating them fails
        geocoding.geocode_trip_places(
            job.trip_id,
            session_factory=lambda: Session(session.get_bind()),
            fetch=fetch or geocoding.default_fetcher(),
        )
        job.status = "done"
        job.error = ""
    job.finished_at = utcnow()
    if gap.status == "researching":
        gap.status = "open"  # open with options waiting to be reviewed
        session.add(gap)
    session.add(job)
    session.commit()
    log.info(
        "job %s %s: %d candidates, %d searches, ~$%.3f",
        job.id, job.status, len(result.candidates), job.search_count, job.cost_usd,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    poll = get_settings().worker_poll_seconds
    log.info("worker started, polling every %.1fs", poll)
    last_recovery = 0.0
    last_purge = 0.0
    while _running:
        with Session(engine) as session:
            if time.monotonic() - last_recovery > 60:
                recover_stale_jobs(session)
                last_recovery = time.monotonic()
            if time.monotonic() - last_purge > 3600:
                purged = purge_deleted_trips(session)
                if purged:
                    log.info("purged %d trip(s) from the trash", purged)
                last_purge = time.monotonic()
            job = claim_job(session)
            if job is None:
                time.sleep(poll)
                continue
            try:
                run_job(session, job)
            except Exception:  # noqa: BLE001
                log.exception("job %s crashed", job.id)
                _fail(session, job, "Something went wrong while finding options. Try again.")
    log.info("worker stopped")


if __name__ == "__main__":
    main()
