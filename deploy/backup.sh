#!/bin/sh
# Daily PostgreSQL dump for the docker-compose setup. Keeps the last 14 days in ./backups.
set -e
while true; do
  stamp=$(date +%F)
  pg_dump -h db -U hoteli hoteli | gzip > "/backups/hoteli-${stamp}.sql.gz"
  echo "Backup written: hoteli-${stamp}.sql.gz"
  # Prune dumps older than 14 days (only files this script created).
  find /backups -maxdepth 1 -type f -name 'hoteli-*.sql.gz' -mtime +14 -exec rm -f {} \;
  sleep 86400
done
