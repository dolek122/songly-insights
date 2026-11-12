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
        "musicbrainz_recordings_mbid_unique",
        "SELECT recording_mbid FROM staging.musicbrainz_recordings "
        "GROUP BY recording_mbid HAVING count(*) > 1",
    ),
    Check(
        "musicbrainz_recordings_title_not_empty",
        "SELECT recording_mbid FROM staging.musicbrainz_recordings WHERE coalesce(title, '') = ''",
    ),
    Check(
        # Not an error: such recordings become tracks with an unknown length (ADR 0009).
        "musicbrainz_recordings_have_length",
        "SELECT recording_mbid FROM staging.musicbrainz_recordings WHERE length_ms IS NULL",
        severity="warn",
    ),
    Check(
        # Such listens cannot be matched to a track and are not imported.
        "listenbrainz_listens_have_recording_mbid",
        "SELECT user_name FROM staging.listenbrainz_listens WHERE recording_mbid IS NULL",
        severity="warn",
    ),
    Check(
        # Broken clocks in listening apps; these listens are skipped on import.
        "listenbrainz_listens_not_in_future",
        "SELECT user_name FROM staging.listenbrainz_listens WHERE listened_at > now()",
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
        # Runs at the end, after publishing: listens with a recording mbid that did not become
        # events, e.g. the recording is new and the listen has no artist mbid to create it.
        "listenbrainz_listens_not_imported",
        """
        SELECT l.user_name
        FROM staging.listenbrainz_listens AS l
        LEFT JOIN public.listeners AS li ON li.listenbrainz_user = l.user_name
        LEFT JOIN public.tracks AS t ON t.mbid = l.recording_mbid
        LEFT JOIN public.listening_events AS e
            ON e.listener_id = li.id AND e.track_id = t.id AND e.listened_at = l.listened_at
        WHERE l.recording_mbid IS NOT NULL AND l.listened_at <= now() AND e.id IS NULL
        """,
        severity="warn",
    ),
    Check(
        "listening_sessions_match_events",
        """
        SELECT 1
        WHERE (SELECT coalesce(sum(plays), 0) FROM marts.listening_sessions)
           <> (SELECT count(*) FROM staging.listening_events)
        """,
    ),
    Check(
        # The session rule itself: two sessions of a listener must be more than 30 minutes
        # apart (from the last play of one to the first play of the next).
        "listening_sessions_separated_by_gap",
        """
        SELECT started_at
        FROM (
            SELECT
                started_at,
                lag(last_play_at) OVER (PARTITION BY listener_id ORDER BY started_at) AS prev
            FROM marts.listening_sessions
        ) AS ordered
        WHERE started_at - prev <= interval '30 minutes'
        """,
    ),
    Check(
        "listening_sessions_end_after_start",
        "SELECT listener_id FROM marts.listening_sessions WHERE ended_at < started_at",
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
