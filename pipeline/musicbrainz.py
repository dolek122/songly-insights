import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy import Engine, text

from pipeline.http import RateLimiter, make_user_agent, send_json

logger = logging.getLogger(__name__)

BASE_URL = "https://musicbrainz.org/ws/2"
MAX_PAGE_SIZE = 100


def normalize_tag(tag: str) -> str:
    return " ".join(tag.lower().split())


class MusicBrainzClient:
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
    def create(cls, contact: str | None = None) -> "MusicBrainzClient":
        http = httpx.Client(
            base_url=BASE_URL,
            headers={"User-Agent": make_user_agent(contact), "Accept": "application/json"},
            timeout=30,
        )
        return cls(http)

    def artist_search_request(self, tag: str, limit: int, offset: int) -> httpx.Request:
        params = {"query": f'tag:"{tag}"', "limit": limit, "offset": offset, "fmt": "json"}
        return self.http.build_request("GET", "/artist", params=params)

    def recording_browse_request(self, artist_mbid: str, limit: int, offset: int) -> httpx.Request:
        params = {"artist": artist_mbid, "limit": limit, "offset": offset, "fmt": "json"}
        return self.http.build_request("GET", "/recording", params=params)

    def send(self, request: httpx.Request) -> dict:
        return send_json(self.http, self.limiter, request)


@dataclass
class ExtractResult:
    pages_downloaded: int = 0
    pages_from_cache: int = 0


def _fetch_page(
    engine: Engine,
    client: MusicBrainzClient,
    request: httpx.Request,
    table: str,
    columns: dict,
    max_age_days: int,
    result: ExtractResult,
) -> dict:
    url = str(request.url)
    cached = text(
        f"""
        SELECT payload FROM {table}
        WHERE request_url = :url AND loaded_at > now() - make_interval(days => :max_age_days)
        ORDER BY loaded_at DESC
        LIMIT 1
        """
    )
    with engine.connect() as conn:
        payload = conn.execute(cached, {"url": url, "max_age_days": max_age_days}).scalar()
    if payload is not None:
        result.pages_from_cache += 1
        return payload

    payload = client.send(request)
    names = ", ".join(columns)
    values = ", ".join(f":{name}" for name in columns)
    insert = text(
        f"INSERT INTO {table} ({names}, request_url, payload) "
        f"VALUES ({values}, :url, CAST(:payload AS jsonb))"
    )
    with engine.begin() as conn:
        conn.execute(insert, {**columns, "url": url, "payload": json.dumps(payload)})
    result.pages_downloaded += 1
    return payload


def extract_artists_by_tag(
    engine: Engine,
    client: MusicBrainzClient,
    tags: list[str],
    artists_per_tag: int,
    run_id: str,
    max_age_days: int = 30,
) -> ExtractResult:
    result = ExtractResult()
    page_size = min(MAX_PAGE_SIZE, artists_per_tag)
    for tag in sorted({normalize_tag(t) for t in tags}):
        for offset in range(0, artists_per_tag, page_size):
            size = min(page_size, artists_per_tag - offset)
            payload = _fetch_page(
                engine,
                client,
                client.artist_search_request(tag, size, offset),
                table="raw.musicbrainz_artist_search",
                columns={"run_id": run_id, "tag": tag, "page_offset": offset},
                max_age_days=max_age_days,
                result=result,
            )
            artists_on_page = len(payload.get("artists", []))
            logger.info("MusicBrainz tag=%r offset=%d: %d artists", tag, offset, artists_on_page)
            if artists_on_page < size:
                break
    return result


def extract_recordings(
    engine: Engine,
    client: MusicBrainzClient,
    recordings_per_artist: int,
    run_id: str,
    max_age_days: int = 30,
) -> ExtractResult:
    with engine.connect() as conn:
        artist_mbids = list(
            conn.execute(
                text("SELECT mbid::text FROM staging.musicbrainz_artists ORDER BY mbid")
            ).scalars()
        )
    result = ExtractResult()
    page_size = min(MAX_PAGE_SIZE, recordings_per_artist)
    for mbid in artist_mbids:
        for offset in range(0, recordings_per_artist, page_size):
            size = min(page_size, recordings_per_artist - offset)
            payload = _fetch_page(
                engine,
                client,
                client.recording_browse_request(mbid, size, offset),
                table="raw.musicbrainz_recording_browse",
                columns={"run_id": run_id, "artist_mbid": mbid, "page_offset": offset},
                max_age_days=max_age_days,
                result=result,
            )
            if len(payload.get("recordings", [])) < size:
                break
    logger.info("MusicBrainz recordings of %d artists: %s", len(artist_mbids), result)
    return result


@dataclass
class PublishResult:
    artists_upserted: int
    genre_links_added: int
    tracks_upserted: int


def publish_to_catalog(engine: Engine, tags: list[str]) -> PublishResult:
    genre_names = sorted({normalize_tag(t) for t in tags})
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.genres (name) "
                "SELECT unnest(CAST(:names AS text[])) ON CONFLICT DO NOTHING"
            ),
            {"names": genre_names},
        )
        artists = conn.execute(
            text(
                """
                INSERT INTO public.artists (name, mbid)
                SELECT left(artist_name, 200), mbid FROM staging.musicbrainz_artists
                ON CONFLICT (mbid) DO UPDATE SET name = EXCLUDED.name
                """
            )
        ).rowcount
        links = conn.execute(
            text(
                """
                INSERT INTO public.artist_genres (artist_id, genre_id)
                SELECT DISTINCT a.id, g.id
                FROM staging.musicbrainz_artist_tags AS t
                JOIN public.artists AS a ON a.mbid = t.mbid
                JOIN public.genres AS g ON g.name = t.tag
                WHERE t.votes > 0
                ON CONFLICT DO NOTHING
                """
            )
        ).rowcount
        tracks = conn.execute(
            text(
                """
                INSERT INTO public.tracks (title, artist_id, duration_ms, mbid)
                SELECT left(r.title, 300), a.id, nullif(r.length_ms, 0), r.recording_mbid
                FROM staging.musicbrainz_recordings AS r
                JOIN public.artists AS a ON a.mbid = r.artist_mbid
                WHERE NOT r.is_video
                ON CONFLICT (mbid) DO UPDATE SET
                    title = EXCLUDED.title,
                    duration_ms = coalesce(EXCLUDED.duration_ms, tracks.duration_ms)
                """
            )
        ).rowcount
    return PublishResult(artists_upserted=artists, genre_links_added=links, tracks_upserted=tracks)
