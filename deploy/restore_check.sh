#!/usr/bin/env bash
#
# restore_check.sh — proba povratka poslednje kopije u privremenu bazu.
# „Kopija koja nije vraćena nije kopija." Ne dira produkcijsku bazu.
#
#   ~/apps/mm-persona-os/deploy/restore_check.sh            poslednja kopija
#   ~/apps/mm-persona-os/deploy/restore_check.sh pg-X.dump  određena kopija
#
# Cron (nedeljno, nedelja 04:30):
#   30 4 * * 0  /home/mm/apps/mm-persona-os/deploy/restore_check.sh >> /home/mm/backups/restore.log 2>&1

set -euo pipefail

BACKUP_DIR="${HOME}/backups"
DUMP="${BACKUP_DIR}/${1:-pg-latest.dump}"
NAME="restore-check-$$"

[[ -s "$DUMP" ]] || { echo "Nema kopije: $DUMP" >&2; exit 1; }
echo "[$(date -Is)] proba povratka: $(readlink -f "$DUMP") ($(du -h "$DUMP" | cut -f1))"

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$NAME" -e POSTGRES_PASSWORD=proba -e POSTGRES_DB=proba \
  pgvector/pgvector:pg16 >/dev/null
for _ in $(seq 1 30); do
  docker exec "$NAME" pg_isready -U postgres -d proba >/dev/null 2>&1 && break
  sleep 1
done

docker exec -i "$NAME" pg_restore -U postgres -d proba --no-owner --no-privileges \
  < "$DUMP" 2> "${BACKUP_DIR}/restore-last.err" || true

q() { docker exec "$NAME" psql -U postgres -d proba -tAc "$1" 2>/dev/null || echo "?"; }
PERSONAS=$(q "select count(*) from personas_persona")
ACTIONS=$(q "select count(*) from orchestration_action")
MIGR=$(q "select count(*) from django_migrations")
AUDIT=$(q "select count(*) from observability_audit_event")

echo "persone=${PERSONAS} akcije=${ACTIONS} audit=${AUDIT} migracije=${MIGR}"
if [[ "$PERSONAS" == "?" || "$PERSONAS" -lt 1 || "$MIGR" == "?" || "$MIGR" -lt 10 ]]; then
  echo "NEUSPEH: kopija se ne vraća ispravno — vidi ${BACKUP_DIR}/restore-last.err" >&2
  exit 1
fi
echo "[$(date -Is)] OK — kopija se vraća."
