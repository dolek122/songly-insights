"""Listener similarity (ADR 0012).

Every listener is a vector: how many times they played each artist in the window.
Two listeners are compared with cosine similarity:

    similarity(a, b) = (a · b) / (|a| * |b|)

    a · b  = sum over shared artists of plays_a * plays_b   (the dot product)
    |a|    = sqrt(sum of plays_a squared)                    (the length of the vector)

It is 1.0 when two listeners split their plays between artists in the same proportions
(even if one listens 10x more) and 0 when they have no artist in common. Read from
marts.listener_track_daily, so windows work like in all statistics (ADR 0007).
"""

from sqlalchemy import Float, cast, func, select
from sqlalchemy.orm import Session

from app.marts import listener_track_daily as facts
from app.models import Artist, Listener
from app.schemas.stats import SharedArtist, SimilarListener
from app.services import catalog
from app.services.stats import filter_days, total
from app.services.time_window import TimeWindow

TOP_SHARED_ARTISTS = 3


def _artist_plays(window: TimeWindow):
    """CTE: one row per (listener, artist) with the plays in the window."""
    stmt = select(
        facts.c.listener_id, facts.c.artist_id, total(facts.c.plays).label("plays")
    ).group_by(facts.c.listener_id, facts.c.artist_id)
    return filter_days(stmt, window, listener_id=None).cte("artist_plays")


def similar_listeners(
    session: Session, listener_id: int, window: TimeWindow, limit: int
) -> list[SimilarListener]:
    catalog.get_listener(session, listener_id)  # 404 when the listener does not exist
    plays = _artist_plays(window)

    # The listener we compare everybody else with.
    target = select(plays.c.artist_id, plays.c.plays).where(plays.c.listener_id == listener_id)
    target = target.cte("target")

    # |v| for every listener. sqrt(sum(x²)), computed once per listener.
    norms = (
        select(
            plays.c.listener_id, func.sqrt(func.sum(plays.c.plays * plays.c.plays)).label("norm")
        )
        .group_by(plays.c.listener_id)
        .cte("norms")
    )

    # a · b: only artists both listened to contribute, so an inner join on artist_id is enough.
    # Listeners with no artist in common do not appear at all (their similarity is 0).
    dots = (
        select(
            plays.c.listener_id,
            func.sum(plays.c.plays * target.c.plays).label("dot"),
            func.count().label("shared_artists"),
        )
        .join(target, target.c.artist_id == plays.c.artist_id)
        .where(plays.c.listener_id != listener_id)
        .group_by(plays.c.listener_id)
        .cte("dots")
    )

    target_norm = select(norms.c.norm).where(norms.c.listener_id == listener_id).scalar_subquery()
    similarity = cast(dots.c.dot / (norms.c.norm * target_norm), Float).label("similarity")
    rows = session.execute(
        select(Listener.id, Listener.username, similarity, dots.c.shared_artists)
        .select_from(dots)
        .join(norms, norms.c.listener_id == dots.c.listener_id)
        .join(Listener, Listener.id == dots.c.listener_id)
        .order_by(similarity.desc(), Listener.id)
        .limit(limit)
    ).all()

    shared = _top_shared_artists(session, plays, target, [r.id for r in rows])
    return [
        SimilarListener(
            listener_id=r.id,
            username=r.username,
            similarity=round(r.similarity, 4),
            shared_artists=r.shared_artists,
            top_shared_artists=shared.get(r.id, []),
        )
        for r in rows
    ]


def _top_shared_artists(
    session: Session, plays, target, listener_ids: list[int]
) -> dict[int, list[SharedArtist]]:
    """For each listener: the shared artists both of them play the most.

    "Both play the most" = the larger the smaller of the two play counts (least()).
    row_number() numbers the artists per listener, so we can keep the first few.
    """
    if not listener_ids:
        return {}
    both = func.least(plays.c.plays, target.c.plays)
    ranked = (
        select(
            plays.c.listener_id,
            Artist.id.label("artist_id"),
            Artist.name,
            func.row_number()
            .over(partition_by=plays.c.listener_id, order_by=(both.desc(), Artist.id))
            .label("rank"),
        )
        .join(target, target.c.artist_id == plays.c.artist_id)
        .join(Artist, Artist.id == plays.c.artist_id)
        .where(plays.c.listener_id.in_(listener_ids))
        .subquery()
    )
    rows = session.execute(
        select(ranked.c.listener_id, ranked.c.artist_id, ranked.c.name)
        .where(ranked.c.rank <= TOP_SHARED_ARTISTS)
        .order_by(ranked.c.listener_id, ranked.c.rank)
    )
    result: dict[int, list[SharedArtist]] = {}
    for listener, artist_id, name in rows:
        result.setdefault(listener, []).append(SharedArtist(artist_id=artist_id, name=name))
    return result
