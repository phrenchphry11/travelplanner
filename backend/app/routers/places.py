"""Saved places: a trip-wide list of spots the traveler wants on the map, not tied to any day."""
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session

from app.auth import current_user
from app.db import get_session
from app.geocoding import get_trip_locator
from app.models import Place, TripMember, User
from app.planning import clean_link
from app.routers.trips import get_member_trip

router = APIRouter(tags=["places"])

SavedPlaceKind = Literal["coffee", "food", "sight", "shop", "other"]


def _member_place(session: Session, place_id: str, user: User) -> Place:
    place = session.get(Place, place_id)
    if place is None or not place.saved or session.get(TripMember, (place.trip_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return place


class SavedPlaceOut(BaseModel):
    id: str
    name: str
    kind: SavedPlaceKind
    address: str
    link: str
    notes: str


def _out(place: Place) -> SavedPlaceOut:
    return SavedPlaceOut(id=place.id, name=place.name, kind=place.kind, address=place.address, link=place.website_url, notes=place.notes)


class SavedPlaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: SavedPlaceKind = "other"
    address: str = Field(default="", max_length=300)
    link: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Give it a name.")
        return v

    @field_validator("address", "notes")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("link")
    @classmethod
    def _link(cls, v: str) -> str:
        return clean_link(v)


@router.post("/trips/{trip_id}/places", response_model=SavedPlaceOut, status_code=status.HTTP_201_CREATED)
def add_saved_place(
    trip_id: str,
    body: SavedPlaceIn,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    locate: Callable[[str], None] = Depends(get_trip_locator),
) -> SavedPlaceOut:
    """Save a spot for the map: a coffee shop, park, or anything else not tied to a day."""
    trip = get_member_trip(session, trip_id, user)
    place = Place(
        trip_id=trip.id, name=body.name, kind=body.kind, address=body.address,
        website_url=body.link, notes=body.notes, saved=True,
    )
    session.add(place)
    session.commit()
    session.refresh(place)
    background.add_task(locate, trip.id)
    return _out(place)


class SavedPlaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: SavedPlaceKind | None = None
    address: str | None = Field(default=None, max_length=300)
    link: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Give it a name.")
        return v

    @field_validator("address", "notes")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return None if v is None else v.strip()

    @field_validator("link")
    @classmethod
    def _link(cls, v: str | None) -> str | None:
        return None if v is None else clean_link(v)


@router.patch("/places/{place_id}", response_model=SavedPlaceOut)
def edit_saved_place(
    place_id: str,
    body: SavedPlaceUpdate,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    locate: Callable[[str], None] = Depends(get_trip_locator),
) -> SavedPlaceOut:
    place = _member_place(session, place_id, user)
    if body.name is not None:
        place.name = body.name
    if body.kind is not None:
        place.kind = body.kind
    if body.link is not None:
        place.website_url = body.link
    if body.notes is not None:
        place.notes = body.notes
    address_changed = body.address is not None and body.address != place.address
    if body.address is not None:
        place.address = body.address
    if address_changed:
        # A new address needs a fresh lookup; drop the old pin and let it retry.
        place.lat, place.lng, place.precision, place.geocoded_at = None, None, "unknown", None
    session.add(place)
    session.commit()
    session.refresh(place)
    if address_changed:
        background.add_task(locate, place.trip_id)
    return _out(place)


@router.delete("/places/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_saved_place(
    place_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> None:
    place = _member_place(session, place_id, user)
    session.delete(place)
    session.commit()
