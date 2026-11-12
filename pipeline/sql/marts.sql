-- Marts layer: tables ready for analytics. See ADR 0005.
--
-- Marts are rebuilt from staging on every run (drop + create in one transaction),
-- so a run can never leave them half updated: either the whole new version is
-- committed, or the old one stays. Primary keys document and enforce the grain
-- ("one row per ...") and give us an index for free.

DROP SCHEMA IF EXISTS marts CASCADE;
CREATE SCHEMA marts;

-- One row per (UTC day, listener).
CREATE TABLE marts.daily_listener_activity AS
SELECT
    e.listened_date AS day,
    e.listener_id,
    count(*) AS plays,
    count(DISTINCT e.track_id) AS unique_tracks,
    count(DISTINCT t.artist_id) AS unique_artists,
    -- We only know that a play started, so we assume the whole track was played.
    sum(t.duration_ms) AS listening_ms
FROM staging.listening_events AS e
JOIN staging.tracks AS t ON t.track_id = e.track_id
GROUP BY e.listened_date, e.listener_id;

ALTER TABLE marts.daily_listener_activity ADD PRIMARY KEY (day, listener_id);

-- One row per (UTC day, genre). A play counts towards every genre of its artist (ADR 0003).
CREATE TABLE marts.daily_genre_plays AS
SELECT
    e.listened_date AS day,
    ag.genre_id,
    ag.genre_name,
    count(*) AS plays,
    count(DISTINCT e.listener_id) AS unique_listeners
FROM staging.listening_events AS e
JOIN staging.tracks AS t ON t.track_id = e.track_id
JOIN staging.artist_genres AS ag ON ag.artist_id = t.artist_id
GROUP BY e.listened_date, ag.genre_id, ag.genre_name;

ALTER TABLE marts.daily_genre_plays ADD PRIMARY KEY (day, genre_id);

-- One row per artist, including artists nobody has played yet (LEFT JOINs),
-- enriched with MusicBrainz data when the artist has an mbid.
CREATE TABLE marts.artist_popularity AS
SELECT
    a.artist_id,
    a.artist_name,
    a.mbid,
    mb.country AS musicbrainz_country,
    mb.artist_type AS musicbrainz_type,
    count(e.event_id) AS total_plays,
    count(DISTINCT e.listener_id) AS unique_listeners,
    min(e.listened_at) AS first_played_at,
    max(e.listened_at) AS last_played_at
FROM staging.artists AS a
LEFT JOIN staging.tracks AS t ON t.artist_id = a.artist_id
LEFT JOIN staging.listening_events AS e ON e.track_id = t.track_id
LEFT JOIN staging.musicbrainz_artists AS mb ON mb.mbid = a.mbid
GROUP BY a.artist_id, a.artist_name, a.mbid, mb.country, mb.artist_type;

ALTER TABLE marts.artist_popularity ADD PRIMARY KEY (artist_id);
