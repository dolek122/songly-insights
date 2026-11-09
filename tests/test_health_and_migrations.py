from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base, get_db
from app.main import create_app
from tests.conftest import alembic_config, assert_error


def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_unreachable_database():
    # Port 1 is never a PostgreSQL server, so connecting fails immediately.
    broken = create_engine("postgresql+psycopg://user:pass@127.0.0.1:1/none")
    app = create_app()

    def broken_db():
        with Session(broken) as session:
            yield session

    app.dependency_overrides[get_db] = broken_db
    response = TestClient(app).get("/health")
    assert_error(response, 503, "database_unavailable")


def test_models_and_migrations_are_in_sync(engine):
    """Fails when a model was changed without a migration (or the other way round).

    Fix: alembic revision --autogenerate -m "describe the change"
    """
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"Models and migrations differ: {diff}"


def test_migrations_downgrade_and_upgrade_again(engine):
    config = alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")
