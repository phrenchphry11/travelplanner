"""A day's plans: ask for ideas, add one yourself, edit, reorder, and remove."""
import re
from collections.abc import Callable
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from app.auth import current_user
from app.db import get_session
from app.geocoding import get_trip_locator
from app.models import Activity, Candidate, Day, Gap, Lodging, Place, ResearchJob, Transit, TripMember, User
from app.planning import OPEN_GAP_STATUSES, next_sort_order, ordered_day_plans, time_rank
from app.routers.choices import undo_choice

router = APIRouter(tags=["plans"])

TimeOfDay = Literal["", "morning", "afternoon", "evening"]
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:(?!\d)")  # "mailto:" but not "example.com:8080"


def _member_day(session: Session, day_id: str, user: User) -> Day:
    day = session.get(Day, day_id)
    if day is None or session.get(TripMember, (day.trip_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return day


def _member_activity(session: Session, activity_id: str, user: User) -> Activity:
    activity = session.get(Activity, activity_id)
    if activity is None or session.get(TripMember, (activity.trip_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return activity


def _clean_link(value: str) -> str:
    """'example.com/tour' -> 'https://example.com/tour'. Only web links are kept."""
    value = value.strip()
    if not value:
        return ""
    if _SCHEME.match(value) and not value.lower().startswith(("http://", "https://")):
        raise ValueError("That link doesn't look like a web address.")  # mailto:, javascript:, ftp://
    if "://" not in value:
        value = f"https://{value}"
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc or " " in value:
        raise ValueError("That link doesn't look like a web address.")
    return value


# ---- Find ideas -------------------------------------------------------------

class PlanRequestIn(BaseModel):
    request: str = Field(min_length=1, max_length=300)
    time_of_day: TimeOfDay = ""

    @field_validator("request")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Tell us what you're looking for.")
        return v[0].upper() + v[1:]


class PlanRequestOut(BaseModel):
    gap_id: str
    job_id: str


@router.post("/days/{day_id}/plan-requests", response_model=PlanRequestOut, status_code=status.HTTP_202_ACCEPTED)
def request_ideas(
    day_id: str,
    body: PlanRequestIn,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> PlanRequestOut:
    """Ask for ideas for this day. Starts research right away: only call from a "Find ideas" button."""
    day = _member_day(session, day_id, user)
    gap = Gap(
        trip_id=day.trip_id,
        day_id=day.id,
        kind="activity",
        origin="request",
        prompt=body.request,
        time_of_day=body.time_of_day,
        status="researching",
    )
    session.add(gap)
    session.flush()  # gap before its job
    job = ResearchJob(trip_id=day.trip_id, gap_id=gap.id)
    session.add(job)
    session.commit()
    return PlanRequestOut(gap_id=gap.id, job_id=job.id)


@router.post("/gaps/{gap_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_request(
    gap_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> None:
    """Drop a "Find ideas" request nobody picked from. Starter gaps can't be dismissed."""
    gap = session.get(Gap, gap_id)
    if gap is None or session.get(TripMember, (gap.trip_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if gap.origin != "request" or gap.status not in OPEN_GAP_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "This can't be removed.")
    gap.status = "dismissed"
    session.add(gap)
    session.commit()


# ---- Plans ------------------------------------------------------------------

class PlanOut(BaseModel):
    id: str
    day_id: str
    name: str
    time_of_day: str
    notes: str
    link: str
    place_id: str | None
    sort_order: int


def _plan_out(a: Activity) -> PlanOut:
    return PlanOut(
        id=a.id, day_id=a.day_id, name=a.name, time_of_day=a.time_of_day, notes=a.notes,
        link=a.booking_url, place_id=a.place_id, sort_order=a.sort_order,
    )


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    time_of_day: TimeOfDay = ""
    address: str = Field(default="", max_length=300)
    link: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Give your plan a name.")
        return v

    @field_validator("address", "notes")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("link")
    @classmethod
    def _link(cls, v: str) -> str:
        return _clean_link(v)


@router.post("/days/{day_id}/plans", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
def add_plan(
    day_id: str,
    body: PlanIn,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    locate: Callable[[str], None] = Depends(get_trip_locator),
) -> PlanOut:
    """Add a plan the traveler already knows about. Its map pin is found afterwards, if we can."""
    day = _member_day(session, day_id, user)
    place = Place(trip_id=day.trip_id, name=body.name, kind="other", address=body.address)
    session.add(place)
    session.flush()  # place before the plan that references it
    activity = Activity(
        trip_id=day.trip_id,
        day_id=day.id,
        name=body.name,
        place_id=place.id,
        time_of_day=body.time_of_day,
        booking_url=body.link,
        status="planned",
        notes=body.notes,
        sort_order=next_sort_order(session, day.id),
    )
    session.add(activity)
    session.commit()
    session.refresh(activity)
    background.add_task(locate, day.trip_id)
    return _plan_out(activity)


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    time_of_day: TimeOfDay | None = None
    notes: str | None = Field(default=None, max_length=2000)
    link: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Give your plan a name.")
        return v

    @field_validator("link")
    @classmethod
    def _link(cls, v: str | None) -> str | None:
        return None if v is None else _clean_link(v)


def _is_own_place(session: Session, place_id: str, activity_id: str) -> bool:
    """A place made just for this plan: no research option, stay, day, or other plan uses it."""
    if session.exec(select(Candidate.id).where(Candidate.place_id == place_id)).first():
        return False
    if session.exec(select(Activity.id).where(Activity.place_id == place_id, Activity.id != activity_id)).first():
        return False
    if session.exec(select(Lodging.id).where(Lodging.place_id == place_id)).first():
        return False
    if session.exec(select(Day.id).where(Day.base_place_id == place_id)).first():
        return False
    if session.exec(
        select(Transit.id).where((Transit.from_place_id == place_id) | (Transit.to_place_id == place_id))
    ).first():
        return False
    return True


@router.patch("/activities/{activity_id}", response_model=PlanOut)
def update_plan(
    activity_id: str,
    body: PlanUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> PlanOut:
    activity = _member_activity(session, activity_id, user)
    if body.name is not None and body.name != activity.name:
        activity.name = body.name
        if activity.place_id and _is_own_place(session, activity.place_id, activity.id):
            place = session.get(Place, activity.place_id)
            place.name = body.name
            session.add(place)
    if body.time_of_day is not None and body.time_of_day != activity.time_of_day:
        activity.time_of_day = body.time_of_day
        activity.sort_order = next_sort_order(session, activity.day_id)  # last in its new part of the day
    if body.notes is not None:
        activity.notes = body.notes.strip()
    if body.link is not None:
        activity.booking_url = body.link
    session.add(activity)
    session.commit()
    session.refresh(activity)
    return _plan_out(activity)


class MoveIn(BaseModel):
    direction: Literal["up", "down"]


@router.post("/activities/{activity_id}/move", response_model=list[PlanOut])
def move_plan(
    activity_id: str,
    body: MoveIn,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[PlanOut]:
    """Swap a plan with its neighbor in the same part of the day. Returns the day's plans in order."""
    activity = _member_activity(session, activity_id, user)
    plans = ordered_day_plans(session, activity.day_id)
    i = next(i for i, a in enumerate(plans) if a.id == activity.id)
    j = i - 1 if body.direction == "up" else i + 1
    if j < 0 or j >= len(plans) or time_rank(plans[j].time_of_day) != time_rank(activity.time_of_day):
        raise HTTPException(status.HTTP_409_CONFLICT, "It can't move further. Change its time of day instead.")
    plans[i], plans[j] = plans[j], plans[i]
    for n, a in enumerate(plans):
        if a.sort_order != n:
            a.sort_order = n
            session.add(a)
    session.commit()
    return [_plan_out(a) for a in ordered_day_plans(session, activity.day_id)]


class RemoveOut(BaseModel):
    removed: Literal["deleted", "reopened"]
    gap_id: str | None  # the reopened gap, whose options are back


@router.delete("/activities/{activity_id}", response_model=RemoveOut)
def remove_plan(
    activity_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> RemoveOut:
    """Remove a plan. One chosen from research options reopens its gap, so the options come back."""
    activity = _member_activity(session, activity_id, user)
    gap = session.exec(
        select(Gap).where(
            Gap.trip_id == activity.trip_id,
            Gap.resolved_by_kind == "activity",
            Gap.resolved_by_id == activity.id,
            Gap.status == "answered",
        )
    ).first()
    if gap is not None:
        undo_choice(session, gap)
        session.commit()
        return RemoveOut(removed="reopened", gap_id=gap.id)

    place_id = activity.place_id
    own_place = bool(place_id) and _is_own_place(session, place_id, activity.id)
    session.delete(activity)
    session.flush()  # the plan before its place
    if own_place:
        place = session.get(Place, place_id)
        if place is not None:
            session.delete(place)
    session.commit()
    return RemoveOut(removed="deleted", gap_id=None)
