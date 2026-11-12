"""MusicBrainz ingestion: search artists by tag, land responses in raw, publish to the catalog.

API docs: https://musicbrainz.org/doc/MusicBrainz_API
Rules we follow (otherwise MusicBrainz blocks the client):
* at most 1 request per second,
* a User-Agent that names the application and a way to contact its author.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

BASE_URL = "https://musicbrainz.org/ws/2"
MAX_PAGE_SIZE = 100  # the API's own limit for `limit`


def make_user_agent(contact: str | None) -> str:
    agent = "songly-insights/0.1"
    return f"{agent} ( {contact} )" if contact else agent


def normalize_tag(tag: str) -> str:
    return " ".join(tag.lower().split())


class MusicBrainzClient:
    """Thin wrapper over httpx that respects the rate limit.

    `sleep` and `clock` can be replaced in tests, so tests do not really wait.
    """

    def __init__(
        self,
        http: httpx.Client,
        min_interval_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.http = http
        self.min_interval_s = min_interval_s
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None

    @classmethod
    def create(cls, contact: str | None = None) -> "MusicBrainzClient":
        http = httpx.Client(
            base_url=BASE_URL,
            headers={"User-Agent": make_user_agent(contact), "Accept": "application/json"},
            timeout=30,
        )
        return cls(http)

    def artist_search_request(self, tag: str, limit: int, offset: int) -> httpx.Request:
        # Quotes make a multi-word tag ("hip hop") one search term.
        params = {"query": f'tag:"{tag}"', "limit": limit, "offset": offset, "fmt": "json"}
        return self.http.build_request("GET", "/artist", params=params)

    def send(self, request: httpx.Request) -> dict:
        self._wait_for_rate_limit()
        response = self.http.send(request)
        # 503 means "too many requests" on MusicBrainz. We raise; the Prefect task retries.
        response.raise_for_status()
        return response.json()

    def _wait_for_rate_limit(self) -> None:
        now = self._clock()
        if self._last_request_at is not None:
            wait = self.min_interval_s - (now - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
                now += wait
        self._last_request_at = now


@dataclass
class ExtractResult:
    pages_downloaded: int = 0
    pages_from_cache: int = 0


_CACHED_PAGE = text(
    """
    SELECT payload FROM raw.musicbrainz_artist_search
    WHERE request_url = :url AND loaded_at > now() - make_interval(days => :max_age_days)
    ORDER BY loaded_at DESC
    LIMIT 1
    """
)

_INSERT_PAGE = text(
    """
    INSERT INTO raw.musicbrainz_artist_search (run_id, tag, page_offset, request_url, payload)
    VALUES (:run_id, :tag, :page_offset, :url, CAST(:payload AS jsonb))
    """
)


def extract_artists_by_tag(
    engine: Engine,
    client: MusicBrainzClient,
    tags: list[str],
    artists_per_tag: int,
    run_id: str,
    max_age_days: int = 30,
) -> ExtractResult:
    """Download artist search pages for each tag into raw.musicbrainz_artist_search.

    raw is append-only: we never update or delete there. A page downloaded less than
    `max_age_days` ago is not downloaded again (raw doubles as a cache), which keeps
    reruns fast and polite to MusicBrainz.
    """
    result = ExtractResult()
    page_size = min(MAX_PAGE_SIZE, artists_per_tag)
    for tag in sorted({normalize_tag(t) for t in tags}):
        for offset in range(0, artists_per_tag, page_size):
            request = client.artist_search_request(tag, page_size, offset)
            url = str(request.url)
            with engine.connect() as conn:
                payload = conn.execute(
                    _CACHED_PAGE, {"url": url, "max_age_days": max_age_days}
                ).scalar()
            if payload is not None:
                result.pages_from_cache += 1
            else:
                payload = client.send(request)
                with engine.begin() as conn:
                    conn.execute(
                        _INSERT_PAGE,
                        {
                            "run_id": run_id,
                            "tag": tag,
                            "page_offset": offset,
                            "url": url,
                            "payload": json.dumps(payload),
                        },
                    )
                result.pages_downloaded += 1
            artists_on_page = len(payload.get("artists", []))
            logger.info("MusicBrainz tag=%r offset=%d: %d artists", tag, offset, artists_on_page)
            if artists_on_page < page_size:
                break  # last page: no more artists with this tag
    return result


@dataclass
class PublishResult:
    artists_upserted: int
    genre_links_added: int


def publish_to_catalog(engine: Engine, tags: list[str]) -> PublishResult:
    """Copy MusicBrainz artists from staging into the API catalog (schema public).

    * every searched tag becomes a genre (if it does not exist yet),
    * artists are matched by mbid: new ones are inserted, known ones get the current name,
    * an artist is linked to every existing genre that matches one of its tags with
      a positive vote count.
    Running it twice changes nothing (ON CONFLICT), so it is safe to retry.
    Requires the staging layer to be built first.
    """
    genre_names = sorted({normalize_tag(t) for t in tags})
    with engine.begin() as conn:
        conn.execute(
            # unnest() turns the array into rows; the CAST tells PostgreSQL its element type.
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
                SELECT artist_name, mbid FROM staging.musicbrainz_artists
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
    return PublishResult(artists_upserted=artists, genre_links_added=links)
