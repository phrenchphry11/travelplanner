from sqlmodel import Session, select

from app.collaborators import redeem_invites
from app.models import TripInvite, TripMember, User
from tests.test_choices import _confirm

CITIES = ["Lisbon", "Porto"]


def test_inviting_someone_whos_used_the_app_adds_them_right_away(make_client, session):
    owner = make_client("owner")
    stranger = make_client("stranger")
    stranger.get("/me")  # they've signed in before, so their User row already exists
    trip_id = _confirm(owner, cities=CITIES)

    res = owner.post(f"/trips/{trip_id}/collaborators", json={"email": "stranger@example.com"})
    assert res.status_code == 201
    out = res.json()
    assert out["invites"] == []
    assert {m["user_id"]: m["role"] for m in out["members"]} == {"owner": "owner", "stranger": "editor"}

    assert session.get(TripMember, (trip_id, "stranger")).role == "editor"
    # They have real access now, not just a listing.
    assert stranger.get(f"/trips/{trip_id}/board").status_code == 200
    assert [t["id"] for t in stranger.get("/trips").json()] == [trip_id]


def test_inviting_a_new_email_creates_a_pending_invite_redeemed_on_first_sign_in(make_client, engine, session):
    owner = make_client("owner")
    trip_id = _confirm(owner, cities=CITIES)

    out = owner.post(f"/trips/{trip_id}/collaborators", json={"email": "friend@example.com"}).json()
    assert out["members"] == [m for m in out["members"] if m["role"] == "owner"]
    assert [i["email"] for i in out["invites"]] == ["friend@example.com"]

    invite = session.exec(select(TripInvite).where(TripInvite.trip_id == trip_id)).one()
    assert invite.accepted_at is None

    # Their first sign-in: the app creates the User row, then redeems invites (app/auth.py).
    with Session(engine) as s:
        friend = User(id="friend", email="friend@example.com")
        s.add(friend)
        s.commit()
        s.refresh(friend)
        redeem_invites(s, friend)

    session.expire_all()
    assert session.get(TripMember, (trip_id, "friend")).role == "editor"
    assert session.get(TripInvite, invite.id).accepted_at is not None

    friend_client = make_client("friend")
    assert friend_client.get(f"/trips/{trip_id}/board").status_code == 200


def test_redeem_invites_is_safe_to_call_with_no_matching_invites(session):
    user = User(id="nobody", email="nobody@example.com")
    session.add(user)
    session.commit()
    redeem_invites(session, user)  # just shouldn't raise


def test_invite_validation_and_duplicates(make_client):
    owner = make_client("owner")
    make_client("stranger")
    trip_id = _confirm(owner, cities=CITIES)

    assert owner.post(f"/trips/{trip_id}/collaborators", json={"email": "not-an-email"}).status_code == 422
    assert owner.post(f"/trips/{trip_id}/collaborators", json={"email": "owner@example.com"}).status_code == 409

    owner.post(f"/trips/{trip_id}/collaborators", json={"email": "stranger@example.com"})
    assert owner.post(f"/trips/{trip_id}/collaborators", json={"email": "stranger@example.com"}).status_code == 409

    owner.post(f"/trips/{trip_id}/collaborators", json={"email": "friend@example.com"})
    assert owner.post(f"/trips/{trip_id}/collaborators", json={"email": "friend@example.com"}).status_code == 409


def test_only_the_owner_can_manage_collaborators(make_client):
    owner = make_client("owner")
    trip_id = _confirm(owner, cities=CITIES)
    owner.post(f"/trips/{trip_id}/collaborators", json={"email": "editor@example.com"})
    editor = make_client("editor")  # now a real member, via the invite above
    stranger = make_client("stranger")

    assert stranger.post(f"/trips/{trip_id}/collaborators", json={"email": "x@example.com"}).status_code == 404
    assert editor.post(f"/trips/{trip_id}/collaborators", json={"email": "x@example.com"}).status_code == 403
    assert editor.get(f"/trips/{trip_id}/collaborators").status_code == 200  # members can still see the list


def test_remove_a_collaborator_and_cannot_remove_the_owner(make_client):
    owner = make_client("owner")
    trip_id = _confirm(owner, cities=CITIES)
    owner.post(f"/trips/{trip_id}/collaborators", json={"email": "editor@example.com"})
    make_client("editor").get("/me")  # they sign in, redeeming the invite into real membership

    assert owner.delete(f"/trips/{trip_id}/collaborators/owner").status_code == 409
    out = owner.delete(f"/trips/{trip_id}/collaborators/editor").json()
    assert [m["user_id"] for m in out["members"]] == ["owner"]
    assert owner.delete(f"/trips/{trip_id}/collaborators/editor").status_code == 404


def test_cancel_a_pending_invite(make_client, session):
    owner = make_client("owner")
    trip_id = _confirm(owner, cities=CITIES)
    invite_id = owner.post(f"/trips/{trip_id}/collaborators", json={"email": "friend@example.com"}).json()["invites"][0]["id"]

    out = owner.delete(f"/trips/{trip_id}/invites/{invite_id}").json()
    assert out["invites"] == []
    assert session.get(TripInvite, invite_id) is None
    assert owner.delete(f"/trips/{trip_id}/invites/{invite_id}").status_code == 404


def test_is_owner_reflects_who_is_looking(make_client):
    owner = make_client("owner")
    trip_id = _confirm(owner, cities=CITIES)
    owner.post(f"/trips/{trip_id}/collaborators", json={"email": "editor@example.com"})
    editor = make_client("editor")

    assert owner.get(f"/trips/{trip_id}").json()["is_owner"] is True
    assert editor.get(f"/trips/{trip_id}").json()["is_owner"] is False
    assert owner.get(f"/trips/{trip_id}/board").json()["trip"]["is_owner"] is True
    assert editor.get(f"/trips/{trip_id}/board").json()["trip"]["is_owner"] is False
    assert [t["is_owner"] for t in owner.get("/trips").json()] == [True]
    assert [t["is_owner"] for t in editor.get("/trips").json()] == [False]


def test_an_editor_can_edit_the_trip_like_the_owner(make_client):
    """Collaborators get full edit access via the existing membership checks; only
    delete/restore/share management and collaborator management stay owner-only."""
    owner = make_client("owner")
    trip_id = _confirm(owner, cities=CITIES)
    owner.post(f"/trips/{trip_id}/collaborators", json={"email": "editor@example.com"})
    editor = make_client("editor")

    day_id = editor.get(f"/trips/{trip_id}/board").json()["days"][0]["id"]
    assert editor.post(f"/days/{day_id}/plans", json={"name": "Museum"}).status_code == 201
    assert editor.delete(f"/trips/{trip_id}").status_code == 403
    assert editor.post(f"/trips/{trip_id}/share").status_code == 403


def test_collaborator_endpoints_404_on_a_deleted_trip(make_client):
    owner = make_client("owner")
    trip_id = _confirm(owner, cities=CITIES)
    owner.post(f"/trips/{trip_id}/collaborators", json={"email": "editor@example.com"})
    owner.delete(f"/trips/{trip_id}")

    assert owner.get(f"/trips/{trip_id}/collaborators").status_code == 404
    assert owner.post(f"/trips/{trip_id}/collaborators", json={"email": "friend@example.com"}).status_code == 404
