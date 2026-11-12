-- Staging layer: one view per source table. See ADR 0005.
--
-- Staging only cleans and renames; it never aggregates. Views (not tables) are always
-- up to date with their source and cost nothing to "build". The schema is dropped and
-- created again on every run, so this file is the single source of truth for staging.

DROP SCHEMA IF EXISTS staging CASCADE;
CREATE SCHEMA staging;

-- Operational tables of the API (schema public) --------------------------------------------

CREATE VIEW staging.listening_events AS
SELECT
    id AS event_id,
    listener_id,
    track_id,
    listened_at,
    -- Day in UTC (ADR 0003), independent of the session's time zone setting.
    (listened_at AT TIME ZONE 'UTC')::date AS listened_date
FROM public.listening_events;

CREATE VIEW staging.listeners AS
SELECT id AS listener_id, username, country
FROM public.listeners;

CREATE VIEW staging.tracks AS
SELECT id AS track_id, title AS track_title, artist_id, duration_ms
FROM public.tracks;

CREATE VIEW staging.artists AS
SELECT id AS artist_id, name AS artist_name, mbid
FROM public.artists;

CREATE VIEW staging.artist_genres AS
SELECT ag.artist_id, ag.genre_id, g.name AS genre_name
FROM public.artist_genres AS ag
JOIN public.genres AS g ON g.id = ag.genre_id;

-- MusicBrainz (schema raw) -----------------------------------------------------------------

-- raw keeps every downloaded page, so the same artist can appear many times.
-- We keep only the newest version of each artist (row_number() = 1 per mbid).
CREATE VIEW staging.musicbrainz_artists AS
WITH artists AS (
    SELECT r.loaded_at, a.artist
    FROM raw.musicbrainz_artist_search AS r
    -- One row per element of the "artists" JSON array.
    CROSS JOIN LATERAL jsonb_array_elements(r.payload -> 'artists') AS a(artist)
),
ranked AS (
    SELECT
        loaded_at,
        artist,
        row_number() OVER (PARTITION BY artist ->> 'id' ORDER BY loaded_at DESC) AS version
    FROM artists
)
SELECT
    (artist ->> 'id')::uuid AS mbid,
    trim(artist ->> 'name') AS artist_name,
    artist ->> 'type' AS artist_type,
    upper(artist ->> 'country') AS country,
    artist -> 'life-span' ->> 'begin' AS active_since,
    -- Kept as JSON; staging.musicbrainz_artist_tags turns it into rows.
    coalesce(artist -> 'tags', '[]'::jsonb) AS tags,
    loaded_at
FROM ranked
WHERE version = 1;

-- MusicBrainz tags are free text written by users; a tag can have a negative vote count.
CREATE VIEW staging.musicbrainz_artist_tags AS
SELECT
    a.mbid,
    lower(trim(t.tag ->> 'name')) AS tag,
    (t.tag ->> 'count')::int AS votes
FROM staging.musicbrainz_artists AS a
CROSS JOIN LATERAL jsonb_array_elements(a.tags) AS t(tag);

-- Recordings (tracks) of MusicBrainz artists. Like artists, raw keeps every downloaded
-- page, so we keep only the newest version of each recording. A recording made by two
-- artists is returned for both; we keep the artist of the newest page (raw id breaks ties).
CREATE VIEW staging.musicbrainz_recordings AS
WITH recordings AS (
    SELECT r.id AS raw_id, r.loaded_at, r.artist_mbid, rec.recording
    FROM raw.musicbrainz_recording_browse AS r
    CROSS JOIN LATERAL jsonb_array_elements(r.payload -> 'recordings') AS rec(recording)
),
ranked AS (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY recording ->> 'id' ORDER BY loaded_at DESC, raw_id DESC
        ) AS version
    FROM recordings
)
SELECT
    (recording ->> 'id')::uuid AS recording_mbid,
    artist_mbid,
    trim(recording ->> 'title') AS title,
    -- Length in milliseconds; MusicBrainz does not know it for every recording (NULL).
    (recording ->> 'length')::int AS length_ms,
    coalesce((recording ->> 'video')::boolean, false) AS is_video,
    recording ->> 'first-release-date' AS first_release_date,
    loaded_at
FROM ranked
WHERE version = 1;

-- ListenBrainz (schema raw) ----------------------------------------------------------------

-- One row per listen. Pages can overlap (incremental load, retries), so the same listen may
-- be in raw several times; DISTINCT ON keeps one per (user, time, recording_msid).
-- recording_msid is ListenBrainz's own id of the submitted track and is always present.
-- The mbids come from ListenBrainz's mapping to MusicBrainz (mbid_mapping) or, if missing,
-- from what the listening app sent (additional_info). App data can be anything, so an
-- mbid is cast to uuid only when it looks like one; otherwise it becomes NULL.
CREATE VIEW staging.listenbrainz_listens AS
WITH listens AS (
    SELECT r.id AS raw_id, r.user_name, l.listen, l.listen -> 'track_metadata' AS meta
    FROM raw.listenbrainz_listens AS r
    CROSS JOIN LATERAL jsonb_array_elements(r.payload -> 'payload' -> 'listens') AS l(listen)
),
parsed AS (
    SELECT
        raw_id,
        user_name,
        to_timestamp((listen ->> 'listened_at')::bigint) AS listened_at,
        listen ->> 'recording_msid' AS recording_msid,
        coalesce(
            meta -> 'mbid_mapping' ->> 'recording_mbid',
            meta -> 'additional_info' ->> 'recording_mbid'
        ) AS recording_mbid_text,
        coalesce(
            meta -> 'mbid_mapping' -> 'artists' -> 0 ->> 'artist_mbid',
            meta -> 'additional_info' -> 'artist_mbids' ->> 0
        ) AS artist_mbid_text,
        trim(coalesce(meta -> 'mbid_mapping' ->> 'recording_name', meta ->> 'track_name'))
            AS track_name,
        trim(coalesce(
            meta -> 'mbid_mapping' -> 'artists' -> 0 ->> 'artist_credit_name',
            meta ->> 'artist_name'
        )) AS artist_name,
        meta -> 'additional_info' ->> 'duration_ms' AS duration_text
    FROM listens
)
SELECT DISTINCT ON (user_name, listened_at, recording_msid)
    user_name,
    listened_at,
    recording_msid,
    CASE WHEN recording_mbid_text ~* '^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$'
        THEN recording_mbid_text::uuid END AS recording_mbid,
    CASE WHEN artist_mbid_text ~* '^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$'
        THEN artist_mbid_text::uuid END AS artist_mbid,
    track_name,
    artist_name,
    -- Only a positive whole number is a usable length; anything else means "unknown".
    CASE WHEN duration_text ~ '^[0-9]{1,9}$' AND duration_text::int > 0
        THEN duration_text::int END AS duration_ms
FROM parsed
ORDER BY user_name, listened_at, recording_msid, raw_id DESC;
