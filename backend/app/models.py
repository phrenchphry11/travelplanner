"""SQLModel tables. Mirrors docs/data-model.md.

Ids are uuid4 strings and list/dict fields use JSON so the schema runs on
both Postgres (Render) and SQLite (local dev).
"""
from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_share_slug() -> str:
    return secrets.token_urlsafe(16)  # 128 bits


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: str = Field(primary_key=True)  # Clerk user id
    email: str = Field(index=True)
    display_name: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class Trip(SQLModel, table=True):
    __tablename__ = "trips"
    id: str = Field(default_factory=new_id, primary_key=True)
    owner_id: str = Field(foreign_key="users.id", index=True)
    title: str
    start_date: date | None = None
    end_date: date | None = None
    home_base_note: str = ""
    status: str = "dreaming"  # dreaming | planning | booked | done
    share_slug: str | None = Field(default=None, index=True, unique=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TripMember(SQLModel, table=True):
    __tablename__ = "trip_members"
    trip_id: str = Field(foreign_key="trips.id", primary_key=True)
    user_id: str = Field(foreign_key="users.id", primary_key=True)
    role: str = "editor"  # owner | editor | viewer


class Place(SQLModel, table=True):
    __tablename__ = "places"
    id: str = Field(default_factory=new_id, primary_key=True)
    trip_id: str = Field(foreign_key="trips.id", index=True)
    name: str
    kind: str = "other"  # lodging|food|coffee|sight|shop|station|airport|neighborhood|other
    lat: float | None = None
    lng: float | None = None
    precision: str = "unknown"  # exact | approximate | unknown
    address: str = ""
    google_maps_url: str = ""
    website_url: str = ""
    summary: str = ""
    notes: str = ""
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class Day(SQLModel, table=True):
    __tablename__ = "days"
    id: str = Field(default_factory=new_id, primary_key=True)
    trip_id: str = Field(foreign_key="trips.id", index=True)
    date: date
    title: str = ""
    summary: str = ""
    notes: str = ""
    base_place_id: str | None = Field(default=None, foreign_key="places.id")


class Lodging(SQLModel, table=True):
    __tablename__ = "lodgings"
    id: str = Field(default_factory=new_id, primary_key=True)
    trip_id: str = Field(foreign_key="trips.id", index=True)
    place_id: str = Field(foreign_key="places.id")
    check_in: date
    check_out: date
    booking_url: str = ""
    confirmation_code: str = ""
    cost: float | None = None
    currency: str = ""
    status: str = "idea"  # idea | shortlisted | booked
    notes: str = ""


class Transit(SQLModel, table=True):
    __tablename__ = "transits"
    id: str = Field(default_factory=new_id, primary_key=True)
    trip_id: str = Field(foreign_key="trips.id", index=True)
    day_id: str = Field(foreign_key="days.id", index=True)
    name: str
    method: str = "other"  # train|flight|drive|bus|ferry|walk|taxi|other
    from_place_id: str | None = Field(default=None, foreign_key="places.id")
    to_place_id: str | None = Field(default=None, foreign_key="places.id")
    depart_at: datetime | None = None
    arrive_at: datetime | None = None
    booking_url: str = ""
    confirmation_code: str = ""
    status: str = "idea"
    notes: str = ""


class Activity(SQLModel, table=True):
    __tablename__ = "activities"
    id: str = Field(default_factory=new_id, primary_key=True)
    trip_id: str = Field(foreign_key="trips.id", index=True)
    day_id: str = Field(foreign_key="days.id", index=True)
    name: str
    kind: str = "other"  # meal|sight|tour|outdoors|shopping|rest|other
    place_id: str | None = Field(default=None, foreign_key="places.id")
    start_time: str = ""  # local "HH:MM" or free text
    end_time: str = ""
    booking_url: str = ""
    status: str = "idea"  # idea | shortlisted | planned | booked
    notes: str = ""
    sort_order: int = 0


class Gap(SQLModel, table=True):
    __tablename__ = "gaps"
    id: str = Field(default_factory=new_id, primary_key=True)
    trip_id: str = Field(foreign_key="trips.id", index=True)
    day_id: str | None = Field(default=None, foreign_key="days.id", index=True)
    kind: str  # lodging | transit | activity | food | question
    prompt: str
    status: str = "open"  # open | researching | answered | dismissed
    resolved_by_kind: str | None = None
    resolved_by_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Candidate(SQLModel, table=True):
    __tablename__ = "candidates"
    id: str = Field(default_factory=new_id, primary_key=True)
    trip_id: str = Field(foreign_key="trips.id", index=True)
    gap_id: str = Field(foreign_key="gaps.id", index=True)
    target_kind: str  # lodging | transit | activity | place
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    place_id: str | None = Field(default=None, foreign_key="places.id")
    summary: str = ""
    pros: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    cons: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    confidence: str = "medium"  # low | medium | high
    status: str = "proposed"  # proposed | accepted | rejected | needs_more
    rejection_reason: str = ""
    created_by: str = "agent"  # "agent" or a user id
    created_at: datetime = Field(default_factory=utcnow)


class Source(SQLModel, table=True):
    __tablename__ = "sources"
    id: str = Field(default_factory=new_id, primary_key=True)
    trip_id: str = Field(foreign_key="trips.id", index=True)
    subject_kind: str = Field(index=True)  # candidate | place | lodging | activity | ...
    subject_id: str = Field(index=True)
    title: str = ""
    url: str
    note: str = ""
    fetched_at: datetime | None = None


class ResearchJob(SQLModel, table=True):
    __tablename__ = "research_jobs"
    id: str = Field(default_factory=new_id, primary_key=True)
    trip_id: str = Field(foreign_key="trips.id", index=True)
    gap_id: str = Field(foreign_key="gaps.id", index=True)
    status: str = Field(default="queued", index=True)  # queued|running|done|failed
    nudge: str = ""
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    search_count: int = 0
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)
