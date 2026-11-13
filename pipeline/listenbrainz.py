"""ListenBrainz ingestion: download a user's listens into raw, publish them as listening events.

API docs: https://listenbrainz.readthedocs.io/en/latest/users/api/core.html
Listens on ListenBrainz are public, but they are personal data: import only your own
account or accounts whose owners agreed (ADR 0009).
"""

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
MAX_PAGE_SIZE = 1000  # the API's own limit for `count`


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
        """Newest listens of `user`; with `max_ts` only listens strictly older than it."""
        params: dict = {"count": count}
        if max_ts is not None:
            params["max_ts"] = max_ts
        # quote(): user names may contain characters that are not allowed in a URL path.
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
    """Download listens into raw.listenbrainz_listens, newest first, going back in time.

    Incremental load: the newest listen we already have for a user is the "watermark".
    We page backwards (max_ts = oldest listen of the previous page) and stop as soon as
    a page reaches the watermark, so a rerun downloads only new listens. A page may
    overlap with known listens; staging removes such duplicates.

    Needs the staging views (the watermark is read from staging.listenbrainz_listens).
    """
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
                break  # no older listens
            oldest = min(listen["listened_at"] for listen in listens)
            if watermark is not None and oldest <= watermark:
                break  # reached listens we already have
            # max_ts is exclusive, so listens in the very same second as `oldest` but
            # cut off by `count` would be skipped. Rare; accepted (ADR 0009).
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
    """Turn staged ListenBrainz listens into listeners, artists, tracks and listening events.

    * every ListenBrainz user becomes a listener (username "lb_<name>"),
    * a listen is matched to a track by the recording mbid; a recording that is not in the
      catalog yet is created from the listen's own metadata (with its first artist),
      MusicBrainz data already in the catalog is never overwritten (DO NOTHING),
    * listens without a recording mbid cannot be matched and are skipped (a DQ warning
      counts them), listens from the future are skipped too (broken client clocks),
    * events use the same natural key as the API import (ADR 0002), so reruns add nothing.
    Requires the staging layer to be built first.
    """
    with engine.begin() as conn:
        listeners = conn.execute(
            text(
                """
                INSERT INTO public.listeners (username, listenbrainz_user)
                SELECT DISTINCT left('lb_' || user_name, 50), user_name
                FROM staging.listenbrainz_listens
                -- No conflict target: also skips a username that is already taken.
                ON CONFLICT DO NOTHING
                """
            )
        ).rowcount
        artists = conn.execute(
            text(
                """
                INSERT INTO public.artists (name, mbid)
                -- DISTINCT ON keeps one row per artist: the name from the newest listen.
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
                -- One row per recording: prefer a listen that knows the length
                -- (false sorts before true), then the newest one.
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
