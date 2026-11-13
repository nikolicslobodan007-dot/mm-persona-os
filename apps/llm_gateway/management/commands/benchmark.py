"""manage.py benchmark — WK Model Benchmark (ADR-0150).

Meri kvalitet-po-ceni modela po tipu zadatka. Za svaku rutu (provider:model_key)
pušta determinističke test slučajeve kroz gateway (only=ruta), pa ispiše po
modelu: stopu uspeha, cenu po uspešnom zadatku (USD) i prosečnu latenciju.

Primer:
  manage.py benchmark --rute anthropic:claude-sonnet-5
  manage.py benchmark --rute anthropic:claude-sonnet-5,anthropic:claude-haiku-5.5
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.llm_gateway import benchmark
from apps.personas.models import Persona


class Command(BaseCommand):
    help = "Meri stopu uspeha, cenu po uspehu i latenciju modela po zadatku."

    def add_arguments(self, p):
        p.add_argument("--rute", required=True,
                       help="Zarezom razdvojeno: provider:model_key,provider:model_key")
        p.add_argument("--persona", default="P-00003",
                       help="Persona čiji se ključ koristi (podrazumevano P-00003).")
        p.add_argument("--actor", default="user:slobodan")
        p.add_argument("--detaljno", action="store_true",
                       help="Ispiši po slučaju: PROŠAO/PAO + isečak izlaza.")
        p.add_argument("--pauza", type=float, default=0.0,
                       help="Pauza (s) između poziva — pomaže kod free rate-limita.")
        p.add_argument("--pokusaji", type=int, default=3,
                       help="Broj pokušaja po slučaju na 429 (rate-limit).")
        p.add_argument("--sudija", default="",
                       help="Ruta modela-sudije (npr. anthropic:claude-sonnet-5): "
                            "ocenjuje jezik po Pravopisu, ne samo dijakritike.")

    def handle(self, *args, **o):
        if not o["actor"].startswith("user:"):
            raise CommandError("--actor mora da počne sa 'user:'.")
        specovi = [s.strip() for s in o["rute"].split(",") if s.strip()]
        if not specovi:
            raise CommandError("Nijedna ruta nije data (--rute).")
        try:
            persona = Persona.objects.get(public_id=o["persona"])
        except Persona.DoesNotExist as e:
            raise CommandError(f"Nema persone: {o['persona']}") from e

        with bind(actor_id=o["actor"]):
            rez = benchmark.pokreni(specovi, benchmark.SLUCAJEVI, persona=persona,
                                    pauza=o["pauza"], pokusaji=o["pokusaji"],
                                    sudija=o["sudija"])
        zbir = benchmark.zbir(rez)

        n_sluc = len(benchmark.SLUCAJEVI)
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nWK Model Benchmark — {n_sluc} slučajeva × {len(specovi)} modela"))
        glava = f"{'MODEL':<34}{'USPEH':>8}{'CENA/USPEH $':>16}{'ms':>8}{'GREŠKE':>8}"
        self.stdout.write(glava)
        self.stdout.write("-" * len(glava))
        for spec in specovi:
            z = zbir.get(spec)
            if z is None:
                continue
            cps = ("—" if z.cena_po_uspehu == float("inf")
                   else f"{z.cena_po_uspehu:.6f}")
            self.stdout.write(
                f"{spec:<34}{z.prosli}/{z.n:>1}{'':>4}"
                f"{z.stopa*100:>5.0f}%{cps:>16}{z.ms_prosek:>8}{z.greske:>8}")

        self.stdout.write(self.style.MIGRATE_HEADING("\nPo kategoriji (uspeh/ukupno):"))
        kategorije = [s.kategorija for s in benchmark.SLUCAJEVI]
        vidjene = list(dict.fromkeys(kategorije))
        for spec in specovi:
            z = zbir.get(spec)
            if z is None:
                continue
            delovi = []
            for k in vidjene:
                pk = z.po_kategoriji.get(k)
                if pk:
                    delovi.append(f"{k} {pk[0]}/{pk[1]}")
            self.stdout.write(f"  {spec}: " + " · ".join(delovi))

        if o["detaljno"]:
            self.stdout.write(self.style.MIGRATE_HEADING("\nPo slučaju:"))
            for r in rez:
                oznaka = "PROŠAO" if r.uspeh else "PAO"
                rep = r.greska or r.uzorak.replace("\n", " ")
                if r.sud:
                    rep += f"  [sudija: {r.sud}]"
                self.stdout.write(f"  [{oznaka:6}] {r.spec} · {r.kljuc} "
                                  f"({r.kategorija}) — {rep}")

        self.stdout.write(self.style.MIGRATE_HEADING("\nNapomena:"))
        sudija_ime = o["sudija"]
        sudija_tekst = (f"Jezik ocenjuje sudija {sudija_ime} po Pravopisu."
                        if sudija_ime else "Provera je deterministička (bez sudije).")
        self.stdout.write("  Cena iz realnih cenovnika (12.11.2026). Nepoznat "
                          f"model → cena 0. {sudija_tekst}")
