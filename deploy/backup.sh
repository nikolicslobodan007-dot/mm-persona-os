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

# .env.prod je Docker env-file, ne bash skripta: vrednosti sa razmakom ili
# zagradom ruše `source`. Zato čitamo samo dve promenljive koje nam trebaju.
env_get() { grep -E "^$1=" .env.prod | tail -1 | cut -d= -f2- | tr -d "\"'"; }
POSTGRES_USER="$(env_get POSTGRES_USER)"
POSTGRES_DB="$(env_get POSTGRES_DB)"
[[ -n "$POSTGRES_USER" && -n "$POSTGRES_DB" ]] || { echo "POSTGRES_USER/DB nisu u .env.prod" >&2; exit 1; }

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
