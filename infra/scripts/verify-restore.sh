#!/bin/sh
set -eu
target=${1:?Pass a NEW verification database name}
dump=$(ls -t /backups/*.dump | head -1)
started=$(date +%s)
sh /scripts/restore.sh "$dump" "$target"
ended=$(date +%s)
echo "Restore seconds: $((ended - started))"
