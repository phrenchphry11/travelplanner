from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import current_user
from app.db import get_session
from app.models import Trip, TripMember, User

router = APIRouter(prefix="/trips", tags=["trips"])


class TripCreate(BaseModel):
    title: str
    start_date: date | None = None
    end_date: date | None = None


class TripOut(BaseModel):
    id: str
    title: str
    start_date: date | None
    end_date: date | None
    status: str
    share_slug: str | None


@router.get("", response_model=list[TripOut])
def list_trips(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[Trip]:
    stmt = (
        select(Trip)
        .join(TripMember, TripMember.trip_id == Trip.id)
        .where(TripMember.user_id == user.id)
        .order_by(Trip.created_at.desc())
    )
    return list(session.exec(stmt))


@router.post("", response_model=TripOut, status_code=status.HTTP_201_CREATED)
def create_trip(
    body: TripCreate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Trip:
    trip = Trip(owner_id=user.id, **body.model_dump())
    session.add(trip)
    session.add(TripMember(trip_id=trip.id, user_id=user.id, role="owner"))
    session.commit()
    session.refresh(trip)
    return trip


@router.get("/{trip_id}", response_model=TripOut)
def get_trip(
    trip_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> Trip:
    member = session.get(TripMember, (trip_id, user.id))
    trip = session.get(Trip, trip_id) if member else None
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    return trip
