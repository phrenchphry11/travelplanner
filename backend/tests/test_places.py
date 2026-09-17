from sqlmodel import Session, select

from app.geocoding import GeoResult, geocode_trip_places
from app.models import Place
from tests.test_choices import _confirm

CITIES = ["Lisbon", "Lisbon", "Porto"]


def _add(client, trip_id, **fields):
    body = {"name": "A Brasileira", "kind": "coffee", **fields}
    return client.post(f"/trips/{trip_id}/places", json=body)


def test_add_saved_place(make_client, session):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    res = _add(client, trip_id, address="R. Garrett 122, Lisbon", link="cafeabrasileira.pt", notes="Try the bica")
    assert res.status_code == 201
    out = res.json()
    assert out == {
        "id": out["id"], "name": "A Brasileira", "kind": "coffee",
        "address": "R. Garrett 122, Lisbon", "link": "https://cafeabrasileira.pt", "notes": "Try the bica",
    }
    place = session.get(Place, out["id"])
    assert place.saved is True and place.trip_id == trip_id

    board = client.get(f"/trips/{trip_id}/board").json()
    saved = [p for p in board["places"] if p["saved"]]
    assert [p["name"] for p in saved] == ["A Brasileira"]
    assert saved[0]["kind"] == "coffee"


def test_add_saved_place_validation(make_client):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    assert _add(client, trip_id, name="   ").status_code == 422
    assert _add(client, trip_id, link="javascript:alert(1)").status_code == 422
    assert client.post(f"/trips/nope/places", json={"name": "x"}).status_code == 404


def test_add_saved_place_is_private(make_client):
    owner = make_client("owner")
    trip_id = _confirm(owner, cities=CITIES)
    stranger = make_client("stranger")
    assert _add(stranger, trip_id).status_code == 404


def test_edit_saved_place(make_client, session):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    place_id = _add(client, trip_id).json()["id"]

    out = client.patch(f"/places/{place_id}", json={"name": "Café A Brasileira", "kind": "sight", "notes": "Historic"}).json()
    assert (out["name"], out["kind"], out["notes"]) == ("Café A Brasileira", "sight", "Historic")

    assert client.patch(f"/places/{place_id}", json={"name": "  "}).status_code == 422
    assert client.patch("/places/nope", json={"name": "x"}).status_code == 404
    stranger = make_client("stranger")
    assert stranger.patch(f"/places/{place_id}", json={"name": "mine now"}).status_code == 404


def test_editing_address_clears_the_pin_for_a_fresh_lookup(make_client, session):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    place_id = _add(client, trip_id).json()["id"]

    place = session.get(Place, place_id)
    place.lat, place.lng, place.precision = 38.71, -9.14, "approximate"
    session.add(place)
    session.commit()

    client.patch(f"/places/{place_id}", json={"address": "New street, Lisbon"})
    session.expire_all()
    place = session.get(Place, place_id)
    assert (place.lat, place.precision) == (None, "unknown")

    # Editing something else leaves an existing pin alone.
    place.lat, place.lng, place.precision = 38.71, -9.14, "approximate"
    session.add(place)
    session.commit()
    client.patch(f"/places/{place_id}", json={"notes": "still great"})
    session.expire_all()
    assert session.get(Place, place_id).lat == 38.71


def test_remove_saved_place(make_client, session):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    place_id = _add(client, trip_id).json()["id"]
    assert client.delete(f"/places/{place_id}").status_code == 204
    assert session.get(Place, place_id) is None
    assert client.delete(f"/places/{place_id}").status_code == 404


def test_cannot_edit_or_remove_a_place_that_isnt_saved(make_client, session):
    """A city, lodging, or research-option place isn't a "saved place": no back door via this router."""
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    city = session.exec(select(Place).where(Place.trip_id == trip_id, Place.kind == "city")).first()
    assert client.patch(f"/places/{city.id}", json={"name": "hacked"}).status_code == 404
    assert client.delete(f"/places/{city.id}").status_code == 404


def _country_fetch(answers):
    """answers: {query -> GeoResult}. 'Portugal' resolves to a boundary in pt."""

    def fetch(params):
        if params["q"] == "Portugal":
            return [GeoResult(39.6, -8.0, "Portugal", "boundary", "pt")]
        return answers.get(params["q"], [])

    return fetch


def test_saved_place_is_pinned_within_the_trips_countries(make_client, session):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    place_id = _add(client, trip_id, address="R. Garrett 122, Lisbon").json()["id"]

    fetch = _country_fetch({"R. Garrett 122, Lisbon": [GeoResult(38.71, -9.14, "A Brasileira", "amenity", "pt")]})
    geocode_trip_places(trip_id, session_factory=lambda: Session(session.get_bind()), fetch=fetch)

    board = client.get(f"/trips/{trip_id}/board").json()
    place = next(p for p in board["places"] if p["id"] == place_id)
    assert (place["lat"], place["precision"]) == (38.71, "approximate")


def test_saved_place_outside_trip_countries_gets_no_pin(make_client, session):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    place_id = _add(client, trip_id, address="Somewhere").json()["id"]

    fetch = _country_fetch({"Somewhere, Lisbon": [GeoResult(-16.74, -49.19, "Elsewhere", "amenity", "br")]})
    geocode_trip_places(trip_id, session_factory=lambda: Session(session.get_bind()), fetch=fetch)

    board = client.get(f"/trips/{trip_id}/board").json()
    place = next(p for p in board["places"] if p["id"] == place_id)
    assert place["lat"] is None
