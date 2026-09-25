#!/usr/bin/env python3
"""Poslušnik. ADR-0038 §2.

Ovo je **jedini** proces koji sme da vidi Docker, i namerno živi van aplikacije.
Razlog je prost: `docker.sock` je root na hostu. Da ga dobije `web` ili worker,
svaka greška u Django kodu postala bi root na mašini — a zaštićene zone dekor,
jer se do njih stiže ispod aplikacije.

Zato ovaj proces:

  - prima **samo `task_id`** preko API-ja; ništa što je agent napisao ne stiže
    do njega kao komanda, ime, putanja ni zastavica;
  - sam pravi radni primerak iz `git`-a, sam primenjuje zakrpu, sam vrti kapije;
  - ne prosleđuje nijednu promenljivu okruženja iz svoje ljuske u kontejner.

Instalacija je u `README.md` pored ovog fajla.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("PERSONA_API", "http://127.0.0.1:8000/api/v1")
TOKEN = os.environ.get("PERSONA_TOKEN", "")
REPO = Path(os.environ.get("PERSONA_REPO", "/srv/mm-persona-os")).resolve()
COMPOSE = Path(__file__).resolve().parent / "docker-compose.zadatak.yml"
PAUZA = int(os.environ.get("PERSONA_POLL_SECONDS", "20"))
#: Koliko sme da traje jedan prolaz kapija. Pun `pytest` je oko 2,5 minuta.
ROK = int(os.environ.get("PERSONA_TIMEOUT_SECONDS", "900"))

#: `task_id` je jedino što ulazi spolja — i jedino čemu se veruje posle ove provere.
TSK = re.compile(r"^TSK-[0-9A-HJKMNP-TV-Z]{26}$")


def log(*delovi) -> None:
    print(time.strftime("%H:%M:%S"), *delovi, flush=True)


def zaglavlja() -> dict[str, str]:
    """Canon §8.5 — svaki POST nosi svoj trag i imenovanog pokretača.

    Radnja bez traga i bez pokretača ne sme ni da počne, pa se ovi header-i
    prave ovde, a ne nadaju se da će ih neko drugi dodati.
    """
    trag = secrets.token_hex(16)
    return {
        "Authorization": f"Token {TOKEN}",
        "Content-Type": "application/json",
        "X-Request-ID": f"runner-{secrets.token_hex(8)}",
        "traceparent": f"00-{trag}-{secrets.token_hex(8)}-01",
        "X-Actor-ID": "service:runner",
    }


def api(putanja: str, telo: dict | None = None) -> dict:
    zahtev = urllib.request.Request(
        f"{API}{putanja}",
        data=json.dumps(telo).encode() if telo is not None else None,
        headers=zaglavlja(),
        method="POST" if telo is not None else "GET",
    )
    with urllib.request.urlopen(zahtev, timeout=30) as odgovor:
        return json.loads(odgovor.read() or b"{}")


def trci(*argv: str, cwd: Path | None = None, rok: int = 120) -> subprocess.CompletedProcess:
    """Pokreće komandu bez ljuske i bez nasleđenog okruženja."""
    return subprocess.run(  # noqa: S603 — argumenti su literali, nikad agentov tekst
        argv, cwd=cwd, capture_output=True, text=True, timeout=rok,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp",
             "GIT_TERMINAL_PROMPT": "0"},
        check=False,
    )


def radni_primerak(baza: str, cilj: Path) -> None:
    """Svež primerak iz lokalnog `git`-a, bez mreže i bez istorije."""
    r = trci("git", "clone", "--no-hardlinks", "--shared", "--no-checkout",
             str(REPO), str(cilj), rok=180)
    if r.returncode:
        raise RuntimeError(f"clone: {r.stderr[:400]}")
    r = trci("git", "checkout", "--detach", baza or "HEAD", cwd=cilj, rok=120)
    if r.returncode:
        raise RuntimeError(f"checkout {baza}: {r.stderr[:400]}")


def primeni(zakrpa: str, rad: Path) -> None:
    """Primena zakrpe koju je aplikacija VEĆ proverila (ADR-0038 §3).

    `--unsafe-paths` se ne prosleđuje, pa `git` sam odbija pisanje van stabla —
    druga brava iza one u `apps/orchestration/zakrpa.py`.
    """
    put = rad / ".zakrpa.diff"
    put.write_text(zakrpa, encoding="utf-8")
    r = trci("git", "apply", "--check", "--whitespace=nowarn", str(put),
             cwd=rad, rok=120)
    if r.returncode:
        raise RuntimeError(f"apply --check: {r.stderr[:400]}")
    r = trci("git", "apply", "--whitespace=nowarn", str(put), cwd=rad, rok=120)
    if r.returncode:
        raise RuntimeError(f"apply: {r.stderr[:400]}")
    put.unlink(missing_ok=True)


def kapije(task_id: str, rad: Path, izvestaj: Path) -> tuple[bool, dict]:
    ime = "zad-" + task_id.lower().replace("tsk-", "")[:20]
    okolina = {
        "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp",
        "COMPOSE_PROJECT_NAME": ime,
        "RADNI_PRIMERAK": str(rad), "IZVESTAJ": str(izvestaj),
        "UID": str(os.getuid()), "GID": str(os.getgid()),
    }
    try:
        subprocess.run(  # noqa: S603
            ["docker", "compose", "-f", str(COMPOSE), "up",
             "--abort-on-container-exit", "--exit-code-from", "kapije"],
            env=okolina, capture_output=True, text=True, timeout=ROK, check=False)
    finally:
        subprocess.run(  # noqa: S603
            ["docker", "compose", "-f", str(COMPOSE), "down", "-v", "--remove-orphans"],
            env=okolina, capture_output=True, text=True, timeout=300, check=False)

    ishod = {}
    for kapija in ("pytest", "ruff", "canon_lint", "migrations"):
        s = (izvestaj / f"{kapija}.status")
        ishod[kapija] = s.read_text().strip() == "ok" if s.exists() else False
    return all(ishod.values()), ishod


def obradi(task_id: str) -> None:
    if not TSK.match(task_id):
        log("odbijen id:", task_id[:60])
        return
    posao = api(f"/tasks/{task_id}/work")
    zakrpa, baza = posao.get("diff", ""), posao.get("base_sha", "")
    if not zakrpa:
        log(task_id, "nema zakrpe")
        return

    rad = Path(tempfile.mkdtemp(prefix="rad-"))
    izvestaj = Path(tempfile.mkdtemp(prefix="izv-"))
    try:
        radni_primerak(baza, rad)
        primeni(zakrpa, rad)
        zelene, ishod = kapije(task_id, rad, izvestaj)
        log(task_id, "kapije:", ishod)
        for kapija, ok in ishod.items():
            api(f"/tasks/{task_id}/gate", {
                "gate": kapija, "passed": ok, "commit": baza,
                "detail": (izvestaj / f"{kapija}.log").read_text(errors="replace")[-4000:]
                if (izvestaj / f"{kapija}.log").exists() else "",
            })
        if zelene:
            log(task_id, "sve zeleno")
    except Exception as e:  # noqa: BLE001 — poslušnik ne sme da padne na jednom zadatku
        log(task_id, "greška:", str(e)[:300])
        api(f"/tasks/{task_id}/gate", {"gate": "pytest", "passed": False,
                                       "detail": str(e)[:2000]})
    finally:
        shutil.rmtree(rad, ignore_errors=True)
        shutil.rmtree(izvestaj, ignore_errors=True)


def main() -> int:
    if not TOKEN:
        log("nema PERSONA_TOKEN — poslušnik ne kreće")
        return 2
    log("poslušnik kreće; repo:", REPO)
    while True:
        try:
            red = api("/tasks/queued").get("tasks", [])
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            log("API nedostupan:", str(e)[:200])
            red = []
        # Jedan zadatak u isto vreme — ADR-0038 §5. CX23 nema za više.
        for task_id in red[:1]:
            obradi(str(task_id))
        time.sleep(PAUZA)


if __name__ == "__main__":
    sys.exit(main())
