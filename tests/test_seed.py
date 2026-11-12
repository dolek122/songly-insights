from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app import cli
from app.models import Artist, ListeningEvent
from app.seed import generator, loader

SMALL = {"artists": 5, "listeners": 3, "events_per_listener": 20, "days": 7}


def test_generator_is_deterministic():
    assert generator.generate(seed=1, **SMALL) == generator.generate(seed=1, **SMALL)
    assert generator.generate(seed=1, **SMALL) != generator.generate(seed=2, **SMALL)


def test_generated_events_fit_the_window():
    end = datetime(2026, 1, 1, tzinfo=UTC)
    data = generator.generate(seed=3, end=end, **SMALL)

    assert len(data.events) == 3 * 20
    assert all(end - timedelta(days=7) <= e.listened_at < end for e in data.events)
    assert all(1 <= len(a.genres) <= 3 for a in data.artists)


def test_loader_writes_dataset_and_is_idempotent_for_events(db):
    data = generator.generate(seed=4, **SMALL)

    first = loader.load(db, data)

    assert first.artists == 5
    assert first.events_inserted + first.events_duplicates == 60
    assert db.scalar(select(func.count()).select_from(Artist)) == 5

    loader.reset(db)
    assert db.scalar(select(func.count()).select_from(ListeningEvent)) == 0


def test_cli_seed_refuses_to_mix_with_existing_data(engine, db, monkeypatch, capsys):
    # Point the CLI at the test database instead of the development one.
    monkeypatch.setattr(cli, "SessionLocal", sessionmaker(bind=engine))
    args = ["seed", "--artists", "3", "--listeners", "2", "--events-per-listener", "5"]

    assert cli.main(args) == 0
    assert "Seeded 16 genres, 3 artists" in capsys.readouterr().out

    assert cli.main(args) == 1  # data exists and --reset was not given
    assert "--reset" in capsys.readouterr().err

    assert cli.main([*args, "--reset"]) == 0
    assert db.scalar(select(func.count()).select_from(Artist)) == 3


def test_generator_creates_listening_sessions():
    data = generator.generate(seed=5, **SMALL)
    first_listener = sorted(e.listened_at for e in data.events if e.listener_index == 0)

    gaps = [b - a for a, b in zip(first_listener, first_listener[1:], strict=False)]
    within_session = [g for g in gaps if g <= timedelta(minutes=30)]

    # Most plays follow the previous one closely: plays come in sessions.
    assert len(within_session) > len(gaps) / 2
