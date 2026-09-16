"""Research agent loop, with a fake Anthropic client."""
from datetime import date
from types import SimpleNamespace as NS

import pytest

from app.agents.research import (
    CandidateIn,
    ResearchContext,
    ResearchError,
    _format_context,
    collect_result_urls,
    normalize_url,
    research_gap,
    verify_sources,
)


def usage(inp=100, out=50, searches=0, cache_read=0):
    return NS(
        input_tokens=inp, output_tokens=out, cache_creation_input_tokens=0, cache_read_input_tokens=cache_read,
        server_tool_use=NS(web_search_requests=searches),
    )


def search_result(*urls):
    return NS(type="web_search_tool_result", content=[NS(type="web_search_result", url=u, title="t") for u in urls])


def submit(candidates):
    return NS(type="tool_use", name="submit_candidates", id="tu_1", input={"candidates": candidates})


def response(stop, content, **u):
    return NS(stop_reason=stop, content=content, usage=usage(**u))


def cand(name="Hotel A", sources=None, **overrides):
    c = {
        "name": name, "summary": "Nice.", "pros": ["central"], "cons": ["small rooms"], "confidence": "high",
        "price_range": "€120–160 per night", "address": None, "neighborhood": "Baixa", "lat": None, "lng": None,
        "website_url": None, "booking_url": None, "activity_kind": None, "best_time": None,
        "sources": sources if sources is not None else [{"url": "https://hotel-a.example/", "title": "Hotel A", "note": "rates"}],
    }
    c.update(overrides)
    return c


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def ctx(**overrides):
    base = dict(
        trip_title="Portugal in May", destinations=["Portugal"], interests=["food"], travelers=2,
        trip_start=date(2027, 5, 1), trip_end=date(2027, 5, 10), gap_kind="lodging",
        gap_prompt="Where to stay in Lisbon (May 1–3, 3 nights)", day_date=date(2027, 5, 1),
        base_city="Lisbon", today=date(2026, 9, 16),
    )
    base.update(overrides)
    return ResearchContext(**base)


def test_happy_path_keeps_seen_sources_and_totals_usage():
    client = FakeClient([
        response("tool_use", [search_result("https://www.hotel-a.example"), submit([cand()])], inp=1000, out=200, searches=3),
    ])
    result = research_gap(ctx(), client=client)
    assert [c.name for c in result.candidates] == ["Hotel A"]
    assert result.candidates[0].sources[0].url == "https://hotel-a.example/"
    assert not result.candidates[0].unverified
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.searches) == (1000, 200, 3)
    # 1000*5/1e6 + 200*25/1e6 + 3*0.01
    assert result.usage.cost_usd() == pytest.approx(0.04)

    call = client.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["fallbacks"] == "default"
    tools = {t["name"]: t for t in call["tools"]}
    assert tools["web_search"]["type"] == "web_search_20260318"
    assert tools["submit_candidates"]["strict"] is True


def test_unseen_sources_are_dropped_and_candidate_marked_unverified():
    fake = [{"url": "https://made-up.example/page", "title": "x", "note": "y"}]
    client = FakeClient([response("tool_use", [search_result("https://real.example"), submit([cand(sources=fake)])])])
    c = research_gap(ctx(), client=client).candidates[0]
    assert c.sources == []
    assert c.unverified is True
    assert c.confidence == "low"


def test_pause_turn_resumes_without_extra_user_message():
    paused = [search_result("https://hotel-a.example")]
    client = FakeClient([
        response("pause_turn", paused, searches=2),
        response("tool_use", [submit([cand()])], searches=1),
    ])
    result = research_gap(ctx(), client=client)
    assert result.usage.searches == 3
    second = client.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant"]
    # Source seen in the first turn still counts in the second.
    assert result.candidates[0].sources


def test_end_turn_without_submit_gets_one_reminder():
    client = FakeClient([
        response("end_turn", [NS(type="text", text="Here are some ideas...")]),
        response("tool_use", [search_result("https://hotel-a.example"), submit([cand()])]),
    ])
    research_gap(ctx(), client=client)
    second = client.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert "submit_candidates" in second[-1]["content"]


def test_gives_up_after_max_turns():
    client = FakeClient([response("end_turn", [NS(type="text", text="hmm")]) for _ in range(4)])
    with pytest.raises(ResearchError, match="didn't finish"):
        research_gap(ctx(), client=client)
    assert len(client.calls) == 4


def test_refusal_raises_friendly_error():
    client = FakeClient([response("refusal", [])])
    with pytest.raises(ResearchError, match="couldn't help"):
        research_gap(ctx(), client=client)


def test_caps_at_five_candidates():
    many = [cand(name=f"H{i}") for i in range(7)]
    client = FakeClient([response("tool_use", [search_result("https://hotel-a.example"), submit(many)])])
    assert len(research_gap(ctx(), client=client).candidates) == 5


def test_search_error_blocks_are_ignored():
    blocks = [NS(type="web_search_tool_result", content=NS(type="web_search_tool_result_error", error_code="unavailable"))]
    assert collect_result_urls(blocks) == set()


def test_normalize_url():
    assert normalize_url("https://WWW.Example.com/a/#frag") == "https://example.com/a"
    assert normalize_url("https://example.com/a?b=1") == "https://example.com/a?b=1"


def test_prompt_includes_nudge_and_exclusions():
    text = _format_context(ctx(
        nudge="closer to the river", already_suggested=["Hotel A"], rejected=[("Hotel B", "too pricey")],
        nearby_days=["Sat May 1: Arrive Lisbon"],
    ))
    assert "closer to the river" in text
    assert "Hotel A" in text and "Hotel B: too pricey" in text
    assert "Sat May 1: Arrive Lisbon" in text
    assert "nightly price range" in text


def test_verify_sources_keeps_matching_urls_only():
    c = CandidateIn.model_validate(cand(sources=[
        {"url": "https://a.example/x/", "title": "a", "note": ""},
        {"url": "https://b.example", "title": "b", "note": ""},
    ]))
    [out] = verify_sources([c], {"https://a.example/x"})
    assert [s.url for s in out.sources] == ["https://a.example/x/"]
    assert out.confidence == "high" and not out.unverified
