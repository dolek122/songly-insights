# Songly Insights

Music listening analytics API (FastAPI, SQLAlchemy 2.0 sync, Alembic, PostgreSQL 16). Stage 1 of a
larger portfolio project; see the roadmap in README.md. The author is a junior developer who must
be able to explain every part of the code in an interview, so prefer simple, readable solutions
and explain non-obvious choices.

## Commands

- Database: `docker compose up -d db` (also creates the `insights_test` database)
- Install: `pip install -e ".[dev]"`, then `cp .env.example .env`
- Migrate: `alembic upgrade head`
- Seed: `python -m app.cli seed --reset`
- Run: `uvicorn app.main:app --reload`
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

## Next: Stage 2 (data pipeline)

Raw -> staging -> marts layers in PostgreSQL, orchestration (Airflow or Prefect), data quality
tests, ingestion of MusicBrainz data. Keep the API working while the pipeline is added.
