#!/bin/sh
set -eu
umask 077
mkdir -p /backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target="/backups/ldt-$stamp-$$.dump"
write_status() {
  printf '{"state":"%s","attempted_at":"%s"}\n' "$1" "$stamp" > /backups/status.json.partial
  mv /backups/status.json.partial /backups/status.json
}
trap 'write_status failed; rm -f "$target.partial"' EXIT
write_status running
pg_dump --format=custom --no-owner --no-acl --file="$target.partial"
pg_restore --list "$target.partial" >/dev/null
mv "$target.partial" "$target"
(cd /backups && sha256sum "$(basename "$target")") > "$target.sha256"
date -u +%FT%TZ > /backups/last-success
write_status completed
trap - EXIT
find /backups -maxdepth 1 -name 'ldt-*.dump' -mtime "+${BACKUP_RETENTION_DAYS:-14}" -exec rm -f {} \;
find /backups -maxdepth 1 -name 'ldt-*.dump.sha256' -mtime "+${BACKUP_RETENTION_DAYS:-14}" -exec rm -f {} \;
echo "Backup completed: $target"
