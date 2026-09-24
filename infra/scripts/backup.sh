#!/bin/sh
set -eu
umask 077
mkdir -p /backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target="/backups/ldt-$stamp.dump"
pg_dump --format=custom --no-owner --no-acl --file="$target.partial"
pg_restore --list "$target.partial" >/dev/null
mv "$target.partial" "$target"
sha256sum "$target" > "$target.sha256"
date -u +%FT%TZ > /backups/last-success
find /backups -maxdepth 1 -name 'ldt-*.dump' -mtime "+${BACKUP_RETENTION_DAYS:-14}" -exec rm -f {} \;
find /backups -maxdepth 1 -name 'ldt-*.dump.sha256' -mtime "+${BACKUP_RETENTION_DAYS:-14}" -exec rm -f {} \;
echo "Backup completed: $target"
