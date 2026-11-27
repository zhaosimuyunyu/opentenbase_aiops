#!/bin/sh
set -eu

interval_seconds=${AIOPS_METADATA_BACKUP_INTERVAL_SECONDS:-86400}
retention_days=${AIOPS_METADATA_BACKUP_RETENTION_DAYS:-30}

case "$interval_seconds" in
  ''|*[!0-9]*) echo "AIOPS_METADATA_BACKUP_INTERVAL_SECONDS must be an integer" >&2; exit 2 ;;
esac
case "$retention_days" in
  ''|*[!0-9]*) echo "AIOPS_METADATA_BACKUP_RETENTION_DAYS must be an integer" >&2; exit 2 ;;
esac
[ "$interval_seconds" -ge 60 ] || { echo "Backup interval must be at least 60 seconds" >&2; exit 2; }
[ "$retention_days" -ge 1 ] || { echo "Backup retention must be at least one day" >&2; exit 2; }

mkdir -p /backups
umask 077
sleep_pid=""

stop_scheduler() {
  if [ -n "$sleep_pid" ]; then
    kill "$sleep_pid" 2>/dev/null || true
  fi
  exit 0
}

trap stop_scheduler INT TERM

while :; do
  timestamp=$(date -u +%Y%m%dT%H%M%SZ)
  archive="/backups/aiops-metadata-${timestamp}-$$.dump"
  temporary="${archive}.partial.$$"
  checksum_temporary="${archive}.sha256.partial.$$"

  if pg_dump --format=custom --no-owner --no-acl > "$temporary"; then
    mv "$temporary" "$archive"
    sha256sum "$archive" > "$checksum_temporary"
    mv "$checksum_temporary" "${archive}.sha256"
    printf 'Created metadata backup %s\n' "$archive"
    find /backups -type f -name 'aiops-metadata-*.dump' -mtime "+${retention_days}" -print |
      while IFS= read -r expired_archive; do
        rm -f "$expired_archive" "${expired_archive}.sha256"
        printf 'Removed expired metadata backup %s\n' "$expired_archive"
      done
    find /backups -type f \
      \( -name 'aiops-metadata-*.dump.partial.*' -o -name 'aiops-metadata-*.dump.sha256.partial.*' \) \
      -mtime +1 -delete
  else
    rm -f "$temporary" "$checksum_temporary"
    echo "Metadata backup failed; retrying after the configured interval" >&2
  fi

  sleep "$interval_seconds" &
  sleep_pid=$!
  wait "$sleep_pid" || true
  sleep_pid=""
done
