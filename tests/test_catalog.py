from tests.conftest import assert_error

API = "/api/v1"


# --- genres ---------------------------------------------------------------------------------


def test_create_and_list_genres(client):
    assert client.post(f"{API}/genres", json={"name": " Rock "}).status_code == 201
    client.post(f"{API}/genres", json={"name": "jazz"})

    response = client.get(f"{API}/genres")

    assert response.status_code == 200
    # Names are normalised (trimmed, lower case) and sorted.
    assert [g["name"] for g in response.json()] == ["jazz", "rock"]


def test_duplicate_genre_is_a_conflict(client):
    client.post(f"{API}/genres", json={"name": "rock"})
    assert_error(client.post(f"{API}/genres", json={"name": "ROCK"}), 409, "conflict")


def test_empty_genre_name_is_rejected(client):
    assert_error(client.post(f"{API}/genres", json={"name": ""}), 422, "validation_error")


# --- artists --------------------------------------------------------------------------------


def test_create_artist_with_genres(client, factory):
    rock, jazz = factory.genre("rock"), factory.genre("jazz")
    payload = {
        "name": "Nina",
        "mbid": "5b11f4ce-a62d-471e-81fc-a69a8278c7da",
        "genre_ids": [rock.id, jazz.id],
    }

    response = client.post(f"{API}/artists", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Nina"
    assert body["mbid"] == payload["mbid"]
    assert [g["name"] for g in body["genres"]] == ["jazz", "rock"]
    assert client.get(f"{API}/artists/{body['id']}").json() == body


def test_create_artist_with_unknown_genre(client, factory):
    rock = factory.genre("rock")
    response = client.post(f"{API}/artists", json={"name": "X", "genre_ids": [rock.id, 999]})
    error = assert_error(response, 422, "unknown_reference")
    assert error["details"] == {"genre_ids": [999]}


def test_duplicate_artist_mbid_is_a_conflict(client):
    payload = {"name": "A", "mbid": "5b11f4ce-a62d-471e-81fc-a69a8278c7da"}
    client.post(f"{API}/artists", json=payload)
    assert_error(client.post(f"{API}/artists", json=payload), 409, "conflict")


def test_invalid_mbid_is_rejected(client):
    response = client.post(f"{API}/artists", json={"name": "A", "mbid": "not-a-uuid"})
    assert_error(response, 422, "validation_error")


def test_get_missing_artist(client):
    error = assert_error(client.get(f"{API}/artists/123"), 404, "not_found")
    assert "123" in error["message"]


def test_list_artists_paginates(client, factory):
    for name in ["Cher", "Abba", "Bjork"]:
        factory.artist(name)

    response = client.get(f"{API}/artists", params={"limit": 2, "offset": 1})

    body = response.json()
    assert body["total"] == 3
    assert (body["limit"], body["offset"]) == (2, 1)
    assert [a["name"] for a in body["items"]] == ["Bjork", "Cher"]


def test_search_artists_is_case_insensitive(client, factory):
    factory.artist("The Silent Wolves")
    factory.artist("Neon Tides")

    body = client.get(f"{API}/artists", params={"q": "silent"}).json()

    assert [a["name"] for a in body["items"]] == ["The Silent Wolves"]


def test_search_treats_percent_literally(client, factory):
    factory.artist("100% Pure")
    factory.artist("Other")

    body = client.get(f"{API}/artists", params={"q": "%"}).json()

    assert [a["name"] for a in body["items"]] == ["100% Pure"]


def test_pagination_limits_are_validated(client):
    assert_error(client.get(f"{API}/artists", params={"limit": 0}), 422, "validation_error")
    assert_error(client.get(f"{API}/artists", params={"limit": 201}), 422, "validation_error")
    assert_error(client.get(f"{API}/artists", params={"offset": -1}), 422, "validation_error")


# --- tracks ---------------------------------------------------------------------------------


def test_create_and_get_track(client, factory):
    artist = factory.artist("Nina")

    response = client.post(
        f"{API}/tracks", json={"title": "Song", "artist_id": artist.id, "duration_ms": 180_000}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["artist"] == {"id": artist.id, "name": "Nina"}
    assert client.get(f"{API}/tracks/{body['id']}").json() == body


def test_create_track_for_unknown_artist(client):
    response = client.post(f"{API}/tracks", json={"title": "S", "artist_id": 9, "duration_ms": 1})
    error = assert_error(response, 422, "unknown_reference")
    assert error["details"] == {"artist_id": 9}


def test_track_duration_must_be_positive(client, factory):
    artist = factory.artist()
    response = client.post(
        f"{API}/tracks", json={"title": "S", "artist_id": artist.id, "duration_ms": 0}
    )
    assert_error(response, 422, "validation_error")


def test_list_tracks_filtered_by_artist(client, factory):
    a, b = factory.artist("A"), factory.artist("B")
    factory.track(a, "a1")
    factory.track(b, "b1")
    factory.track(a, "a2")

    body = client.get(f"{API}/tracks", params={"artist_id": a.id}).json()

    assert body["total"] == 2
    assert [t["title"] for t in body["items"]] == ["a1", "a2"]


def test_get_missing_track(client):
    assert_error(client.get(f"{API}/tracks/5"), 404, "not_found")


# --- listeners ------------------------------------------------------------------------------


def test_create_list_and_get_listener(client):
    response = client.post(f"{API}/listeners", json={"username": "alice", "country": "PL"})
    assert response.status_code == 201
    listener = response.json()

    assert client.get(f"{API}/listeners/{listener['id']}").json() == listener
    page = client.get(f"{API}/listeners").json()
    assert page["total"] == 1
    assert page["items"] == [listener]


def test_duplicate_username_is_a_conflict(client):
    client.post(f"{API}/listeners", json={"username": "alice"})
    assert_error(client.post(f"{API}/listeners", json={"username": "alice"}), 409, "conflict")


def test_listener_input_is_validated(client):
    for payload in [{"username": "a b"}, {"username": "ab"}, {"username": "bob", "country": "pl"}]:
        assert_error(client.post(f"{API}/listeners", json=payload), 422, "validation_error")


def test_get_missing_listener(client):
    assert_error(client.get(f"{API}/listeners/1"), 404, "not_found")
