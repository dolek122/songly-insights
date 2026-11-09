"""Command line tools. Usage: python -m app.cli seed --reset"""

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Listener
from app.seed import generator, loader


def cmd_seed(args: argparse.Namespace) -> int:
    data = generator.generate(
        seed=args.seed,
        artists=args.artists,
        listeners=args.listeners,
        events_per_listener=args.events_per_listener,
        days=args.days,
    )
    with SessionLocal() as session:
        if args.reset:
            loader.reset(session)
        elif _has_data(session):
            print(
                "Database already has data. Use --reset to replace it "
                "(catalog rows would otherwise be duplicated).",
                file=sys.stderr,
            )
            return 1
        result = loader.load(session, data)
    print(
        f"Seeded {result.genres} genres, {result.artists} artists, {result.tracks} tracks, "
        f"{result.listeners} listeners, {result.events_inserted} listening events "
        f"({result.events_duplicates} duplicates skipped)."
    )
    return 0


def _has_data(session: Session) -> bool:
    return session.scalar(select(Listener.id).limit(1)) is not None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    seed = commands.add_parser("seed", help="Fill the database with synthetic data")
    seed.add_argument("--reset", action="store_true", help="Delete all existing data first")
    seed.add_argument("--seed", type=int, default=42, help="Random seed (same seed = same data)")
    seed.add_argument("--artists", type=int, default=60)
    seed.add_argument("--listeners", type=int, default=25)
    seed.add_argument("--events-per-listener", type=int, default=400)
    seed.add_argument("--days", type=int, default=90, help="Events end on 2026-01-01 UTC")
    seed.set_defaults(handler=cmd_seed)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
