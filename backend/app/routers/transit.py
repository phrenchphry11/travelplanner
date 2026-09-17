"""A day's transit: manual-only in v1 (no research agent for travel legs)."""
from datetime import date, datetime, time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from app.auth import current_user
from app.db import get_session
from app.models import Day, Transit, TripMember, User
from app.planning import clean_link, trip_is_deleted
from app.routers.plans import _member_day

router = APIRouter(tags=["transit"])

TransitMethod = Literal["train", "flight", "drive", "bus", "ferry", "walk", "taxi", "other"]


def _member_transit(session: Session, transit_id: str, user: User) -> Transit:
    leg = session.get(Transit, transit_id)
    if leg is None or session.get(TripMember, (leg.trip_id, user.id)) is None or trip_is_deleted(session, leg.trip_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return leg


def _parse_time(value: str | None, on: date) -> datetime | None:
    """'10:47' on 2027-05-04 -> that datetime. Blank/None -> None."""
    if not value:
        return None
    try:
        h, m = value.split(":")
        return datetime.combine(on, time(int(h), int(m)))
    except ValueError as exc:
        raise ValueError("Times look like HH:MM, e.g. 10:47.") from exc


def _format_time(value: datetime | None) -> str:
    return value.strftime("%H:%M") if value else ""


class TransitOut(BaseModel):
    id: str
    day_id: str
    name: str
    method: TransitMethod
    depart_time: str  # "HH:MM" or ""
    arrive_time: str
    link: str
    confirmation_code: str
    notes: str


def _out(leg: Transit) -> TransitOut:
    return TransitOut(
        id=leg.id, day_id=leg.day_id, name=leg.name, method=leg.method,
        depart_time=_format_time(leg.depart_at), arrive_time=_format_time(leg.arrive_at),
        link=leg.booking_url, confirmation_code=leg.confirmation_code, notes=leg.notes,
    )


class TransitIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    method: TransitMethod = "other"
    depart_time: str = Field(default="", max_length=5)
    arrive_time: str = Field(default="", max_length=5)
    link: str = Field(default="", max_length=1000)
    confirmation_code: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Give this leg a name, e.g. 'Bordeaux to Paris'.")
        return v

    @field_validator("confirmation_code", "notes")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("link")
    @classmethod
    def _link(cls, v: str) -> str:
        return clean_link(v)


@router.post("/days/{day_id}/transit", response_model=TransitOut, status_code=status.HTTP_201_CREATED)
def add_transit(
    day_id: str,
    body: TransitIn,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> TransitOut:
    """Add a travel leg the traveler already knows about, e.g. a train or flight."""
    day = _member_day(session, day_id, user)
    try:
        depart_at = _parse_time(body.depart_time, day.date)
        arrive_at = _parse_time(body.arrive_time, day.date)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    leg = Transit(
        trip_id=day.trip_id, day_id=day.id, name=body.name, method=body.method,
        depart_at=depart_at, arrive_at=arrive_at, booking_url=body.link,
        confirmation_code=body.confirmation_code, status="planned", notes=body.notes,
    )
    session.add(leg)
    session.commit()
    session.refresh(leg)
    return _out(leg)


class TransitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    method: TransitMethod | None = None
    depart_time: str | None = Field(default=None, max_length=5)
    arrive_time: str | None = Field(default=None, max_length=5)
    link: str | None = Field(default=None, max_length=1000)
    confirmation_code: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Give this leg a name.")
        return v

    @field_validator("confirmation_code", "notes")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return None if v is None else v.strip()

    @field_validator("link")
    @classmethod
    def _link(cls, v: str | None) -> str | None:
        return None if v is None else clean_link(v)


@router.patch("/transit/{transit_id}", response_model=TransitOut)
def edit_transit(
    transit_id: str,
    body: TransitUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> TransitOut:
    leg = _member_transit(session, transit_id, user)
    # Days are created once at intake and never individually removed, so this always exists.
    day_date = session.get(Day, leg.day_id).date

    if body.name is not None:
        leg.name = body.name
    if body.method is not None:
        leg.method = body.method
    if body.link is not None:
        leg.booking_url = body.link
    if body.confirmation_code is not None:
        leg.confirmation_code = body.confirmation_code
    if body.notes is not None:
        leg.notes = body.notes
    try:
        if body.depart_time is not None:
            leg.depart_at = _parse_time(body.depart_time, day_date)
        if body.arrive_time is not None:
            leg.arrive_at = _parse_time(body.arrive_time, day_date)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    session.add(leg)
    session.commit()
    session.refresh(leg)
    return _out(leg)


@router.delete("/transit/{transit_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_transit(
    transit_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> None:
    leg = _member_transit(session, transit_id, user)
    session.delete(leg)
    session.commit()
