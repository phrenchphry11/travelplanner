"""Inviting other people to plan a trip together."""
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from app.auth import current_user
from app.db import get_session
from app.models import Trip, TripInvite, TripMember, User
from app.routers.trips import get_member_trip

router = APIRouter(tags=["collaborators"])

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _owned_trip(session: Session, trip_id: str, user: User) -> Trip:
    """Only the trip owner may manage collaborators. Non-members get 404, other members 403."""
    trip = get_member_trip(session, trip_id, user)
    if trip.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the trip's owner can manage collaborators")
    return trip


class MemberOut(BaseModel):
    user_id: str
    display_name: str
    email: str
    role: str  # owner | editor


class InviteOut(BaseModel):
    id: str
    email: str
    role: str


class CollaboratorsOut(BaseModel):
    members: list[MemberOut]
    invites: list[InviteOut]  # pending, not yet redeemed


@router.get("/trips/{trip_id}/collaborators", response_model=CollaboratorsOut)
def list_collaborators(
    trip_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> CollaboratorsOut:
    """Any member can see who's on the trip; only the owner can change who."""
    trip = get_member_trip(session, trip_id, user)
    members = session.exec(
        select(TripMember, User).join(User, User.id == TripMember.user_id).where(TripMember.trip_id == trip.id)
    ).all()
    invites = session.exec(
        select(TripInvite).where(TripInvite.trip_id == trip.id, TripInvite.accepted_at.is_(None))
    ).all()
    return CollaboratorsOut(
        members=[
            MemberOut(user_id=m.user_id, display_name=u.display_name or u.email, email=u.email, role=m.role)
            for m, u in sorted(members, key=lambda pair: pair[0].role != "owner")
        ],
        invites=[InviteOut(id=i.id, email=i.email, role=i.role) for i in invites],
    )


class InviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("That doesn't look like an email address.")
        return v


@router.post("/trips/{trip_id}/collaborators", response_model=CollaboratorsOut, status_code=status.HTTP_201_CREATED)
def invite_collaborator(
    trip_id: str,
    body: InviteIn,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> CollaboratorsOut:
    """Add a collaborator right away if they've used the app before, otherwise invite them by
    email: they get access automatically the next time they sign in with that address."""
    trip = _owned_trip(session, trip_id, user)
    if body.email == user.email.strip().lower():
        raise HTTPException(status.HTTP_409_CONFLICT, "That's you.")

    existing_user = session.exec(select(User).where(User.email == body.email)).first()
    if existing_user is not None:
        if session.get(TripMember, (trip.id, existing_user.id)) is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "They're already on this trip.")
        session.add(TripMember(trip_id=trip.id, user_id=existing_user.id, role="editor"))
        session.commit()
        return list_collaborators(trip_id, user, session)

    already_invited = session.exec(
        select(TripInvite).where(
            TripInvite.trip_id == trip.id, TripInvite.email == body.email, TripInvite.accepted_at.is_(None)
        )
    ).first()
    if already_invited is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "They're already invited.")
    session.add(TripInvite(trip_id=trip.id, email=body.email, invited_by=user.id))
    session.commit()
    return list_collaborators(trip_id, user, session)


@router.delete("/trips/{trip_id}/collaborators/{user_id}", response_model=CollaboratorsOut)
def remove_collaborator(
    trip_id: str,
    user_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> CollaboratorsOut:
    trip = _owned_trip(session, trip_id, user)
    if user_id == trip.owner_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "The owner can't be removed.")
    member = session.get(TripMember, (trip.id, user_id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    session.delete(member)
    session.commit()
    return list_collaborators(trip_id, user, session)


@router.delete("/trips/{trip_id}/invites/{invite_id}", response_model=CollaboratorsOut)
def cancel_invite(
    trip_id: str,
    invite_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> CollaboratorsOut:
    trip = _owned_trip(session, trip_id, user)
    invite = session.get(TripInvite, invite_id)
    if invite is None or invite.trip_id != trip.id or invite.accepted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    session.delete(invite)
    session.commit()
    return list_collaborators(trip_id, user, session)
