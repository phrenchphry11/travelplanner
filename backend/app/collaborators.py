"""Turning an email invite into real access, once the invitee signs in."""
from sqlmodel import Session, select

from app.models import TripInvite, TripMember, User, utcnow


def redeem_invites(session: Session, user: User) -> None:
    """Materialize any pending invites for this user's email into TripMember rows.

    Call whenever a user's email is freshly known (new account, or email
    changed) so an invited collaborator gets access the moment they sign in
    with the matching address, no separate "accept" step needed.
    """
    if not user.email:
        return
    email = user.email.strip().lower()
    invites = session.exec(
        select(TripInvite).where(TripInvite.email == email, TripInvite.accepted_at.is_(None))
    ).all()
    for invite in invites:
        invite.accepted_at = utcnow()
        session.add(invite)
        if session.get(TripMember, (invite.trip_id, user.id)) is None:
            session.add(TripMember(trip_id=invite.trip_id, user_id=user.id, role=invite.role))
    if invites:
        session.commit()
