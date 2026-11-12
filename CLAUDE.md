# Songly Insights

Music listening analytics API (FastAPI, SQLAlchemy 2.0 sync, Alembic, PostgreSQL 16) with a
Stage 2 data pipeline (Prefect). Portfolio project; see the roadmap in README.md. The author is a junior developer who must
be able to explain every part of the code in an interview, so prefer simple, readable solutions
and explain non-obvious choices.

## Commands

- Database: `docker compose up -d db` (also creates the `insights_test` database)
- Install: `pip install -e ".[dev]"`, then `cp .env.example .env`
- Migrate: `alembic upgrade head`
- Seed: `python -m app.cli seed --reset`
- Run: `uvicorn app.main:app --reload` (statistics need `python -m pipeline run` first)
- Pipeline: `python -m pipeline run` (add `--musicbrainz-tag jazz` to import MusicBrainz; needs internet)
- Tests: `pytest` (needs PostgreSQL; the schema is built from the real migrations)
- Quality gate before every commit: `ruff check . && ruff format --check . && pytest`

## Conventions

- Code, comments and commit messages in English. README and ADRs are in Polish.
- Any model change needs an Alembic migration (`alembic revision --autogenerate -m "..."`);
  `tests/test_health_and_migrations.py` fails when models and migrations drift apart.
- Every new endpoint gets tests, including error cases. All errors use the shape
  `{"error": {"code", "message", "details"?}}` (see `app/errors.py`).
- Aggregation logic lives in `app/services`, routers stay thin.
- Record important decisions as a short ADR in `docs/adr/` (context, decision, consequences).
- Never commit `.env` or secrets.

## Domain rules (see ADRs 0002 and 0003)

- A listening event is unique by `(listener_id, track_id, listened_at)`; bulk import is idempotent.
- Time windows are half-open: `from` inclusive, `to` exclusive. Days are computed in UTC.
- A play counts towards every genre of its artist.
- Do not build features on the Spotify Web API: new apps lost most endpoints in 2024-2026.
  Data comes from the synthetic generator, MusicBrainz and optionally ListenBrainz (ADR 0004).

## Pipeline (Stage 2, see ADRs 0005 and 0006)

- Schemas: `raw` (external data as received, append-only, created by migration 0002),
  `staging` (views, clean + rename only), `marts` (analytics tables). staging and marts are
  rebuilt from `pipeline/sql/*.sql` in one transaction on every run; edit the SQL files, not the DB.
- Logic lives in plain modules (`pipeline/layers.py`, `quality.py`, `musicbrainz.py`);
  `pipeline/flows.py` only wires them into Prefect tasks. Keep Prefect out of the other modules.
- Data quality checks are SQL returning violating rows; add one for every new mart.
- Tests never call MusicBrainz: use `tests/pipeline_helpers.py` (httpx MockTransport).
- The pipeline writes to `public` only in `publish_to_catalog`.

## Statistics read marts (ADR 0007)

- `/stats/*` and `/listeners/{id}/summary` read `marts.listener_track_daily` (facts) joined with
  the catalog in `public` (names). Catalog and `/listening-events` endpoints read `public`.
- Windows must be whole UTC days (422 otherwise); responses carry `data_as_of`; missing marts
  give 503 `marts_not_ready`. Data is as fresh as the last `python -m pipeline run`.
- `app/marts.py` mirrors the mart columns in a separate MetaData (not Alembic): keep it in sync
  with `pipeline/sql/marts.sql`. Tests build marts with the `build_marts` fixture.
