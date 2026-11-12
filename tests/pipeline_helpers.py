"""Fake MusicBrainz responses for pipeline tests (no network)."""

import httpx

from pipeline.musicbrainz import MusicBrainzClient

MBID_A = "11111111-1111-4111-8111-111111111111"
MBID_B = "22222222-2222-4222-8222-222222222222"
MBID_C = "33333333-3333-4333-8333-333333333333"
REC_1 = "aaaaaaaa-0000-4000-8000-000000000001"
REC_2 = "aaaaaaaa-0000-4000-8000-000000000002"
REC_3 = "aaaaaaaa-0000-4000-8000-000000000003"


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


def mb_recording(mbid: str, title: str, length: int | None = 200_000, video: bool = False) -> dict:
    """One recording in the shape returned by /ws/2/recording?artist=<mbid>&fmt=json."""
    return {
        "id": mbid,
        "title": title,
        "length": length,
        "video": video,
        "disambiguation": "",
        "first-release-date": "1959-08-17",
    }


def recordings_page(recordings: list[dict], offset: int = 0) -> dict:
    return {"recording-count": 1000, "recording-offset": offset, "recordings": recordings}


class FakeMusicBrainz:
    """A fake MusicBrainz API that records every request.

    `pages` answers artist searches: {(tag, offset): page}.
    `recordings` answers recording browsing: {(artist_mbid, offset): page}.
    Anything not listed gets an empty page.
    """

    def __init__(
        self,
        pages: dict[tuple[str, int], dict],
        status_code: int = 200,
        recordings: dict[tuple[str, int], dict] | None = None,
    ) -> None:
        self.pages = pages
        self.recordings = recordings or {}
        self.status_code = status_code
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status_code != 200:
            return httpx.Response(self.status_code, json={"error": "busy"})
        params = request.url.params
        offset = int(params["offset"])
        if request.url.path.endswith("/recording"):
            page = self.recordings.get((params["artist"], offset), recordings_page([]))
        else:
            tag = params["query"].removeprefix('tag:"').removesuffix('"')
            page = self.pages.get((tag, offset), search_page([]))
        return httpx.Response(200, json=page)

    def recording_requests(self) -> list[tuple[str, int]]:
        return [
            (r.url.params["artist"], int(r.url.params["offset"]))
            for r in self.requests
            if r.url.path.endswith("/recording")
        ]

    def client(self) -> MusicBrainzClient:
        http = httpx.Client(
            base_url="https://musicbrainz.test/ws/2",
            transport=httpx.MockTransport(self.handler),
        )
        # No real waiting in tests.
        return MusicBrainzClient(http, sleep=lambda _: None)


# --- ListenBrainz ---------------------------------------------------------------------------


def lb_listen(
    listened_at: int,
    recording_mbid: str | None,
    artist_mbid: str | None = None,
    track: str = "Track",
    artist: str = "Artist",
    duration_ms: int | None = None,
    mapped: bool = True,
    msid: str | None = None,
) -> dict:
    """One listen in the shape of /1/user/<name>/listens.

    mapped=True puts the mbids where ListenBrainz's own MusicBrainz mapping puts them;
    mapped=False only in `additional_info`, as sent by the listening app.
    """
    additional_info: dict = {}
    if duration_ms is not None:
        additional_info["duration_ms"] = duration_ms
    metadata: dict = {
        "artist_name": artist,
        "track_name": track,
        "additional_info": additional_info,
    }
    if mapped and recording_mbid:
        metadata["mbid_mapping"] = {
            "recording_mbid": recording_mbid,
            "recording_name": track,
            "artists": [{"artist_mbid": artist_mbid, "artist_credit_name": artist}]
            if artist_mbid
            else [],
        }
    elif recording_mbid:
        additional_info["recording_mbid"] = recording_mbid
        if artist_mbid:
            additional_info["artist_mbids"] = [artist_mbid]
    return {
        "listened_at": listened_at,
        "recording_msid": msid or f"msid-{recording_mbid}-{listened_at}",
        "track_metadata": metadata,
    }


class FakeListenBrainz:
    """Serves {user: [listens]} with the real API's rules: newest first, `count`, and
    `max_ts` meaning "strictly older than"."""

    def __init__(self, listens: dict[str, list[dict]]) -> None:
        self.listens = listens
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        user = request.url.path.split("/")[-2]
        if user not in self.listens:
            return httpx.Response(404, json={"code": 404, "error": "Cannot find user"})
        count = int(request.url.params["count"])
        max_ts = request.url.params.get("max_ts")
        listens = sorted(self.listens[user], key=lambda x: x["listened_at"], reverse=True)
        if max_ts is not None:
            listens = [x for x in listens if x["listened_at"] < int(max_ts)]
        page = listens[:count]
        return httpx.Response(
            200, json={"payload": {"count": len(page), "user_id": user, "listens": page}}
        )

    def max_ts_sent(self) -> list[str | None]:
        return [r.url.params.get("max_ts") for r in self.requests]

    def client(self):
        from pipeline.listenbrainz import ListenBrainzClient

        http = httpx.Client(
            base_url="https://listenbrainz.test/1", transport=httpx.MockTransport(self.handler)
        )
        return ListenBrainzClient(http, sleep=lambda _: None)
