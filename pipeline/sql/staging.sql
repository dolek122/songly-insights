DROP SCHEMA IF EXISTS staging CASCADE;
CREATE SCHEMA staging;

CREATE VIEW staging.listening_events AS
SELECT
    id AS event_id,
    listener_id,
    track_id,
    listened_at,
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

CREATE VIEW staging.musicbrainz_artists AS
WITH artists AS (
    SELECT r.loaded_at, a.artist
    FROM raw.musicbrainz_artist_search AS r
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
    coalesce(artist -> 'tags', '[]'::jsonb) AS tags,
    loaded_at
FROM ranked
WHERE version = 1;

CREATE VIEW staging.musicbrainz_artist_tags AS
SELECT
    a.mbid,
    lower(trim(t.tag ->> 'name')) AS tag,
    (t.tag ->> 'count')::int AS votes
FROM staging.musicbrainz_artists AS a
CROSS JOIN LATERAL jsonb_array_elements(a.tags) AS t(tag);

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
    (recording ->> 'length')::int AS length_ms,
    coalesce((recording ->> 'video')::boolean, false) AS is_video,
    recording ->> 'first-release-date' AS first_release_date,
    loaded_at
FROM ranked
WHERE version = 1;

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
    CASE WHEN duration_text ~ '^[0-9]{1,9}$' AND duration_text::int > 0
        THEN duration_text::int END AS duration_ms
FROM parsed
ORDER BY user_name, listened_at, recording_msid, raw_id DESC;
