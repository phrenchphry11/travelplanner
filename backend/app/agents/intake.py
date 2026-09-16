"""Intake agent: turns a free-text trip idea into a draft day-by-day skeleton.

Stateless. The client holds the conversation and the current (possibly
user-edited) draft and sends both on every turn.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from functools import lru_cache
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from app.config import get_settings

log = logging.getLogger(__name__)

MAX_FOLLOW_UPS = 2
MAX_DAYS = 60


class DraftDay(BaseModel):
    base_city: str = Field(description="Where the traveler sleeps or is based that day, e.g. 'Lisbon'.")
    title: str = Field(description="Short day title, e.g. 'Arrive Lisbon' or 'Day trip to Sintra'.")
    summary: str = Field(description="One sentence on what the day is about. Empty string if nothing to say.")


class TripDraft(BaseModel):
    title: str = Field(description="Short trip name, e.g. 'Portugal in May'.")
    destinations: list[str] = Field(description="Countries, regions, or cities mentioned, in travel order.")
    start_date: str | None = Field(
        description="First day as YYYY-MM-DD only if the traveler gave or clearly implied an exact date; otherwise null."
    )
    travelers: int | None = Field(description="Number of travelers if stated or clearly implied; otherwise null.")
    interests: list[str] = Field(description="Short interest tags such as 'food', 'wine', 'hiking'.")
    days: list[DraftDay] = Field(description="One entry per calendar day of the trip, in order.")


class IntakeTurn(BaseModel):
    reply: str = Field(
        description="What to say to the traveler: either one short follow-up question, or one or two sentences introducing the draft."
    )
    kind: Literal["question", "draft"]
    draft: TripDraft | None = Field(description="The full draft when kind is 'draft'; null when asking a question.")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)
    # Set on assistant messages, echoed back by the client, so we can count
    # follow-up questions without guessing from punctuation. Not sent to Claude.
    kind: Literal["question", "draft"] | None = None


class IntakeError(Exception):
    """A user-presentable intake failure."""


SYSTEM_PROMPT = """You help a traveler turn a rough trip idea into a day-by-day skeleton they can edit. Many travelers are not technical, so keep replies short, warm, and plain.

Each turn, either ask one follow-up question or produce a full draft.

Produce a draft as soon as you know roughly where they're going and roughly how long the trip is. Default anything else sensibly rather than asking: pick a reasonable route and pace, assume an arrival day and a departure day, and leave start_date null if they gave only a month or season. Ask a question only when you can't make a reasonable draft without the answer, and ask about one thing at a time. Never ask more than {max_follow_ups} questions in a conversation; after that, always draft with your best assumptions and mention what you assumed.

When a current draft is provided, treat it as the traveler's latest version, including any edits they made by hand, and change only what they ask for.

A good skeleton groups nights in each base city instead of moving every day, includes realistic travel days between cities, and uses day trips from a base where that's the normal way to visit a place. Titles are short. Don't recommend specific hotels, restaurants, or bookings; those get researched later.

Today's date is {today}. Interpret months and seasons as the next upcoming occurrence."""


@lru_cache
def _client() -> anthropic.Anthropic:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise IntakeError("The trip assistant isn't configured yet.")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120, max_retries=2)


def _build_messages(history: list[ChatMessage], current_draft: TripDraft | None) -> list[dict]:
    messages = [{"role": m.role, "content": m.content} for m in history]
    if current_draft is not None:
        messages[-1]["content"] += (
            "\n\n<current_draft>\n" + current_draft.model_dump_json(indent=2) + "\n</current_draft>"
        )
    return messages


def run_intake(history: list[ChatMessage], current_draft: TripDraft | None, today: date) -> IntakeTurn:
    questions_asked = sum(1 for m in history if m.role == "assistant" and m.kind == "question")
    system = SYSTEM_PROMPT.format(max_follow_ups=MAX_FOLLOW_UPS, today=today.isoformat())
    messages = _build_messages(history, current_draft)
    if questions_asked >= MAX_FOLLOW_UPS:
        messages.append({
            "role": "system",
            "content": "You've used all follow-up questions. Produce a draft now, stating your assumptions in the reply.",
        })

    try:
        response = _client().beta.messages.parse(
            model=get_settings().intake_model,
            max_tokens=16000,
            system=system,
            messages=messages,
            output_format=IntakeTurn,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError as exc:
        log.warning("intake rate limited: %s", exc)
        raise IntakeError("The trip assistant is busy right now. Try again in a minute.") from exc
    except anthropic.APIStatusError as exc:
        log.exception("intake API error")
        raise IntakeError("The trip assistant hit a problem. Try again.") from exc
    except anthropic.APIConnectionError as exc:
        log.exception("intake connection error")
        raise IntakeError("Couldn't reach the trip assistant. Try again.") from exc

    log.info(
        "intake model=%s stop=%s in=%s out=%s",
        response.model, response.stop_reason, response.usage.input_tokens, response.usage.output_tokens,
    )
    if response.stop_reason == "refusal":
        raise IntakeError("The trip assistant couldn't help with that request. Try describing the trip differently.")
    turn = response.parsed_output
    if turn is None:
        raise IntakeError("The trip assistant gave an unexpected answer. Try again.")
    if turn.kind == "draft" and turn.draft is None:
        raise IntakeError("The trip assistant gave an unexpected answer. Try again.")
    if turn.draft is not None and not (1 <= len(turn.draft.days) <= MAX_DAYS):
        raise IntakeError(f"Trips can be 1 to {MAX_DAYS} days. Try a shorter trip or split it up.")
    return turn


IntakeRunner = Callable[[list[ChatMessage], TripDraft | None, date], IntakeTurn]


def get_intake_runner() -> IntakeRunner:
    """FastAPI dependency so tests can swap in a fake."""
    return run_intake
