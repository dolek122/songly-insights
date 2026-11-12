"""Data quality checks.

Each check is a SQL query that returns the rows BREAKING a rule, so "0 rows" means
the check passed. The same idea is used by dbt tests. A failing check with severity
"error" stops the pipeline; "warn" is only logged.
"""

import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Check:
    name: str
    sql: str
    severity: Literal["error", "warn"] = "error"


@dataclass(frozen=True)
class CheckResult:
    check: Check
    failing_rows: int

    @property
    def passed(self) -> bool:
        return self.failing_rows == 0


class DataQualityError(Exception):
    def __init__(self, failed: list[CheckResult]) -> None:
        names = ", ".join(f"{r.check.name} ({r.failing_rows} rows)" for r in failed)
        super().__init__(f"Data quality checks failed: {names}")
        self.failed = failed


# Checked before anything is built: is the data coming from the API sane?
SOURCE_CHECKS = [
    Check(
        "listening_events_not_in_future",
        # A small margin for clocks that are a bit off.
        "SELECT id FROM public.listening_events WHERE listened_at > now() + interval '1 hour'",
    ),
    Check(
        "tracks_shorter_than_2_hours",
        "SELECT id FROM public.tracks WHERE duration_ms > 2 * 60 * 60 * 1000",
        severity="warn",
    ),
]

STAGING_CHECKS = [
    Check(
        "musicbrainz_artists_mbid_unique",
        "SELECT mbid FROM staging.musicbrainz_artists GROUP BY mbid HAVING count(*) > 1",
    ),
    Check(
        "musicbrainz_artists_name_not_empty",
        "SELECT mbid FROM staging.musicbrainz_artists WHERE coalesce(artist_name, '') = ''",
    ),
    Check(
        "musicbrainz_tags_not_empty",
        "SELECT mbid FROM staging.musicbrainz_artist_tags WHERE coalesce(tag, '') = ''",
        severity="warn",
    ),
    Check(
        "musicbrainz_country_is_iso_code",
        "SELECT mbid FROM staging.musicbrainz_artists WHERE country !~ '^[A-Z]{2}$'",
        severity="warn",
    ),
]

MART_CHECKS = [
    # Reconciliation: the mart must contain exactly as many plays as staging.
    Check(
        "daily_listener_activity_matches_events",
        """
        SELECT 1
        WHERE (SELECT coalesce(sum(plays), 0) FROM marts.daily_listener_activity)
           <> (SELECT count(*) FROM staging.listening_events)
        """,
    ),
    Check(
        "artist_popularity_matches_events",
        """
        SELECT 1
        WHERE (SELECT coalesce(sum(total_plays), 0) FROM marts.artist_popularity)
           <> (SELECT count(*) FROM staging.listening_events)
        """,
    ),
    Check(
        "listener_track_daily_matches_events",
        """
        SELECT 1
        WHERE (SELECT coalesce(sum(plays), 0) FROM marts.listener_track_daily)
           <> (SELECT count(*) FROM staging.listening_events)
        """,
    ),
    Check(
        "listener_track_daily_first_before_last",
        "SELECT day FROM marts.listener_track_daily WHERE first_listened_at > last_listened_at",
    ),
    Check(
        "artist_popularity_listeners_not_above_plays",
        "SELECT artist_id FROM marts.artist_popularity WHERE unique_listeners > total_plays",
    ),
    Check(
        "daily_genre_plays_positive",
        "SELECT day FROM marts.daily_genre_plays WHERE plays <= 0",
    ),
]


def run_checks(engine: Engine, checks: list[Check]) -> list[CheckResult]:
    results = []
    with engine.connect() as conn:
        for check in checks:
            count_sql = text(f"SELECT count(*) FROM ({check.sql}) AS violations")
            result = CheckResult(check, conn.execute(count_sql).scalar_one())
            if not result.passed:
                logger.warning(
                    "DQ %s: %s failed (%d rows)",
                    check.severity,
                    check.name,
                    result.failing_rows,
                )
            results.append(result)
    return results


def ensure_passed(results: list[CheckResult]) -> None:
    """Raise when any check with severity "error" failed. Warnings do not stop the run."""
    failed = [r for r in results if not r.passed and r.check.severity == "error"]
    if failed:
        raise DataQualityError(failed)
