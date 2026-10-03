"""Grane koje čekaju ljudsku ruku. ADR-0043.

    manage.py grane

Ispisuje zadatke koji imaju commit na grani `zadatak/TSK-…`, a još nisu
zatvoreni. Uz spisak ide i komanda kojom se te grane dovlače — jer se `main`
menja sa radne mašine, ne sa servera: serverski ključ je namerno read-only.

Refspec nosi `+` (ADR-0069). Poslušnik svaki pokušaj gradi iz čistog primerka,
pa grana zadatka nije istorija nego **poslednji ishod**: svaki novi pokušaj je
prepisuje. Dovlačenje bez `+` takvu granu odbija kao `non-fast-forward` i tiho
ostavlja ono što je stiglo prošli put.

Od ADR-0071 ispis nije spisak nego **prevod**: čovek koji odlučuje o `main`-u ne
mora da čita `diff` da bi znao šta spaja. Sve stoji u bazi i ništa se ne traži od
modela — prikaz koji bi izmišljao bio bi gori od nikakvog.
"""

from __future__ import annotations

import os

from django.core.management.base import BaseCommand

from apps.orchestration import rezultat

#: Kako se sa radne mašine vidi serverski repozitorijum. Menja se promenljivom
#: okruženja, da vrednost ne bi bila pretpostavka zakucana u kod (ADR-0033).
DALJINSKI = os.environ.get("PERSONA_GIT_REMOTE", "persona:apps/mm-persona-os")


def _uvij(tekst: str, uvlaka: str, sirina: int = 76) -> list[str]:
    """Prelama prozu da red stane na ekran, bez sečenja reči."""
    reci = (tekst or "").split()
    if not reci:
        return [f"{uvlaka}—"]
    redovi, tekuci = [], reci[0]
    for rec in reci[1:]:
        if len(tekuci) + 1 + len(rec) > sirina:
            redovi.append(tekuci)
            tekuci = rec
        else:
            tekuci += " " + rec
    redovi.append(tekuci)
    return [uvlaka + r for r in redovi]


def _kapije(ishod: dict) -> str:
    """Sve tražene kapije u jednom redu, svaka sa svojim ishodom."""
    if not ishod:
        return "nijedna nije vrtena nad ovom zakrpom"
    znak = {True: "prošla", False: "PALA", None: "nije vrtena"}
    return "  ".join(f"{g}: {znak[ok]}" for g, ok in ishod.items())


class Command(BaseCommand):
    help = "Grane sa rezultatom rada agenata, koje čekaju pregled (ADR-0043, 0071)."

    def handle(self, *args, **opts):
        redovi = rezultat.za_pregled()
        if not redovi:
            self.stdout.write("Nijedna grana ne čeka pregled.")
            return

        for r in redovi:
            self.stdout.write("")
            self.stdout.write("─" * 78)
            self.stdout.write(f"GRANA     {r['branch']}  ({r['commit'][:12]})")
            self.stdout.write(f"ZADATAK   {r['task']} · {r['title']}")

            self.stdout.write("ZAŠTO")
            for red in _uvij(r["zasto"], "          "):
                self.stdout.write(red)
            if r["adr"]:
                self.stdout.write(f"          (po {r['adr']})")

            ime = (r["ime"] or "").strip()
            self.stdout.write(f"AGENT     {ime or '—'}  [{r['agent']}]")

            self.stdout.write("DIRANO")
            if r["izmene"]:
                for i in r["izmene"]:
                    self.stdout.write(
                        f"          {i['put']}  +{i['dodato']} −{i['obrisano']}")
            else:
                self.stdout.write("          — (zakrpa se ne može pročitati)")

            self.stdout.write(f"KAPIJE    {_kapije(r['gates'])}")
            self.stdout.write(
                f"TROŠAK    {r['pokusaja']} od {r['plafon_pokusaja']} pokušaja, "
                f"{r['centi']} od {r['plafon_centi']} centi")

            n = r["nalazi"]
            self.stdout.write(
                f"RECENZIJA {n['ukupno']} nalaza — zatvoreno {n['zatvoreno']}, "
                f"otvoreno {n['otvoreno']}"
                + (f" (blokada: {n['blokera']})" if n["blokera"] else ""))

            if r["upozorenja"]:
                self.stdout.write(self.style.ERROR("NE SPAJATI:"))
                for u in r["upozorenja"]:
                    for red in _uvij(u, "          "):
                        self.stdout.write(self.style.ERROR(red))
            else:
                self.stdout.write(self.style.SUCCESS(
                    "SMETNJI   nema — kapije zelene, nijedan nalaz nije otvoren"))

        self.stdout.write("")
        self.stdout.write("─" * 78)
        self.stdout.write("Ovo su činjenice iz baze, ne ocena. Da li izmena treba da "
                          "postoji — odlučuje čovek.")
        self.stdout.write("\nNa radnoj mašini (ne na serveru):")
        # `+` nije ukras: grana se prepisuje svakim pokušajem (ADR-0069).
        self.stdout.write(f"  git fetch {DALJINSKI} "
                          f"'+refs/heads/{rezultat.PREFIKS_GRANE}*:"
                          f"refs/remotes/agent/*'")
        self.stdout.write("\nU `main` ulazi ljudskom rukom; poslušnik gura samo u "
                          "svoju granu (ADR-0038 §6, ADR-0043).")
