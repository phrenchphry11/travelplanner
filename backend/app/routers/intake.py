from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlmodel import Session

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
from app.models import Day, Gap, Place, Trip, TripMember, User
from app.routers.trips import TripOut, to_trip_out

router = APIRouter(prefix="/intake", tags=["intake"])


class IntakeTurnRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    current_draft: TripDraft | None = None

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


@router.post("/turn", response_model=IntakeTurnResponse)
def intake_turn(
    body: IntakeTurnRequest,
    _user: User = Depends(current_user),
    runner: IntakeRunner = Depends(get_intake_runner),
) -> IntakeTurnResponse:
    try:
        turn = runner(body.messages, body.current_draft, date.today())
    except IntakeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return IntakeTurnResponse(reply=turn.reply, kind=turn.kind, draft=turn.draft)


class ConfirmDay(BaseModel):
    base_city: str = Field(min_length=1, max_length=120)
    title: str = Field(default="", max_length=200)
    summary: str = Field(default="", max_length=1000)


class ConfirmDraft(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start_date: date
    travelers: int | None = Field(default=None, ge=1, le=50)
    interests: list[str] = Field(default_factory=list, max_length=20)
    days: list[ConfirmDay] = Field(min_length=1, max_length=MAX_DAYS)

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
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> TripOut:
    days_count = len(body.days)
    end_date = body.start_date + timedelta(days=days_count - 1)
    trip = Trip(
        owner_id=user.id,
        title=body.title,
        start_date=body.start_date,
        end_date=end_date,
        travelers=body.travelers,
        interests=[i.strip() for i in body.interests if i.strip()],
        status="planning",
    )
    session.add(trip)
    session.add(TripMember(trip_id=trip.id, user_id=user.id, role="owner"))

    places: dict[str, Place] = {}
    days: list[Day] = []
    for i, d in enumerate(body.days):
        key = d.base_city.casefold()
        if key not in places:
            places[key] = Place(trip_id=trip.id, name=d.base_city, kind="city")
            session.add(places[key])
        day = Day(
            trip_id=trip.id,
            date=body.start_date + timedelta(days=i),
            title=d.title or d.base_city,
            summary=d.summary,
            base_place_id=places[key].id,
        )
        days.append(day)
        session.add(day)

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
    session.commit()
    session.refresh(trip)
    return to_trip_out(trip, open_gap_count=len(gaps))
