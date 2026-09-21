#!/usr/bin/env bash
#
# backup.sh — dnevni dump Postgresa i MinIO sadržaja.
# Cron (kao korisnik mm):
#   15 3 * * *  /home/mm/apps/mm-persona-os/deploy/backup.sh >> /home/mm/backups/backup.log 2>&1
#
# Hetznerov snapshot pokriva ceo disk, ali se pravi jednom i ne vraća
# pojedinačnu tabelu. Ovo pokriva "obrisao sam pogrešnu personu u utorak".

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${HOME}/backups"
KEEP_DAYS=14
STAMP="$(date +%Y%m%d-%H%M)"

cd "$APP_DIR"
mkdir -p "$BACKUP_DIR"

# shellcheck disable=SC1091
set -a; source .env.prod; set +a

echo "[$(date -Is)] start"

docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom \
  > "${BACKUP_DIR}/pg-${STAMP}.dump"

docker run --rm \
  -v mm-persona-os_miniodata:/data:ro \
  -v "${BACKUP_DIR}:/backup" \
  alpine tar czf "/backup/minio-${STAMP}.tar.gz" -C /data .

find "$BACKUP_DIR" -name 'pg-*.dump'      -mtime "+${KEEP_DAYS}" -delete
find "$BACKUP_DIR" -name 'minio-*.tar.gz' -mtime "+${KEEP_DAYS}" -delete

ln -sfn "pg-${STAMP}.dump" "${BACKUP_DIR}/pg-latest.dump"

echo "[$(date -Is)] gotovo — $(du -sh "$BACKUP_DIR" | cut -f1) ukupno"

# Provera da dump nije prazan ljuska — pg_dump vraća 0 i za praznu bazu.
SIZE=$(stat -c%s "${BACKUP_DIR}/pg-${STAMP}.dump")
if (( SIZE < 4096 )); then
  echo "UPOZORENJE: dump je ${SIZE} B. Proveri bazu." >&2
  exit 1
fi
