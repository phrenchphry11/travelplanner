from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from app.auth import current_user
from app.card_catalog import CARD_CATALOG
from app.db import get_session
from app.models import User, UserCard

router = APIRouter(tags=["me"])


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name}


@router.get("/cards/catalog")
def card_catalog() -> dict:
    return {"catalog": CARD_CATALOG}


class CardsOut(BaseModel):
    cards: list[str]


class CardsIn(BaseModel):
    cards: list[str] = Field(max_length=30)

    @field_validator("cards")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for name in v:
            name = name.strip()
            if name and name.casefold() not in {s.casefold() for s in seen}:
                seen[name] = None
        return list(seen)


def _cards_out(session: Session, user: User) -> CardsOut:
    rows = session.exec(select(UserCard).where(UserCard.user_id == user.id).order_by(UserCard.created_at)).all()
    return CardsOut(cards=[r.name for r in rows])


@router.get("/me/cards", response_model=CardsOut)
def list_cards(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> CardsOut:
    return _cards_out(session, user)


@router.put("/me/cards", response_model=CardsOut)
def set_cards(
    body: CardsIn,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> CardsOut:
    """Replace the traveler's whole card/loyalty-program list."""
    for row in session.exec(select(UserCard).where(UserCard.user_id == user.id)):
        session.delete(row)
    session.flush()
    for name in body.cards:
        session.add(UserCard(user_id=user.id, name=name))
    session.commit()
    return _cards_out(session, user)


@router.post("/me/cards/dismiss-nudge", status_code=204)
def dismiss_cards_nudge(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> None:
    """The board's 'add your cards' banner, dismissed for good."""
    if not user.cards_banner_dismissed:
        user.cards_banner_dismissed = True
        session.add(user)
        session.commit()
