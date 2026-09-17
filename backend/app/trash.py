"""Deleted trips: soft-delete leaves a trip recoverable; purge removes it for good."""
from datetime import timedelta

from sqlmodel import Session, select

from app.models import (
    Activity,
    Candidate,
    Day,
    Gap,
    Lodging,
    Place,
    ResearchJob,
    Source,
    Transit,
    Trip,
    TripMember,
    utcnow,
)

PURGE_AFTER = timedelta(days=30)

# Children before parents; each table is flushed before the next one is deleted.
_CHILD_MODELS = (ResearchJob, Source, Candidate, Gap, Activity, Transit, Lodging, Day, Place, TripMember)


def hard_delete_trip(session: Session, trip: Trip) -> None:
    """Permanently remove a trip and everything in it. Caller commits."""
    for model in _CHILD_MODELS:
        for row in session.exec(select(model).where(model.trip_id == trip.id)):
            session.delete(row)
        session.flush()
    session.delete(trip)


def purge_deleted_trips(session: Session, older_than: timedelta = PURGE_AFTER) -> int:
    """Permanently remove trips that have been in the trash long enough. Returns how many."""
    cutoff = utcnow() - older_than
    trips = session.exec(select(Trip).where(Trip.deleted_at.is_not(None), Trip.deleted_at <= cutoff)).all()
    for trip in trips:
        hard_delete_trip(session, trip)
        session.commit()
    return len(trips)
