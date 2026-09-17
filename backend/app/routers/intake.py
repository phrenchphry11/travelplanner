from datetime import date, timedelta

from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlmodel import Session, select

from app.agents.intake import (
    MAX_DAYS,
    ChatMessage,
    IntakeError,
    IntakeRunner,
    TripDraft,
    get_intake_runner,
)
from app.auth import current_user
from app.db import get_session
from app.geocoding import get_trip_locator
from app.models import Day, Gap, IntakeSession, Place, Trip, TripMember, User, utcnow
from app.routers.trips import TripOut, to_trip_out
from app.trash import INTAKE_SESSION_EXPIRY

router = APIRouter(prefix="/intake", tags=["intake"])


class IntakeTurnRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    current_draft: TripDraft | None = None
    session_id: str | None = None

    @model_validator(mode="after")
    def _check_roles(self) -> "IntakeTurnRequest":
        if self.messages[0].role != "user" or self.messages[-1].role != "user":
            raise ValueError("Conversation must start and end with the traveler")
        for prev, cur in zip(self.messages, self.messages[1:]):
            if prev.role == cur.role:
                raise ValueError("Messages must alternate between traveler and assistant")
        return self


class IntakeTurnResponse(BaseModel):
    reply: str
    kind: str
    draft: TripDraft | None
    session_id: str


def _own_open_session(session: Session, user: User, session_id: str | None) -> IntakeSession | None:
    """The caller's session_id, if it's real, theirs, and not already linked to a trip."""
    if session_id is None:
        return None
    s = session.get(IntakeSession, session_id)
    if s is None or s.user_id != user.id or s.trip_id is not None:
        return None
    return s


@router.post("/turn", response_model=IntakeTurnResponse)
def intake_turn(
    body: IntakeTurnRequest,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    runner: IntakeRunner = Depends(get_intake_runner),
) -> IntakeTurnResponse:
    try:
        turn = runner(body.messages, body.current_draft, date.today())
    except IntakeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    messages = [m.model_dump() for m in body.messages] + [
        {"role": "assistant", "content": turn.reply, "kind": turn.kind}
    ]
    draft = turn.draft.model_dump() if turn.draft else (body.current_draft.model_dump() if body.current_draft else None)
    record = _own_open_session(session, user, body.session_id)
    if record is None:
        record = IntakeSession(user_id=user.id, messages=messages, current_draft=draft)
    else:
        record.messages = messages
        record.current_draft = draft
        record.updated_at = utcnow()
    session.add(record)
    session.commit()
    session.refresh(record)
    return IntakeTurnResponse(reply=turn.reply, kind=turn.kind, draft=turn.draft, session_id=record.id)


class IntakeSessionOut(BaseModel):
    id: str
    messages: list[ChatMessage]
    current_draft: TripDraft | None


@router.get("/session", response_model=IntakeSessionOut | None)
def latest_session(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> IntakeSessionOut | None:
    """The traveler's most recent unfinished intake chat, if any, to resume after a refresh."""
    cutoff = utcnow() - INTAKE_SESSION_EXPIRY
    record = session.exec(
        select(IntakeSession)
        .where(IntakeSession.user_id == user.id, IntakeSession.trip_id.is_(None), IntakeSession.updated_at > cutoff)
        .order_by(IntakeSession.updated_at.desc())
    ).first()
    if record is None:
        return None
    return IntakeSessionOut(id=record.id, messages=record.messages, current_draft=record.current_draft)


@router.delete("/session/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard_session(
    session_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> None:
    record = _own_open_session(session, user, session_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    session.delete(record)
    session.commit()


class ConfirmDay(BaseModel):
    base_city: str = Field(min_length=1, max_length=120)
    title: str = Field(default="", max_length=200)
    summary: str = Field(default="", max_length=1000)


class ConfirmDraft(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start_date: date
    travelers: int | None = Field(default=None, ge=1, le=50)
    destinations: list[str] = Field(default_factory=list, max_length=20)
    interests: list[str] = Field(default_factory=list, max_length=20)
    days: list[ConfirmDay] = Field(min_length=1, max_length=MAX_DAYS)
    session_id: str | None = None

    @model_validator(mode="after")
    def _strip(self) -> "ConfirmDraft":
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("Title can't be blank")
        for d in self.days:
            d.base_city = d.base_city.strip()
            d.title = d.title.strip()
            if not d.base_city:
                raise ValueError("Every day needs a place")
        return self


def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}"


def _date_range(start: date, end: date) -> str:
    if start == end:
        return _fmt(start)
    if start.month == end.month:
        return f"{_fmt(start)}–{end.day}"
    return f"{_fmt(start)}–{_fmt(end)}"


@router.post("/confirm", response_model=TripOut, status_code=status.HTTP_201_CREATED)
def confirm_draft(
    body: ConfirmDraft,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    locate: Callable[[str], None] = Depends(get_trip_locator),
) -> TripOut:
    days_count = len(body.days)
    end_date = body.start_date + timedelta(days=days_count - 1)
    trip = Trip(
        owner_id=user.id,
        title=body.title,
        start_date=body.start_date,
        end_date=end_date,
        travelers=body.travelers,
        destinations=[d.strip() for d in body.destinations if d.strip()],
        interests=[i.strip() for i in body.interests if i.strip()],
        status="planning",
    )
    # No ORM relationships are declared, so SQLAlchemy won't order inserts by
    # foreign key. Flush each level before adding rows that reference it.
    session.add(trip)
    session.flush()
    session.add(TripMember(trip_id=trip.id, user_id=user.id, role="owner"))

    places: dict[str, Place] = {}
    days: list[Day] = []
    for i, d in enumerate(body.days):
        key = d.base_city.casefold()
        if key not in places:
            places[key] = Place(trip_id=trip.id, name=d.base_city, kind="city")
            session.add(places[key])
        session.flush()  # the day's place must exist before the day
        day = Day(
            trip_id=trip.id,
            date=body.start_date + timedelta(days=i),
            title=d.title or d.base_city,
            summary=d.summary,
            base_place_id=places[key].id,
        )
        days.append(day)
        session.add(day)

    session.flush()  # days before the gaps that reference them
    gaps: list[Gap] = []
    # One lodging gap per consecutive stay. The last day of the trip is assumed
    # to be a departure day with no night to book.
    i = 0
    while i < days_count:
        j = i
        while j + 1 < days_count and body.days[j + 1].base_city.casefold() == body.days[i].base_city.casefold():
            j += 1
        last_night = min(j, days_count - 2)
        if last_night >= i:
            city = body.days[i].base_city
            nights = last_night - i + 1
            gaps.append(Gap(
                trip_id=trip.id,
                day_id=days[i].id,
                kind="lodging",
                prompt=f"Where to stay in {city} ({_date_range(days[i].date, days[last_night].date)}, "
                       f"{nights} night{'s' if nights != 1 else ''})",
            ))
        i = j + 1
    for day, d in zip(days, body.days):
        gaps.append(Gap(
            trip_id=trip.id,
            day_id=day.id,
            kind="activity",
            prompt=f"What to do in {d.base_city} on {_fmt(day.date)}",
        ))
    session.add_all(gaps)
    record = _own_open_session(session, user, body.session_id)
    if record is not None:
        record.trip_id = trip.id
        session.add(record)
    session.commit()
    session.refresh(trip)
    background.add_task(locate, trip.id)
    return to_trip_out(trip, user.id, open_gap_count=len(gaps))
