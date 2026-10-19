"""Komanda: popuni semantičke vektore veština (ADR-0120).

    python manage.py embed_vestine
    python manage.py embed_vestine --model minilm-l12-v2
    python manage.py embed_vestine --force

Prolazi kroz SVE veštine u bazi znanja (`KnowledgeFact`, predikat
`vestina.postupak`) i pravi/osvežava `KnowledgeEmbedding` izabranim modelom.
Embeduju se sve veštine, ne samo aktivne/SLOBODNE: licenca izvora se može
promeniti posle uvoza (ADR-0095), a tekst postupka ostaje isti — da promena
zastavice ne traži ponovno računanje.

`text_hash` (Memory v0.1 §6): red sa istim modelom i istim tekstom se
preskače, pa je ponovni poziv nad nepromenjenim korpusom jeftin. `--force`
briše postojeće vektore za taj model i računa ih iznova — za slučaj kad se
promeni sam model ili oblik teksta.

Ovo je JEDNOKRATNA dopuna: pri uvozu (`vestina`) nove veštine se embeduju
same (ADR-0120). Komanda postoji za prvi punjenje 452 veštine i za ponovno
embedovanje kad se model promeni. Ako model nije dostupan (fastembed/offline),
`embeduj` staje bez greške i komanda to prijavi — ne ruši se (ADR-0009).
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from apps.memory import embeddings, vestine
from apps.memory.models import KnowledgeEmbedding, KnowledgeFact
from apps.memory.vestine import PREDIKAT


class Command(BaseCommand):
    help = "Popuni/osveži semantičke vektore veština (KnowledgeEmbedding, ADR-0120)."

    def add_arguments(self, parser):
        parser.add_argument("--model", default=None,
                            help="Ključ modela (podrazumevano VESTINA_EMBEDDING_MODEL).")
        parser.add_argument("--force", action="store_true",
                            help="Obriši postojeće vektore za taj model i računaj iznova.")

    def handle(self, *args, model, force, **opts):
        mk = model or embeddings.vestina_model_key()
        facts = list(KnowledgeFact.objects.filter(predicate=PREDIKAT))
        if not facts:
            self.stdout.write("Nema veština u bazi znanja — ništa za embedovanje.")
            return
        if force:
            obrisano = KnowledgeEmbedding.objects.filter(
                model_key=mk, fact__predicate=PREDIKAT).delete()[0]
            self.stdout.write(f"--force: obrisano {obrisano} starih vektora za model {mk}.")

        t0 = time.perf_counter()
        broj = vestine.embeduj(facts, model_key=mk)
        dt = time.perf_counter() - t0

        pokriveno = KnowledgeEmbedding.objects.filter(
            model_key=mk, fact__predicate=PREDIKAT).count()
        poruka = (f"model {mk} · upisano {broj['upisano']} · preskočeno "
                  f"{broj['preskoceno']} · pokriveno {pokriveno}/{len(facts)} "
                  f"veština · {dt:.1f} s")
        if broj["upisano"] == 0 and pokriveno < len(facts):
            self.stdout.write(self.style.WARNING(
                poruka + " — model verovatno nedostupan (offline?); "
                "rangiranje radi leksički dok vektora nema (ADR-0009)."))
        else:
            self.stdout.write(self.style.SUCCESS(poruka))
