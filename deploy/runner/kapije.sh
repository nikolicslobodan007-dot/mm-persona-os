#!/bin/sh
# Četiri kapije nad radnim primerkom. ADR-0035 §3.
#
# Izlazi 0 samo ako su sve četiri zelene. Svaki ispis ide i u /izvestaj, jer
# poslušnik ne čita ekran nego fajlove.
set -u
IZ=/izvestaj
mkdir -p "$IZ"
ishod=0

vrti() {
    ime="$1"; shift
    echo "--- $ime ---"
    if "$@" > "$IZ/$ime.log" 2>&1; then
        echo "$ime: ZELENO"
        echo "ok" > "$IZ/$ime.status"
    else
        echo "$ime: PALO"
        echo "pao" > "$IZ/$ime.status"
        ishod=1
    fi
}

vrti pytest      python -m pytest -q
vrti ruff        ruff check .
vrti canon_lint  python tools/canon_lint.py
vrti migrations  python manage.py makemigrations --check --dry-run

echo "$ishod" > "$IZ/ishod"
exit "$ishod"
