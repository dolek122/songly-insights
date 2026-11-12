# Songly Insights

Music listening analytics API (FastAPI, SQLAlchemy 2.0 sync, Alembic, PostgreSQL 16) with a
Stage 2 data pipeline (Prefect) and Stage 3 behaviour analytics. Portfolio project; see the roadmap in README.md. The author is a junior developer who must
be able to explain every part of the code in an interview, so prefer simple, readable solutions
and explain non-obvious choices.

## Commands

- Database: `docker compose up -d db` (also creates the `insights_test` database)
- Install: `pip install -e ".[dev]"`, then `cp .env.example .env`
- Migrate: `alembic upgrade head`
- Seed: `python -m app.cli seed --reset`
- Run: `uvicorn app.main:app --reload` (statistics need `python -m pipeline run` first)
- Pipeline: `python -m pipeline run` (add `--musicbrainz-tag jazz` / `--listenbrainz-user name`
  to import MusicBrainz / ListenBrainz; needs internet)
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

## Pipeline (Stage 2, see ADRs 0005, 0006, 0008 and 0009)

- Schemas: `raw` (external data as received, append-only, created by migration 0002),
  `staging` (views, clean + rename only), `marts` (analytics tables). staging and marts are
  rebuilt from `pipeline/sql/*.sql` in one transaction on every run; edit the SQL files, not the DB.
- Logic lives in plain modules (`pipeline/layers.py`, `quality.py`, `musicbrainz.py`);
  `pipeline/flows.py` only wires them into Prefect tasks. Keep Prefect out of the other modules.
- Data quality checks are SQL returning violating rows; add one for every new mart.
- MusicBrainz: artists by tag and their recordings (browse) land in `raw`; both go through
  `_fetch_page` (cache + append). Recordings become `public.tracks` matched by mbid.
- Tests never call MusicBrainz: use `tests/pipeline_helpers.py` (httpx MockTransport).
  Database cleanup runs after every test (`clean_database`, autouse); add new raw tables there.
- ListenBrainz: listens are loaded incrementally (watermark = newest listen in staging, paging
  back with `max_ts`), matched to tracks by recording mbid; missing tracks/artists are created
  from listen metadata, never overwriting MusicBrainz data. `tracks.duration_ms` may be NULL.
- Both API clients share `pipeline/http.py` (RateLimiter, User-Agent).
- The pipeline writes to `public` only in `musicbrainz.publish_to_catalog` and
  `listenbrainz.publish_listens`; both are idempotent (ON CONFLICT).

## Statistics read marts (ADR 0007)

- `/stats/*` and `/listeners/{id}/summary` read `marts.listener_track_daily` (facts) joined with
  the catalog in `public` (names). Catalog and `/listening-events` endpoints read `public`.
- Windows must be whole UTC days (422 otherwise); responses carry `data_as_of`; missing marts
  give 503 `marts_not_ready`. Data is as fresh as the last `python -m pipeline run`.
- `app/marts.py` mirrors the mart columns in a separate MetaData (not Alembic): keep it in sync
  with `pipeline/sql/marts.sql`. Tests build marts with the `build_marts` fixture.

## Sessions, trends and similarity (Stage 3, ADRs 0010-0012)

- Sessions: `marts.listening_sessions` (gaps and islands, 30-minute gap, identified by
  listener + start, belong to the UTC day they started). Service: `app/services/sessions.py`.
- Trends: current window vs the previous window of the same length, ranked by absolute change;
  computed in `app/services/trends.py` from `listener_track_daily` (no extra mart).
- Similarity: cosine similarity of (artist -> plays) vectors, computed on request in
  `app/services/similarity.py` (CTEs over `listener_track_daily`); results explain themselves
  with `top_shared_artists`.
- `stats.filter_days()` applies window + listener filters to any mart with `day`/`listener_id`.
- The seed generator produces sessions and slow artist popularity trends; keep demo data realistic
  enough for new statistics to show something.
