DROP SCHEMA IF EXISTS marts CASCADE;
CREATE SCHEMA marts;

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
CREATE INDEX ix_listener_track_daily_listener_day ON marts.listener_track_daily (listener_id, day);

CREATE TABLE marts.daily_listener_activity AS
SELECT
    e.listened_date AS day,
    e.listener_id,
    count(*) AS plays,
    count(DISTINCT e.track_id) AS unique_tracks,
    count(DISTINCT t.artist_id) AS unique_artists,
    sum(t.duration_ms) AS listening_ms
FROM staging.listening_events AS e
JOIN staging.tracks AS t ON t.track_id = e.track_id
GROUP BY e.listened_date, e.listener_id;

ALTER TABLE marts.daily_listener_activity ADD PRIMARY KEY (day, listener_id);

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
    max(listened_at + make_interval(secs => coalesce(duration_ms, 0) / 1000.0)) AS ended_at,
    (min(listened_at) AT TIME ZONE 'UTC')::date AS day,
    count(*) AS plays,
    count(DISTINCT track_id) AS unique_tracks,
    count(DISTINCT artist_id) AS unique_artists,
    sum(duration_ms) AS listening_ms
FROM numbered
GROUP BY listener_id, session_number;

ALTER TABLE marts.listening_sessions ADD PRIMARY KEY (listener_id, started_at);
CREATE INDEX ix_listening_sessions_day ON marts.listening_sessions (day);

CREATE TABLE marts.build_info AS SELECT now() AS built_at;

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_reader') THEN
        GRANT USAGE ON SCHEMA marts TO grafana_reader;
        GRANT SELECT ON ALL TABLES IN SCHEMA marts TO grafana_reader;
    END IF;
END
$$;
