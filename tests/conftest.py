"""Test setup.

* The test database (TEST_DATABASE_URL) is wiped once per test run and rebuilt from the real
  Alembic migrations, so the tests also prove that the migrations work.
* After every test all tables are truncated and the derived schemas dropped,
  so tests cannot affect each other.
* The API under test gets its sessions from the test database via a dependency override.
"""

from collections.abc import Iterator
from datetime import datetime

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db import get_db
from app.main import create_app
from app.models import Artist, Genre, Listener, ListeningEvent, Track
from app.seed.loader import TABLES
from pipeline import layers

TEST_DATABASE_URL = get_settings().test_database_url


def alembic_config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))
    return config


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        # Pipeline schemas first: staging views depend on tables in public.
        conn.execute(text("DROP SCHEMA IF EXISTS marts, staging, raw, ops CASCADE"))
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
def clean_database(engine: Engine) -> Iterator[None]:
    """Runs after EVERY test (autouse), also tests that use `engine` without `db`."""
    yield
    with engine.begin() as conn:
        tables = [
            *TABLES,
            "raw.musicbrainz_artist_search",
            "raw.musicbrainz_recording_browse",
            "raw.listenbrainz_listens",
            "ops.pipeline_runs",
        ]
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        # staging and marts are fully derived; the pipeline creates them again when needed.
        conn.execute(text("DROP SCHEMA IF EXISTS marts, staging CASCADE"))


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app = create_app()

    def test_db() -> Iterator[Session]:
        yield db
        # A real request closes its session; that ends its transaction and releases its
        # locks. Without this, a read of the marts would block the next pipeline rebuild.
        db.rollback()

    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as test_client:
        yield test_client


class Factory:
    """Small helpers that insert rows directly, so tests can focus on what they check."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _save(self, obj):
        self.session.add(obj)
        self.session.commit()
        return obj

    def genre(self, name: str) -> Genre:
        return self._save(Genre(name=name))

    def artist(self, name: str = "Artist", genres: list[Genre] | None = None) -> Artist:
        return self._save(Artist(name=name, genres=genres or []))

    def track(
        self, artist: Artist, title: str = "Track", duration_ms: int | None = 200_000
    ) -> Track:
        return self._save(Track(title=title, artist_id=artist.id, duration_ms=duration_ms))

    def listener(self, username: str = "alice") -> Listener:
        return self._save(Listener(username=username))

    def plays(self, listener: Listener, track: Track, *moments: datetime) -> None:
        self.session.add_all(
            ListeningEvent(listener_id=listener.id, track_id=track.id, listened_at=m)
            for m in moments
        )
        self.session.commit()


@pytest.fixture
def factory(db: Session) -> Factory:
    return Factory(db)


@pytest.fixture
def build_marts(engine: Engine):
    """Run the pipeline's SQL (staging + marts). Statistics endpoints read the marts."""

    def build() -> None:
        layers.build_staging(engine)
        layers.build_marts(engine)

    return build


def assert_error(response, status: int, code: str) -> dict:
    """Check the common error shape {"error": {"code", "message", "details"?}}."""
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert set(body["error"]) <= {"code", "message", "details"}
    return body["error"]
