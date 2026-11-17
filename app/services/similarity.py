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
    stmt = select(
        facts.c.listener_id, facts.c.artist_id, total(facts.c.plays).label("plays")
    ).group_by(facts.c.listener_id, facts.c.artist_id)
    return filter_days(stmt, window, listener_id=None).cte("artist_plays")


def similar_listeners(
    session: Session, listener_id: int, window: TimeWindow, limit: int
) -> list[SimilarListener]:
    catalog.get_listener(session, listener_id)
    plays = _artist_plays(window)

    target = select(plays.c.artist_id, plays.c.plays).where(plays.c.listener_id == listener_id)
    target = target.cte("target")

    norms = (
        select(
            plays.c.listener_id, func.sqrt(func.sum(plays.c.plays * plays.c.plays)).label("norm")
        )
        .group_by(plays.c.listener_id)
        .cte("norms")
    )

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
