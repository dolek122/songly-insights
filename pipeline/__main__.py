"""Usage:
python -m pipeline run                               # API data only
python -m pipeline run --musicbrainz-tag jazz --musicbrainz-tag rock
python -m pipeline serve --cron "15 3 * * *"         # run on a schedule
"""

import argparse

from pipeline.flows import songly_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in [("run", "Run the pipeline once"), ("serve", "Run on a schedule")]:
        cmd = commands.add_parser(name, help=help_text)
        cmd.add_argument(
            "--musicbrainz-tag",
            action="append",
            dest="tags",
            help="Import MusicBrainz artists with this tag (repeatable). Needs internet.",
        )
        cmd.add_argument("--artists-per-tag", type=int, default=25)
        cmd.add_argument(
            "--recordings-per-artist",
            type=int,
            default=25,
            help="Recordings to import per MusicBrainz artist (0 = none)",
        )
        if name == "serve":
            cmd.add_argument("--cron", default="15 3 * * *", help="Schedule, UTC (cron syntax)")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    params = {
        "musicbrainz_tags": args.tags,
        "artists_per_tag": args.artists_per_tag,
        "recordings_per_artist": args.recordings_per_artist,
    }
    if args.command == "run":
        songly_pipeline(**params)
    else:
        # Keeps running and starts the flow according to the cron schedule.
        songly_pipeline.serve(name="daily", cron=args.cron, parameters=params)


if __name__ == "__main__":
    main()
