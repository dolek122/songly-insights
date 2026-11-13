"""Deterministic synthetic data generator.

The same `seed` always produces the same data, so demos and bug reports are reproducible.
The data is random but shaped a little like real listening:
* every listener has a few favourite genres and mostly plays artists from them,
* a few artists are much more popular than the rest (weights fall off like 1/rank),
* more plays happen in the evening than at night,
* plays come in listening sessions of 1-12 tracks played one after another,
* each artist slowly gains or loses popularity over the period (a trend).

Generation is pure Python (no database), which makes it easy to test.
"""

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

GENRES = [
    "rock", "pop", "jazz", "hip hop", "electronic", "classical", "metal", "folk",
    "blues", "reggae", "punk", "soul", "indie", "ambient", "country", "funk",
]  # fmt: skip

_ADJECTIVES = [
    "Silent", "Electric", "Golden", "Velvet", "Broken", "Neon", "Wild", "Midnight",
    "Crimson", "Hollow", "Lunar", "Paper", "Iron", "Static", "Northern", "Glass",
]  # fmt: skip
_NOUNS = [
    "Wolves", "Rivers", "Echoes", "Machines", "Gardens", "Signals", "Tides", "Ghosts",
    "Lanterns", "Engines", "Foxes", "Satellites", "Mirrors", "Orchards", "Comets", "Harbors",
]  # fmt: skip
_TITLE_WORDS = [
    "love", "night", "city", "fire", "dream", "rain", "home", "light", "summer", "heart",
    "road", "ocean", "shadow", "gold", "storm", "morning", "stars", "river", "echo", "time",
]  # fmt: skip
_COUNTRIES = ["PL", "DE", "GB", "US", "FR", "SE", "ES", "IT", "NL", "CZ"]

# Relative chance of a play in each UTC hour, 0..23: quiet nights, busy evenings.
HOUR_WEIGHTS = [1, 1, 1, 1, 1, 1, 2, 4, 5, 4, 4, 5, 6, 5, 5, 5, 6, 7, 9, 10, 10, 8, 5, 2]


@dataclass
class SyntheticArtist:
    name: str
    genres: list[str]


@dataclass
class SyntheticTrack:
    title: str
    artist_index: int
    duration_ms: int


@dataclass
class SyntheticEvent:
    listener_index: int
    track_index: int
    listened_at: datetime


@dataclass
class SyntheticDataset:
    genres: list[str]
    artists: list[SyntheticArtist]
    tracks: list[SyntheticTrack]
    listeners: list[tuple[str, str]]  # (username, country)
    events: list[SyntheticEvent] = field(default_factory=list)


def generate(
    *,
    seed: int = 42,
    artists: int = 60,
    tracks_per_artist: int = 8,
    listeners: int = 25,
    events_per_listener: int = 400,
    days: int = 90,
    end: datetime | None = None,
) -> SyntheticDataset:
    """Build a dataset. Events fall into the half-open window [end - days, end)."""
    rng = random.Random(seed)
    end = end or datetime(2026, 1, 1, tzinfo=UTC)
    start = end - timedelta(days=days)

    artist_list = _make_artists(rng, artists)
    track_list = _make_tracks(rng, artist_list, tracks_per_artist)
    listener_list = [(f"listener_{i + 1:03d}", rng.choice(_COUNTRIES)) for i in range(listeners)]

    # Popularity by rank: artist 0 is the most popular, weight 1/(rank+1).
    popularity = [1 / (rank + 1) for rank in range(len(artist_list))]
    rng.shuffle(popularity)
    tracks_by_artist: dict[int, list[int]] = {}
    for index, track in enumerate(track_list):
        tracks_by_artist.setdefault(track.artist_index, []).append(index)

    # Trend of each artist over the whole period, from -0.8 (fading) to +0.8 (rising).
    # It makes /stats/trending-* show something more than random noise.
    trends = [rng.uniform(-0.8, 0.8) for _ in artist_list]

    events = []
    for listener_index in range(listeners):
        favourite_genres = set(rng.sample(GENRES, k=3))
        # Favourite-genre artists are 5x more likely to be played by this listener.
        base_weights = [
            popularity[i] * (5 if favourite_genres & set(a.genres) else 1)
            for i, a in enumerate(artist_list)
        ]
        listener_events: list[SyntheticEvent] = []
        # Plays come in sessions: a few tracks in a row, each one starting when the
        # previous one ended plus a short pause (ADR 0010).
        while len(listener_events) < events_per_listener:
            moment = _random_moment(rng, start, days)
            # 0.0 at the start of the period, 1.0 at the end; the trend shifts the weights.
            progress = (moment - start) / (end - start)
            weights = [w * (1 + trends[i] * (2 * progress - 1)) for i, w in enumerate(base_weights)]
            for _ in range(rng.randint(1, 12)):
                if moment >= end or len(listener_events) == events_per_listener:
                    break
                artist_index = rng.choices(range(len(artist_list)), weights=weights)[0]
                track_index = rng.choice(tracks_by_artist[artist_index])
                listener_events.append(SyntheticEvent(listener_index, track_index, moment))
                moment += timedelta(
                    milliseconds=track_list[track_index].duration_ms,
                    seconds=rng.randint(0, 120),
                )
        events.extend(listener_events)

    return SyntheticDataset(
        genres=list(GENRES),
        artists=artist_list,
        tracks=track_list,
        listeners=listener_list,
        events=events,
    )


def _make_artists(rng: random.Random, count: int) -> list[SyntheticArtist]:
    names: set[str] = set()
    result = []
    while len(result) < count:
        name = f"The {rng.choice(_ADJECTIVES)} {rng.choice(_NOUNS)}"
        if name in names:
            # 16 x 16 = 256 combinations; add a number instead of looping forever.
            name = f"{name} {len(result) + 1}"
        names.add(name)
        genres = rng.sample(GENRES, k=rng.choice([1, 1, 2, 2, 3]))
        result.append(SyntheticArtist(name=name, genres=sorted(genres)))
    return result


def _make_tracks(
    rng: random.Random, artists: list[SyntheticArtist], per_artist: int
) -> list[SyntheticTrack]:
    result = []
    for artist_index in range(len(artists)):
        for _ in range(per_artist):
            words = rng.sample(_TITLE_WORDS, k=rng.choice([1, 2, 3]))
            result.append(
                SyntheticTrack(
                    title=" ".join(words).capitalize(),
                    artist_index=artist_index,
                    duration_ms=rng.randint(120_000, 360_000),
                )
            )
    return result


def _random_moment(rng: random.Random, start: datetime, days: int) -> datetime:
    day = rng.randrange(days)
    hour = rng.choices(range(24), weights=HOUR_WEIGHTS)[0]
    second = rng.randrange(3600)
    return start + timedelta(days=day, hours=hour, seconds=second)
