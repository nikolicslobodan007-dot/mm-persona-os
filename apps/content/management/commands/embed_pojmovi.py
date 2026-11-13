"""Komanda: popuni semantičke vektore pojmove (ADR-0120).

    python manage.py embed_pojmovi
    python manage.py embed_pojmovi --model minilm-l12-v2
    python manage.py embed_pojmovi --force

Prolazi kroz SVA pojmove u bazi znanja (`KnowledgeFact`, predikat
`pravopis.pravilo`) i pravi/osvežava `KnowledgeEmbedding` izabranim modelom.
Isti alat kao `embed_vestine`, samo nad pravilima — ista tabela i model.

`text_hash` (Memory v0.1 §6): red sa istim modelom i istim tekstom se
preskače, pa je ponovni poziv nad nepromenjenim korpusom jeftin. `--force`
briše postojeće vektore za taj model i računa ih iznova — za slučaj kad se
promeni sam model ili oblik teksta.

Ovo je JEDNOKRATNA dopuna: pri uvozu (`pojmovnik --uvezi`) nova pojmove
se embeduju sama (ADR-0120). Komanda postoji za prvo punjenje 94 termina i
za ponovno embedovanje kad se model promeni. Ako model nije dostupan
(fastembed/offline), `embeduj_pojmove` staje bez greške i komanda to prijavi
— ne ruši se (ADR-0009).
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from apps.content import pojmovnik
from apps.content.pojmovnik import PREDIKAT_POJMA
from apps.memory import embeddings
from apps.memory.models import KnowledgeEmbedding, KnowledgeFact


class Command(BaseCommand):
    help = "Popuni/osveži semantičke vektore pojmove (KnowledgeEmbedding, ADR-0120)."

    def add_arguments(self, parser):
        parser.add_argument("--model", default=None,
                            help="Ključ modela (podrazumevano VESTINA_EMBEDDING_MODEL).")
        parser.add_argument("--force", action="store_true",
                            help="Obriši postojeće vektore za taj model i računaj iznova.")

    def handle(self, *args, model, force, **opts):
        mk = model or embeddings.vestina_model_key()
        facts = list(KnowledgeFact.objects.filter(predicate=PREDIKAT_POJMA))
        if not facts:
            self.stdout.write("Nema pojmove u bazi znanja — ništa za embedovanje.")
            return
        if force:
            obrisano = KnowledgeEmbedding.objects.filter(
                model_key=mk, fact__predicate=PREDIKAT_POJMA).delete()[0]
            self.stdout.write(f"--force: obrisano {obrisano} starih vektora za model {mk}.")

        t0 = time.perf_counter()
        broj = pojmovnik.embeduj_pojmove(facts, model_key=mk)
        dt = time.perf_counter() - t0

        pokriveno = KnowledgeEmbedding.objects.filter(
            model_key=mk, fact__predicate=PREDIKAT_POJMA).count()
        poruka = (f"model {mk} · upisano {broj['upisano']} · preskočeno "
                  f"{broj['preskoceno']} · pokriveno {pokriveno}/{len(facts)} "
                  f"pojmove · {dt:.1f} s")
        if broj["upisano"] == 0 and pokriveno < len(facts):
            self.stdout.write(self.style.WARNING(
                poruka + " — model verovatno nedostupan (offline?); "
                "pretraga radi leksički dok vektora nema (ADR-0009)."))
        else:
            self.stdout.write(self.style.SUCCESS(poruka))
