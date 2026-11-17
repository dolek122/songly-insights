import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from sqlalchemy import Engine, text

from pipeline.http import RateLimiter, make_user_agent, send_json

logger = logging.getLogger(__name__)

BASE_URL = "https://api.listenbrainz.org/1"
MAX_PAGE_SIZE = 1000


class ListenBrainzClient:
    def __init__(
        self,
        http: httpx.Client,
        min_interval_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.http = http
        self.limiter = RateLimiter(min_interval_s, sleep, clock)

    @classmethod
    def create(cls, contact: str | None = None) -> "ListenBrainzClient":
        http = httpx.Client(
            base_url=BASE_URL,
            headers={"User-Agent": make_user_agent(contact), "Accept": "application/json"},
            timeout=30,
        )
        return cls(http)

    def listens_request(self, user: str, count: int, max_ts: int | None) -> httpx.Request:
        params: dict = {"count": count}
        if max_ts is not None:
            params["max_ts"] = max_ts
        path = f"/user/{quote(user, safe='')}/listens"
        return self.http.build_request("GET", path, params=params)

    def send(self, request: httpx.Request) -> dict:
        return send_json(self.http, self.limiter, request)


@dataclass
class ListensResult:
    pages_downloaded: int = 0
    listens_downloaded: int = 0


_WATERMARK = text(
    """
    SELECT extract(epoch FROM max(listened_at))::bigint
    FROM staging.listenbrainz_listens
    WHERE user_name = :user
    """
)

_INSERT_PAGE = text(
    """
    INSERT INTO raw.listenbrainz_listens (run_id, user_name, max_ts, request_url, payload)
    VALUES (:run_id, :user, :max_ts, :url, CAST(:payload AS jsonb))
    """
)


def extract_listens(
    engine: Engine,
    client: ListenBrainzClient,
    users: list[str],
    max_listens_per_user: int,
    run_id: str,
    page_size: int = 100,
) -> ListensResult:
    result = ListensResult()
    page_size = min(page_size, MAX_PAGE_SIZE)
    for user in sorted({u.strip() for u in users if u.strip()}):
        with engine.connect() as conn:
            watermark = conn.execute(_WATERMARK, {"user": user}).scalar()
        fetched = 0
        max_ts: int | None = None
        while fetched < max_listens_per_user:
            count = min(page_size, max_listens_per_user - fetched)
            request = client.listens_request(user, count, max_ts)
            payload = client.send(request)
            with engine.begin() as conn:
                conn.execute(
                    _INSERT_PAGE,
                    {
                        "run_id": run_id,
                        "user": user,
                        "max_ts": max_ts,
                        "url": str(request.url),
                        "payload": json.dumps(payload),
                    },
                )
            listens = payload.get("payload", {}).get("listens", [])
            result.pages_downloaded += 1
            result.listens_downloaded += len(listens)
            fetched += len(listens)
            if not listens:
                break
            oldest = min(listen["listened_at"] for listen in listens)
            if watermark is not None and oldest <= watermark:
                break
            max_ts = oldest
        logger.info("ListenBrainz %s: %d listens (watermark %s)", user, fetched, watermark)
    return result


@dataclass
class PublishListensResult:
    listeners_added: int
    artists_added: int
    tracks_added: int
    events_added: int


def publish_listens(engine: Engine) -> PublishListensResult:
    with engine.begin() as conn:
        listeners = conn.execute(
            text(
                """
                INSERT INTO public.listeners (username, listenbrainz_user)
                SELECT DISTINCT left('lb_' || user_name, 50), user_name
                FROM staging.listenbrainz_listens
                ON CONFLICT DO NOTHING
                """
            )
        ).rowcount
        artists = conn.execute(
            text(
                """
                INSERT INTO public.artists (name, mbid)
                SELECT DISTINCT ON (artist_mbid) left(artist_name, 200), artist_mbid
                FROM staging.listenbrainz_listens
                WHERE recording_mbid IS NOT NULL AND artist_mbid IS NOT NULL
                ORDER BY artist_mbid, listened_at DESC
                ON CONFLICT (mbid) DO NOTHING
                """
            )
        ).rowcount
        tracks = conn.execute(
            text(
                """
                INSERT INTO public.tracks (title, artist_id, duration_ms, mbid)
                SELECT DISTINCT ON (l.recording_mbid)
                    left(l.track_name, 300), a.id, l.duration_ms, l.recording_mbid
                FROM staging.listenbrainz_listens AS l
                JOIN public.artists AS a ON a.mbid = l.artist_mbid
                WHERE l.recording_mbid IS NOT NULL
                ORDER BY l.recording_mbid, l.duration_ms IS NULL, l.listened_at DESC
                ON CONFLICT (mbid) DO NOTHING
                """
            )
        ).rowcount
        events = conn.execute(
            text(
                """
                INSERT INTO public.listening_events (listener_id, track_id, listened_at)
                SELECT li.id, t.id, l.listened_at
                FROM staging.listenbrainz_listens AS l
                JOIN public.listeners AS li ON li.listenbrainz_user = l.user_name
                JOIN public.tracks AS t ON t.mbid = l.recording_mbid
                WHERE l.listened_at <= now()
                ON CONFLICT ON CONSTRAINT uq_listening_events_natural_key DO NOTHING
                """
            )
        ).rowcount
    return PublishListensResult(
        listeners_added=listeners,
        artists_added=artists,
        tracks_added=tracks,
        events_added=events,
    )
