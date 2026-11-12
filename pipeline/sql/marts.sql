-- Marts layer: tables ready for analytics. See ADR 0005.
--
-- Marts are rebuilt from staging on every run (drop + create in one transaction),
-- so a run can never leave them half updated: either the whole new version is
-- committed, or the old one stays. Primary keys document and enforce the grain
-- ("one row per ...") and give us an index for free.

DROP SCHEMA IF EXISTS marts CASCADE;
CREATE SCHEMA marts;

-- One row per (UTC day, listener, track). The API statistics read this table (ADR 0007).
-- It keeps track_id on purpose: "unique tracks in a window" cannot be computed by adding
-- daily unique counts (the same track on two days would be counted twice).
CREATE TABLE marts.listener_track_daily AS
SELECT
    e.listened_date AS day,
    e.listener_id,
    e.track_id,
    t.artist_id,
    count(*) AS plays,
    count(*) * t.duration_ms AS listening_ms,
    min(e.listened_at) AS first_listened_at,
    max(e.listened_at) AS last_listened_at
FROM staging.listening_events AS e
JOIN staging.tracks AS t ON t.track_id = e.track_id
GROUP BY e.listened_date, e.listener_id, e.track_id, t.artist_id, t.duration_ms;

ALTER TABLE marts.listener_track_daily ADD PRIMARY KEY (day, listener_id, track_id);
-- The API filters by listener and day range; the primary key already covers day-first lookups.
CREATE INDEX ix_listener_track_daily_listener_day ON marts.listener_track_daily (listener_id, day);

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

-- Listening sessions (ADR 0010): one row per session of a listener.
-- A session is a run of plays where each play starts at most 30 minutes after the
-- previous one. This is the "gaps and islands" pattern:
--   1. lag() puts the previous play's time next to every play,
--   2. a play starts a new session when there is no previous play or the gap is too big,
--   3. a running sum of those "new session" flags numbers the sessions (1, 1, 1, 2, 2, 3, ...),
--   4. GROUP BY that number collapses each session into one row.
CREATE TABLE marts.listening_sessions AS
WITH plays AS (
    SELECT
        e.event_id,
        e.listener_id,
        e.track_id,
        e.listened_at,
        t.artist_id,
        t.duration_ms,
        lag(e.listened_at) OVER (
            PARTITION BY e.listener_id ORDER BY e.listened_at, e.event_id
        ) AS previous_listened_at
    FROM staging.listening_events AS e
    JOIN staging.tracks AS t ON t.track_id = e.track_id
),
flagged AS (
    SELECT
        *,
        CASE
            WHEN previous_listened_at IS NULL THEN 1
            WHEN listened_at - previous_listened_at > interval '30 minutes' THEN 1
            ELSE 0
        END AS starts_session
    FROM plays
),
numbered AS (
    SELECT
        *,
        sum(starts_session) OVER (
            PARTITION BY listener_id ORDER BY listened_at, event_id
        ) AS session_number
    FROM flagged
)
SELECT
    listener_id,
    min(listened_at) AS started_at,
    max(listened_at) AS last_play_at,
    -- The session ends when its last track ends. Unknown length: the moment it started.
    max(listened_at + make_interval(secs => coalesce(duration_ms, 0) / 1000.0)) AS ended_at,
    -- A session belongs to the UTC day it started on (also when it runs past midnight).
    (min(listened_at) AT TIME ZONE 'UTC')::date AS day,
    count(*) AS plays,
    count(DISTINCT track_id) AS unique_tracks,
    count(DISTINCT artist_id) AS unique_artists,
    sum(duration_ms) AS listening_ms
FROM numbered
GROUP BY listener_id, session_number;

-- session_number is not kept: it changes when older plays are imported later.
-- (listener, start time) identifies a session and stays the same.
ALTER TABLE marts.listening_sessions ADD PRIMARY KEY (listener_id, started_at);
CREATE INDEX ix_listening_sessions_day ON marts.listening_sessions (day);

-- When were the marts built? now() is the start of this transaction, i.e. the data in the
-- marts is complete up to this moment. The API returns it as `data_as_of`.
CREATE TABLE marts.build_info AS SELECT now() AS built_at;
