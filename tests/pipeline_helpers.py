"""Fake MusicBrainz responses for pipeline tests (no network)."""

import httpx

from pipeline.musicbrainz import MusicBrainzClient

MBID_A = "11111111-1111-4111-8111-111111111111"
MBID_B = "22222222-2222-4222-8222-222222222222"
MBID_C = "33333333-3333-4333-8333-333333333333"


def mb_artist(mbid: str, name: str, tags=(("jazz", 3),), country: str | None = "GB") -> dict:
    """One artist in the shape returned by https://musicbrainz.org/ws/2/artist?fmt=json."""
    return {
        "id": mbid,
        "type": "Person",
        "score": 100,
        "name": name,
        "sort-name": name,
        "country": country,
        "life-span": {"begin": "1959", "ended": None},
        "tags": [{"count": count, "name": tag} for tag, count in tags],
    }


def search_page(artists: list[dict], offset: int = 0) -> dict:
    return {"created": "2026-11-12T00:00:00Z", "count": 1000, "offset": offset, "artists": artists}


class FakeMusicBrainz:
    """Answers search requests from a dict {(tag, offset): page} and records every request."""

    def __init__(self, pages: dict[tuple[str, int], dict], status_code: int = 200) -> None:
        self.pages = pages
        self.status_code = status_code
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status_code != 200:
            return httpx.Response(self.status_code, json={"error": "busy"})
        tag = request.url.params["query"].removeprefix('tag:"').removesuffix('"')
        page = self.pages.get((tag, int(request.url.params["offset"])), search_page([]))
        return httpx.Response(200, json=page)

    def client(self) -> MusicBrainzClient:
        http = httpx.Client(
            base_url="https://musicbrainz.test/ws/2",
            transport=httpx.MockTransport(self.handler),
        )
        # No real waiting in tests.
        return MusicBrainzClient(http, sleep=lambda _: None)
