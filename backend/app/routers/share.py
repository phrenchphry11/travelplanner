"""Share links: owners publish a read-only itinerary at an unguessable slug.

The slug is the only protection (PRD 5.6), so the public payload is built
from an allow-list of fields. It never includes ids, prices, confirmation
codes, gaps, candidates, sources, research jobs, or anything about members.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import current_user
from app.db import get_session
from app.models import Activity, Day, Lodging, Place, Trip, User, new_share_slug, utcnow
from app.planning import plan_order_key
from app.routers.trips import get_member_trip

router = APIRouter(tags=["share"])

NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}
# Unpublishing should take effect right away, so nothing may cache the payload.
PUBLIC_HEADERS = {**NOINDEX, "Cache-Control": "no-store"}


# --- Owner management -------------------------------------------------------


class ShareState(BaseModel):
    share_slug: str | None


def _owned_trip(session: Session, trip_id: str, user: User) -> Trip:
    """Only the trip owner may publish. Non-members get 404, other members 403."""
    trip = get_member_trip(session, trip_id, user)
    if trip.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the trip's owner can change sharing")
    return trip


def _set_slug(session: Session, trip: Trip, slug: str | None) -> ShareState:
    trip.share_slug = slug
    trip.updated_at = utcnow()
    session.add(trip)
    session.commit()
    return ShareState(share_slug=slug)


@router.post("/trips/{trip_id}/share", response_model=ShareState)
def publish(trip_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)) -> ShareState:
    """Publish the trip. Idempotent: an already-published trip keeps its link."""
    trip = _owned_trip(session, trip_id, user)
    if trip.share_slug:
        return ShareState(share_slug=trip.share_slug)
    return _set_slug(session, trip, new_share_slug())


@router.post("/trips/{trip_id}/share/regenerate", response_model=ShareState)
def regenerate(trip_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)) -> ShareState:
    """Replace the link; the old one stops working. Publishes if not already published."""
    trip = _owned_trip(session, trip_id, user)
    return _set_slug(session, trip, new_share_slug())


@router.delete("/trips/{trip_id}/share", response_model=ShareState)
def unpublish(trip_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)) -> ShareState:
    trip = _owned_trip(session, trip_id, user)
    return _set_slug(session, trip, None)


# --- Public payload ---------------------------------------------------------


class PublicPlace(BaseModel):
    name: str
    address: str
    lat: float | None  # null when the place isn't pinned on the map
    lng: float | None


class PublicStay(BaseModel):
    place: PublicPlace
    check_in: date
    check_out: date
    nights: int
    booking_url: str
    website_url: str


class PublicPlan(BaseModel):
    name: str
    time: str  # "morning" | "afternoon" | "evening" | "" (any time)
    place: PublicPlace | None
    booking_url: str
    website_url: str
    notes: str  # a short description of the plan


class PublicDay(BaseModel):
    date: date
    title: str
    summary: str
    city: PublicPlace | None
    plans: list[PublicPlan]  # morning, afternoon, evening, then anything else


class PublicTrip(BaseModel):
    title: str
    start_date: date | None
    end_date: date | None
    days: list[PublicDay]
    stays: list[PublicStay]  # a day's stay is the one with check_in <= date < check_out


def _place(p: Place | None) -> PublicPlace | None:
    if p is None:
        return None
    pinned = p.lat is not None and p.lng is not None
    return PublicPlace(name=p.name, address=p.address, lat=p.lat if pinned else None, lng=p.lng if pinned else None)


def build_public_trip(session: Session, trip: Trip) -> PublicTrip:
    places = {p.id: p for p in session.exec(select(Place).where(Place.trip_id == trip.id))}
    days = list(session.exec(select(Day).where(Day.trip_id == trip.id).order_by(Day.date)))
    stays = list(session.exec(select(Lodging).where(Lodging.trip_id == trip.id).order_by(Lodging.check_in)))
    plans_by_day: dict[str, list[Activity]] = {}
    for a in session.exec(select(Activity).where(Activity.trip_id == trip.id)):
        plans_by_day.setdefault(a.day_id, []).append(a)

    def website(place_id: str | None) -> str:
        p = places.get(place_id) if place_id else None
        return p.website_url if p else ""

    return PublicTrip(
        title=trip.title,
        start_date=trip.start_date,
        end_date=trip.end_date,
        days=[
            PublicDay(
                date=d.date,
                title=d.title,
                summary=d.summary,
                city=_place(places.get(d.base_place_id)) if d.base_place_id else None,
                plans=[
                    PublicPlan(
                        name=a.name,
                        time=a.time_of_day,
                        place=_place(places.get(a.place_id)) if a.place_id else None,
                        booking_url=a.booking_url,
                        website_url=website(a.place_id),
                        notes=a.notes,
                    )
                    for a in sorted(plans_by_day.get(d.id, []), key=plan_order_key)
                ],
            )
            for d in days
        ],
        stays=[
            PublicStay(
                place=_place(places.get(s.place_id)) or PublicPlace(name="Stay", address="", lat=None, lng=None),
                check_in=s.check_in,
                check_out=s.check_out,
                nights=(s.check_out - s.check_in).days,
                booking_url=s.booking_url,
                website_url=website(s.place_id),
            )
            for s in stays
        ],
    )


# No auth dependency on purpose: anyone with the link can read it.
@router.get("/share/{slug}", response_model=PublicTrip)
def get_shared_trip(slug: str, response: Response, session: Session = Depends(get_session)) -> PublicTrip:
    trip = session.exec(select(Trip).where(Trip.share_slug == slug)).first() if 0 < len(slug) <= 64 else None
    if trip is None:
        # Same answer for unknown, unpublished, and regenerated-away links.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link isn't working. Ask whoever sent it for a new one.", headers=PUBLIC_HEADERS)
    response.headers.update(PUBLIC_HEADERS)
    return build_public_trip(session, trip)
