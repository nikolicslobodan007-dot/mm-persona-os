"""Komanda: popuni semantičke vektore članova propisa (ADR-0120).

    python manage.py embed_clanovi
    python manage.py embed_clanovi --model minilm-l12-v2
    python manage.py embed_clanovi --force

Prolazi kroz SVE članove u bazi znanja (`KnowledgeFact`, predikat `propis.clan`)
i pravi/osvežava `KnowledgeEmbedding`. Isti alat kao `embed_pojmovi`, nad članovima.

Pri uvozu (`propisi --uvezi`) novi članovi se embeduju sami (ADR-0120). Komanda
postoji za prvo punjenje i za ponovno embedovanje kad se model promeni. Ako model
nije dostupan (fastembed/offline), staje bez greške i prijavi — ne ruši se (ADR-0009).
"""
from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from apps.content import propisi
from apps.content.propisi import PREDIKAT_CLANA
from apps.memory import embeddings
from apps.memory.models import KnowledgeEmbedding, KnowledgeFact


class Command(BaseCommand):
    help = "Popuni/osveži semantičke vektore članova propisa (KnowledgeEmbedding, ADR-0120)."

    def add_arguments(self, parser):
        parser.add_argument("--model", default=None,
                            help="Ključ modela (podrazumevano VESTINA_EMBEDDING_MODEL).")
        parser.add_argument("--force", action="store_true",
                            help="Obriši postojeće vektore za taj model i računaj iznova.")

    def handle(self, *args, model, force, **opts):
        mk = model or embeddings.vestina_model_key()
        facts = list(KnowledgeFact.objects.filter(predicate=PREDIKAT_CLANA))
        if not facts:
            self.stdout.write("Nema članova u bazi znanja — ništa za embedovanje.")
            return
        if force:
            obrisano = KnowledgeEmbedding.objects.filter(
                model_key=mk, fact__predicate=PREDIKAT_CLANA).delete()[0]
            self.stdout.write(f"--force: obrisano {obrisano} starih vektora za model {mk}.")

        t0 = time.perf_counter()
        broj = propisi.embeduj_clanove(facts, model_key=mk)
        dt = time.perf_counter() - t0

        pokriveno = KnowledgeEmbedding.objects.filter(
            model_key=mk, fact__predicate=PREDIKAT_CLANA).count()
        poruka = (f"model {mk} · upisano {broj['upisano']} · preskočeno "
                  f"{broj['preskoceno']} · pokriveno {pokriveno}/{len(facts)} "
                  f"članova · {dt:.1f} s")
        if broj["upisano"] == 0 and pokriveno < len(facts):
            self.stdout.write(self.style.WARNING(
                poruka + " — model verovatno nedostupan (offline?); "
                "pretraga radi leksički dok vektora nema (ADR-0009)."))
        else:
            self.stdout.write(self.style.SUCCESS(poruka))
