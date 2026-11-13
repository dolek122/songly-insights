#!/bin/bash
# Backups of the insights database (ADR 0017). Runs in the official postgres image, which
# already has pg_dump, pg_restore and psql. Connection settings come from PG* variables.
#
#   backup.sh loop            one backup now, then every day at BACKUP_TIME (UTC)
#   backup.sh once            one backup now
#   backup.sh restore FILE    replace the database content with a dump (stop API + pipeline first)
#
# Every backup is checked by restoring it into a throwaway database: a backup nobody has
# restored is only a hope. The result goes to ops.backups, which monitoring reads.
set -uo pipefail

BACKUP_DIR=${BACKUP_DIR:-/backups}
BACKUP_TIME=${BACKUP_TIME:-02:30}
BACKUP_KEEP_DAYS=${BACKUP_KEEP_DAYS:-7}
CHECK_DB=insights_restore_check

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup: $*"; }

# psql with the SQL on stdin, so values can be passed safely as psql variables (:'name').
sql() { psql -X -q -t -A -v ON_ERROR_STOP=1 "$@"; }

verify() {
    local file=$1
    dropdb --if-exists "$CHECK_DB" && createdb "$CHECK_DB" || return 1
    # --exit-on-error: any problem fails the check instead of being printed and ignored.
    if ! pg_restore --no-owner --exit-on-error --dbname="$CHECK_DB" "$file"; then
        dropdb --if-exists "$CHECK_DB"
        return 1
    fi
    local events
    events=$(sql -d "$CHECK_DB" -c "SELECT count(*) FROM public.listening_events") || return 1
    dropdb "$CHECK_DB"
    log "test restore OK ($events listening events)"
}

backup_once() {
    local id file
    id=$(echo "INSERT INTO ops.backups DEFAULT VALUES RETURNING id" | sql) || return 1
    file="$BACKUP_DIR/insights-$(date -u +%Y%m%dT%H%M%SZ).dump"
    log "starting $file"

    # Write to .partial first: a half-written file never looks like a finished backup.
    # --format=custom: compressed, and pg_restore can restore selected parts of it.
    if pg_dump --format=custom --file="$file.partial" && mv "$file.partial" "$file" \
        && verify "$file"; then
        sql -v id="$id" -v name="$(basename "$file")" -v size="$(stat -c %s "$file")" <<'SQL'
UPDATE ops.backups
SET finished_at = now(), status = 'completed', file_name = :'name',
    size_bytes = :'size', verified = true
WHERE id = :'id';
SQL
        # Rotation: delete dumps older than BACKUP_KEEP_DAYS days.
        find "$BACKUP_DIR" -name 'insights-*.dump' -mtime +"$BACKUP_KEEP_DAYS" -print -delete
        log "done ($(du -h "$file" | cut -f1))"
    else
        rm -f "$file.partial"
        sql -v id="$id" <<'SQL'
UPDATE ops.backups SET finished_at = now(), status = 'failed',
    error = 'pg_dump or the test restore failed; see the backup container log'
WHERE id = :'id';
SQL
        log "FAILED"
        return 1
    fi
}

seconds_until() {
    local now next
    now=$(date -u +%s)
    next=$(date -u -d "today $1" +%s)
    [ "$next" -le "$now" ] && next=$(date -u -d "tomorrow $1" +%s)
    echo $((next - now))
}

restore() {
    local file=$1
    [ -f "$file" ] || { log "no such file: $file"; exit 1; }
    log "restoring $file into $PGDATABASE"
    # --clean --if-exists: drop each object before recreating it.
    # --single-transaction: all or nothing; a failed restore leaves the database as it was.
    pg_restore --clean --if-exists --no-owner --exit-on-error --single-transaction \
        --dbname="$PGDATABASE" "$file" && log "restore finished"
}

case "${1:-loop}" in
    once) backup_once ;;
    restore) restore "${2:?usage: backup.sh restore FILE}" ;;
    loop)
        mkdir -p "$BACKUP_DIR"
        # A first backup right away, so a fresh deployment is protected (and monitored) at once.
        backup_once
        while true; do
            wait_s=$(seconds_until "$BACKUP_TIME")
            log "next backup in $((wait_s / 3600)) h $((wait_s % 3600 / 60)) min"
            sleep "$wait_s"
            backup_once
        done
        ;;
    *) echo "usage: backup.sh [loop|once|restore FILE]"; exit 2 ;;
esac
