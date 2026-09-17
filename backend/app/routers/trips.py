from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlmodel import Session, select

from app.auth import current_user
from app.db import get_session
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
    User,
)
from app.planning import OPEN_GAP_STATUSES, counts_as_missing, days_with_plans

router = APIRouter(prefix="/trips", tags=["trips"])

TRIP_STATUSES = ("dreaming", "planning", "booked", "done")


class TripCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> "TripCreate":
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("Title can't be blank")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("End date must be on or after the start date")
        return self


class TripOut(BaseModel):
    id: str
    title: str
    start_date: date | None
    end_date: date | None
    status: str
    open_gap_count: int = 0
    share_slug: str | None = None  # set while the trip is published


def to_trip_out(trip: Trip, open_gap_count: int = 0) -> TripOut:
    return TripOut(
        id=trip.id,
        title=trip.title,
        start_date=trip.start_date,
        end_date=trip.end_date,
        status=trip.status,
        open_gap_count=open_gap_count,
        share_slug=trip.share_slug,
    )


def get_member_trip(session: Session, trip_id: str, user: User) -> Trip:
    """Return the trip if the user is a member, else 404 (never leak existence)."""
    member = session.get(TripMember, (trip_id, user.id))
    trip = session.get(Trip, trip_id) if member else None
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    return trip


def _open_gap_counts(session: Session, trip_ids: list[str]) -> dict[str, int]:
    """Things still missing per trip (see planning.counts_as_missing)."""
    if not trip_ids:
        return {}
    planned = days_with_plans(session, trip_ids)
    counts: dict[str, int] = {}
    for gap in session.exec(select(Gap).where(Gap.trip_id.in_(trip_ids), Gap.status.in_(OPEN_GAP_STATUSES))):
        if counts_as_missing(gap, planned):
            counts[gap.trip_id] = counts.get(gap.trip_id, 0) + 1
    return counts


@router.get("", response_model=list[TripOut])
def list_trips(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[TripOut]:
    trips = list(
        session.exec(
            select(Trip)
            .join(TripMember, TripMember.trip_id == Trip.id)
            .where(TripMember.user_id == user.id)
            .order_by(Trip.created_at.desc())
        )
    )
    counts = _open_gap_counts(session, [t.id for t in trips])
    return [to_trip_out(t, counts.get(t.id, 0)) for t in trips]


@router.post("", response_model=TripOut, status_code=status.HTTP_201_CREATED)
def create_trip(
    body: TripCreate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> TripOut:
    trip = Trip(owner_id=user.id, **body.model_dump())
    # No ORM relationships are declared, so SQLAlchemy won't order inserts by
    # foreign key. Flush parents before children.
    session.add(trip)
    session.flush()
    session.add(TripMember(trip_id=trip.id, user_id=user.id, role="owner"))
    session.commit()
    session.refresh(trip)
    return to_trip_out(trip)


@router.get("/{trip_id}", response_model=TripOut)
def get_trip(
    trip_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> TripOut:
    trip = get_member_trip(session, trip_id, user)
    return to_trip_out(trip, _open_gap_counts(session, [trip.id]).get(trip.id, 0))


@router.delete("/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trip(
    trip_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> None:
    trip = get_member_trip(session, trip_id, user)
    if trip.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can delete a trip")
    # Children before parents, flushing each table so deletes run in this order.
    for model in (ResearchJob, Source, Candidate, Gap, Activity, Transit, Lodging, Day, Place, TripMember):
        for row in session.exec(select(model).where(model.trip_id == trip.id)):
            session.delete(row)
        session.flush()
    session.delete(trip)
    session.commit()


class DayOut(BaseModel):
    id: str
    date: date
    title: str
    summary: str
    base_city: str | None
    open_gap_count: int


@router.get("/{trip_id}/days", response_model=list[DayOut])
def list_days(
    trip_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[DayOut]:
    trip = get_member_trip(session, trip_id, user)
    days = session.exec(select(Day).where(Day.trip_id == trip.id).order_by(Day.date)).all()
    places = {p.id: p.name for p in session.exec(select(Place).where(Place.trip_id == trip.id))}
    planned = days_with_plans(session, [trip.id])
    gap_counts: dict[str | None, int] = {}
    for gap in session.exec(select(Gap).where(Gap.trip_id == trip.id, Gap.status.in_(OPEN_GAP_STATUSES))):
        if counts_as_missing(gap, planned):
            gap_counts[gap.day_id] = gap_counts.get(gap.day_id, 0) + 1
    return [
        DayOut(
            id=d.id,
            date=d.date,
            title=d.title,
            summary=d.summary,
            base_city=places.get(d.base_place_id) if d.base_place_id else None,
            open_gap_count=gap_counts.get(d.id, 0),
        )
        for d in days
    ]
