"""Prefect flow that runs the whole pipeline (ADR 0005).

Prefect adds what a plain script lacks: retries, logs and state of every step,
a UI (`prefect server start`) and schedules (`python -m pipeline serve`).
The steps themselves live in plain modules; tasks here only call them.
"""

from prefect import flow, get_run_logger, task
from prefect.runtime import flow_run
from sqlalchemy import Engine

from app import db
from app.config import get_settings
from pipeline import layers, listenbrainz, musicbrainz, quality, runs


def get_engine() -> Engine:
    # A function (not a module constant) so tests can point the flow at the test database.
    return db.engine


@task
def check_quality(layer: str, checks: list[quality.Check]) -> int:
    """Run checks; raise on a failed "error" check. Returns the number of failed warnings."""
    logger = get_run_logger()
    results = quality.run_checks(get_engine(), checks)
    for r in results:
        status = "ok" if r.passed else f"FAILED ({r.failing_rows} rows, {r.check.severity})"
        logger.info("DQ %s / %s: %s", layer, r.check.name, status)
    quality.ensure_passed(results)
    return sum(1 for r in results if not r.passed)


# MusicBrainz sometimes answers 503 when it is busy; waiting and trying again usually helps.
@task(retries=3, retry_delay_seconds=30)
def extract_musicbrainz(tags: list[str], artists_per_tag: int) -> musicbrainz.ExtractResult:
    client = musicbrainz.MusicBrainzClient.create(get_settings().musicbrainz_contact)
    result = musicbrainz.extract_artists_by_tag(
        get_engine(), client, tags, artists_per_tag, run_id=str(flow_run.id or "local")
    )
    get_run_logger().info("MusicBrainz: %s", result)
    return result


@task(retries=3, retry_delay_seconds=30)
def extract_musicbrainz_recordings(recordings_per_artist: int) -> musicbrainz.ExtractResult:
    client = musicbrainz.MusicBrainzClient.create(get_settings().musicbrainz_contact)
    result = musicbrainz.extract_recordings(
        get_engine(), client, recordings_per_artist, run_id=str(flow_run.id or "local")
    )
    get_run_logger().info("MusicBrainz recordings: %s", result)
    return result


@task(retries=3, retry_delay_seconds=30)
def extract_listenbrainz(users: list[str], listens_per_user: int) -> listenbrainz.ListensResult:
    client = listenbrainz.ListenBrainzClient.create(get_settings().musicbrainz_contact)
    result = listenbrainz.extract_listens(
        get_engine(), client, users, listens_per_user, run_id=str(flow_run.id or "local")
    )
    get_run_logger().info("ListenBrainz: %s", result)
    return result


@task
def publish_listenbrainz() -> listenbrainz.PublishListensResult:
    result = listenbrainz.publish_listens(get_engine())
    get_run_logger().info("ListenBrainz published: %s", result)
    return result


@task
def build_staging() -> None:
    layers.build_staging(get_engine())


@task
def publish_musicbrainz(tags: list[str]) -> musicbrainz.PublishResult:
    result = musicbrainz.publish_to_catalog(get_engine(), tags)
    get_run_logger().info("Published to catalog: %s", result)
    return result


@task
def build_marts() -> None:
    layers.build_marts(get_engine())


@flow(name="songly-pipeline")
def songly_pipeline(
    musicbrainz_tags: list[str] | None = None,
    artists_per_tag: int = 25,
    recordings_per_artist: int = 25,
    listenbrainz_users: list[str] | None = None,
    listens_per_user: int = 1000,
) -> None:
    """sources -> (MusicBrainz, ListenBrainz -> raw) -> staging -> (catalog) -> marts.

    Data quality checks run between the steps. Without `musicbrainz_tags` and
    `listenbrainz_users` only the API data is processed (no network needed).
    `recordings_per_artist=0` skips downloading recordings.
    """
    # Every run is recorded in ops.pipeline_runs, also a failed one (for monitoring).
    run_id = runs.start_run(get_engine(), str(flow_run.id or "local"))
    warnings = 0
    try:
        warnings += check_quality("sources", quality.SOURCE_CHECKS)
        if musicbrainz_tags:
            extract_musicbrainz(musicbrainz_tags, artists_per_tag)
        build_staging()
        # The next two steps run after build_staging because they read staging views
        # (the artist list, the newest known listen). Views read raw live, so whatever
        # they download is visible in staging right away.
        if musicbrainz_tags and recordings_per_artist > 0:
            extract_musicbrainz_recordings(recordings_per_artist)
        if listenbrainz_users:
            extract_listenbrainz(listenbrainz_users, listens_per_user)
        warnings += check_quality("staging", quality.STAGING_CHECKS)
        if musicbrainz_tags:
            # Staging views read the catalog live, so new artists reach the marts in this run.
            publish_musicbrainz(musicbrainz_tags)
        if listenbrainz_users:
            # After MusicBrainz: tracks it created (with lengths and genres) are reused.
            publish_listenbrainz()
        build_marts()
        warnings += check_quality("marts", quality.MART_CHECKS)
    except Exception as exc:
        errors = len(exc.failed) if isinstance(exc, quality.DataQualityError) else 0
        runs.finish_run(get_engine(), run_id, "failed", warnings, errors, str(exc))
        raise
    runs.finish_run(get_engine(), run_id, "completed", warnings, 0)
