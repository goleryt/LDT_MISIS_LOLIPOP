#!/bin/sh
# Restore only into a new empty database; never drop or overwrite the source database.
set -eu
dump=${1:?Usage: restore.sh /backups/file.dump NEW_DATABASE}
target=${2:?New database name required}
case "$target" in *[!a-zA-Z0-9_]*|"") echo "Invalid database name" >&2; exit 2;; esac
if [ "$target" = "${PGDATABASE:-}" ]; then echo "Target must differ from source database" >&2; exit 2; fi
sha256sum -c "$dump.sha256"
createdb "$target"
pg_restore --exit-on-error --single-transaction --no-owner --no-acl --dbname="$target" "$dump"
psql --dbname="$target" --set=ON_ERROR_STOP=1 --command='SELECT version_num FROM alembic_version; SELECT count(*) FROM events_journal;'
echo "Restored into $target. Validate API and switch configuration in the planned maintenance window."
