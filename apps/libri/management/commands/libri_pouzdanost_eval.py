"""Merenje računice pouzdanosti na scenarijima (ADR-0031 sloj 4b §3.3).

    python manage.py libri_pouzdanost_eval

Računica je deterministička, pa se meri svuda — i u gejtu i na produkciji. Za svaki
scenario poredi izračunatih pet osa + `ukupno` sa očekivanim. Semantika (potkrepa i
nezavisnost rastu sa saglasnim izvorima, stabilnost pada sa protivrečnim) vidi se u
zakucanim vrednostima, a dodatno je proverava test.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.libri import pouzdanost
from apps.libri.golden import POUZDANOST_SCENARIJI


def run_eval() -> dict:
    greske: list = []
    rezultati: list = []
    for s in POUZDANOST_SCENARIJI:
        ns = pouzdanost.scenario_namespaces(s["tvrdnje"])
        o = pouzdanost.oceni(ns[s["cilj"]], ns)
        dobijeno = {k: o[k] for k in
                    ("pouzdanost", "nezavisnost", "blizina", "potkrepljenost",
                     "stabilnost", "ukupno")}
        rezultati.append((s["opis"], dobijeno))
        if dobijeno != s["ocekivano"]:
            greske.append((s["opis"], dobijeno, s["ocekivano"]))
    return {"ispravno": not greske, "greske": greske, "rezultati": rezultati}


class Command(BaseCommand):
    help = "Izmeri računicu pouzdanosti po pet osa na zlatnim scenarijima."

    def handle(self, *args, **opts):
        r = run_eval()
        for opis, dobijeno in r["rezultati"]:
            self.stdout.write(f"{opis}: {dobijeno}")
        if r["ispravno"]:
            self.stdout.write(self.style.SUCCESS("pouzdanost (osnova) · svi scenariji OK"))
        else:
            for opis, dobijeno, ocekivano in r["greske"]:
                self.stdout.write(f"  NESLAGANJE {opis}: {dobijeno} != {ocekivano}")
