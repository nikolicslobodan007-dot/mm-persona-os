"""Grane koje čekaju ljudsku ruku. ADR-0043.

    manage.py grane

Ispisuje zadatke koji imaju commit na grani `zadatak/TSK-…`, a još nisu
zatvoreni. Uz spisak ide i komanda kojom se te grane dovlače — jer se `main`
menja sa radne mašine, ne sa servera: serverski ključ je namerno read-only.
"""

from __future__ import annotations

import os

from django.core.management.base import BaseCommand

from apps.orchestration import rezultat

#: Kako se sa radne mašine vidi serverski repozitorijum. Menja se promenljivom
#: okruženja, da vrednost ne bi bila pretpostavka zakucana u kod (ADR-0033).
DALJINSKI = os.environ.get("PERSONA_GIT_REMOTE", "persona:apps/mm-persona-os")


class Command(BaseCommand):
    help = "Grane sa rezultatom rada agenata, koje čekaju pregled (ADR-0043)."

    def handle(self, *args, **opts):
        redovi = rezultat.za_pregled()
        if not redovi:
            self.stdout.write("Nijedna grana ne čeka pregled.")
            return

        for r in redovi:
            pale = [g for g, ok in r["gates"].items() if ok is not True]
            self.stdout.write(f"\n{r['branch']}  ({r['commit'][:12]})")
            self.stdout.write(f"  {r['task']} · {r['title']}")
            self.stdout.write(f"  agent: {r['agent']} {r['ime']}")
            if pale:
                self.stdout.write(self.style.ERROR(
                    f"  kapije nisu zelene nad ovom zakrpom: {', '.join(pale)}"))
            if r["blokera"]:
                self.stdout.write(self.style.WARNING(
                    f"  otvorenih BLOCKER nalaza: {r['blokera']}"))

        self.stdout.write("\nNa radnoj mašini (ne na serveru):")
        self.stdout.write(f"  git fetch {DALJINSKI} "
                          f"'refs/heads/{rezultat.PREFIKS_GRANE}*:"
                          f"refs/remotes/agent/*'")
        self.stdout.write("\nU `main` ulazi ljudskom rukom; poslušnik gura samo u "
                          "svoju granu (ADR-0038 §6, ADR-0043).")
