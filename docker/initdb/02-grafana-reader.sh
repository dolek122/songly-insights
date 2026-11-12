#!/bin/bash
# Read-only database user for Grafana dashboards (ADR 0014). Runs once, when the
# data volume is created. The password comes from GRAFANA_DB_PASSWORD (.env).
set -euo pipefail

if [ -z "${GRAFANA_DB_PASSWORD:-}" ]; then
    echo "GRAFANA_DB_PASSWORD not set: skipping the grafana_reader user"
    exit 0
fi

psql -v ON_ERROR_STOP=1 -v pw="$GRAFANA_DB_PASSWORD" \
    --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE grafana_reader LOGIN PASSWORD :'pw';
GRANT CONNECT ON DATABASE insights TO grafana_reader;
-- The catalog (names of artists, genres) ...
GRANT USAGE ON SCHEMA public TO grafana_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO grafana_reader;
-- ... marts are granted by pipeline/sql/marts.sql, because the pipeline recreates them.
SQL
