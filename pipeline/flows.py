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
from pipeline import layers, musicbrainz, quality


def get_engine() -> Engine:
    # A function (not a module constant) so tests can point the flow at the test database.
    return db.engine


@task
def check_quality(layer: str, checks: list[quality.Check]) -> None:
    logger = get_run_logger()
    results = quality.run_checks(get_engine(), checks)
    for r in results:
        status = "ok" if r.passed else f"FAILED ({r.failing_rows} rows, {r.check.severity})"
        logger.info("DQ %s / %s: %s", layer, r.check.name, status)
    quality.ensure_passed(results)


# MusicBrainz sometimes answers 503 when it is busy; waiting and trying again usually helps.
@task(retries=3, retry_delay_seconds=30)
def extract_musicbrainz(tags: list[str], artists_per_tag: int) -> musicbrainz.ExtractResult:
    client = musicbrainz.MusicBrainzClient.create(get_settings().musicbrainz_contact)
    result = musicbrainz.extract_artists_by_tag(
        get_engine(), client, tags, artists_per_tag, run_id=str(flow_run.id or "local")
    )
    get_run_logger().info("MusicBrainz: %s", result)
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
def songly_pipeline(musicbrainz_tags: list[str] | None = None, artists_per_tag: int = 25) -> None:
    """sources -> (MusicBrainz -> raw) -> staging -> (catalog) -> marts, with checks between.

    Without `musicbrainz_tags` only the API data is processed (no network needed).
    """
    check_quality("sources", quality.SOURCE_CHECKS)
    if musicbrainz_tags:
        extract_musicbrainz(musicbrainz_tags, artists_per_tag)
    build_staging()
    check_quality("staging", quality.STAGING_CHECKS)
    if musicbrainz_tags:
        # Staging views read the catalog live, so new artists reach the marts in this run.
        publish_musicbrainz(musicbrainz_tags)
    build_marts()
    check_quality("marts", quality.MART_CHECKS)
