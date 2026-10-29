"""Komanda `libri` — sloj znanja nad dokumentima (ADR-0031).

Radnje:
  uvezi        — PDF → LKP blokovi (sloj 2). Čovek uvozi (ADR-0074): `--actor`
                 mora da počne sa `user:`; posao ide unutar `bind(actor_id=...)`.
  reindeksiraj — napravi/osveži semantičke vektore blokova (sloj 3). Bez novog
                 materijala, pa ne traži `--actor`.
  pretrazi     — semantička pretraga blokova po prirodnom jeziku (sloj 3).
  tvrdnje      — izvuci (subjekat, relacija, vrednost) iz blokova dokumenta u
                 KnowledgeFact (sloj 4a). Čovek pokreće izvođenje: `--actor user:`.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.libri import (
    dosije,
    ekstrakt,
    ekstrakt_entiteti,
    entiteti,
    pouzdanost,
    steps,
    tvrdnje,
    uvoz_web,
    vektori,
)
from apps.libri.models import Block, LibriDocument
from apps.libri.uvoz import UvozError, uvezi


class Command(BaseCommand):
    help = "Sloj znanja: libri uvezi | reindeksiraj | pretrazi | tvrdnje ..."

    def add_arguments(self, parser):
        parser.add_argument(
            "radnja",
            choices=["uvezi", "uvezi-web", "reindeksiraj", "pretrazi", "tvrdnje",
                     "entiteti", "pouzdanost", "dosije", "plan"],
            help=("uvezi | uvezi-web | reindeksiraj | pretrazi | tvrdnje | "
                  "entiteti | pouzdanost | dosije | plan"))
        parser.add_argument("--iz", default="", help="Putanja do PDF-a (uvezi).")
        parser.add_argument("--url", default="",
                            help="Javni URL (uvezi-web).")
        parser.add_argument("--naslov", default="",
                            help="Naslov dokumenta (podrazumevano: ime fajla).")
        parser.add_argument("--licenca", default="",
                            help="LicenseBox: SLOBODNA, ZARAZNA, ZABRANJENA, NEPOZNATA.")
        parser.add_argument("--naziv-licence", default="",
                            help="Naziv licence — obavezan kad je --licenca SLOBODNA.")
        parser.add_argument("--actor", default="",
                            help="Mora da počne sa 'user:' (uvezi — čovek uvozi).")
        parser.add_argument("--dokument", default="",
                            help="document_id (reindeksiraj — samo taj dokument).")
        parser.add_argument("--upit", default="", help="Tekst upita (pretrazi).")
        parser.add_argument("--top", type=int, default=5,
                            help="Koliko blokova vratiti (pretrazi).")
        parser.add_argument("--llm", action="store_true",
                            help="tvrdnje/entiteti/dosije: LLM sloj (fallback na osnovu).")

    def handle(self, *args, **options):
        radnja = options["radnja"]
        if radnja == "uvezi":
            self._uvezi(options)
        elif radnja == "uvezi-web":
            self._uvezi_web(options)
        elif radnja == "reindeksiraj":
            self._reindeksiraj(options)
        elif radnja == "tvrdnje":
            self._tvrdnje(options)
        elif radnja == "entiteti":
            self._entiteti(options)
        elif radnja == "pouzdanost":
            self._pouzdanost(options)
        elif radnja == "dosije":
            self._dosije(options)
        elif radnja == "plan":
            self._plan(options)
        else:
            self._pretrazi(options)

    def _uvezi(self, options):
        iz = options["iz"]
        actor = options["actor"]
        if not iz:
            raise CommandError("uvezi traži --iz <PDF>.")
        if not actor.startswith("user:"):
            raise CommandError(
                "--actor mora da počne sa 'user:' (ADR-0074 — čovek uvozi)."
            )
        if not options["licenca"]:
            raise CommandError("uvezi traži --licenca.")
        try:
            with bind(actor_id=actor):
                dok = uvezi(
                    iz,
                    naslov=options["naslov"],
                    licenca=options["licenca"],
                    naziv_licence=options["naziv_licence"],
                )
        except UvozError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(self.style.SUCCESS(
            f"Uvezeno: {dok.document_id} „{dok.title}” — "
            f"{dok.pages} str., {dok.blocks.count()} blokova."
        ))

    def _uvezi_web(self, options):
        url = options["url"]
        actor = options["actor"]
        if not url:
            raise CommandError("uvezi-web traži --url <URL>.")
        if not actor.startswith("user:"):
            raise CommandError(
                "--actor mora da počne sa 'user:' (ADR-0074 — čovek uvozi).")
        if not options["licenca"]:
            raise CommandError("uvezi-web traži --licenca.")
        try:
            with bind(actor_id=actor):
                dok = uvoz_web.uvezi_url(
                    url,
                    naslov=options["naslov"],
                    licenca=options["licenca"],
                    naziv_licence=options["naziv_licence"],
                )
        except UvozError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(self.style.SUCCESS(
            f"Uvezeno (web): {dok.document_id} „{dok.title}” — "
            f"{dok.blocks.count()} blokova."
        ))

    def _reindeksiraj(self, options):
        blokovi = Block.objects.all()
        if options["dokument"]:
            blokovi = blokovi.filter(document__document_id=options["dokument"])
        rez = vektori.embeduj(blokovi)
        self.stdout.write(self.style.SUCCESS(
            f"Reindeksirano: {rez['upisano']} upisano, "
            f"{rez['preskoceno']} preskočeno."
        ))

    def _tvrdnje(self, options):
        actor = options["actor"]
        doc_id = options["dokument"]
        if not actor.startswith("user:"):
            raise CommandError(
                "--actor mora da počne sa 'user:' (čovek pokreće izvođenje tvrdnji)."
            )
        if not doc_id:
            raise CommandError("tvrdnje traži --dokument <document_id>.")
        dok = LibriDocument.objects.filter(document_id=doc_id).first()
        if dok is None:
            raise CommandError(f"Dokument ne postoji: {doc_id}.")
        try:
            with bind(actor_id=actor):
                rez = (ekstrakt.upisi(dok) if options["llm"]
                       else tvrdnje.upisi(dok))
        except ValueError as e:
            raise CommandError(str(e)) from e
        put = "LLM" if options["llm"] else "osnova"
        self.stdout.write(self.style.SUCCESS(
            f"Tvrdnje za {doc_id} ({put}): {rez['upisano']} upisano, "
            f"{rez['obrisano']} staro obrisano."
        ))

    def _entiteti(self, options):
        actor = options["actor"]
        doc_id = options["dokument"]
        if not actor.startswith("user:"):
            raise CommandError(
                "--actor mora da počne sa 'user:' (čovek pokreće izvođenje entiteta)."
            )
        if not doc_id:
            raise CommandError("entiteti traži --dokument <document_id>.")
        dok = LibriDocument.objects.filter(document_id=doc_id).first()
        if dok is None:
            raise CommandError(f"Dokument ne postoji: {doc_id}.")
        try:
            with bind(actor_id=actor):
                rez = (ekstrakt_entiteti.upisi(dok) if options["llm"]
                       else entiteti.upisi(dok))
        except ValueError as e:
            raise CommandError(str(e)) from e
        put = "LLM" if options["llm"] else "osnova"
        self.stdout.write(self.style.SUCCESS(
            f"Entiteti za {doc_id} ({put}): {rez['entiteta']} entiteta, "
            f"{rez['odnosa']} odnosa, {rez['obrisano']} staro obrisano."
        ))

    def _pouzdanost(self, options):
        actor = options["actor"]
        doc_id = options["dokument"]
        if not actor.startswith("user:"):
            raise CommandError(
                "--actor mora da počne sa 'user:' (čovek pokreće ocenjivanje)."
            )
        if not doc_id:
            raise CommandError("pouzdanost traži --dokument <document_id>.")
        dok = LibriDocument.objects.filter(document_id=doc_id).first()
        if dok is None:
            raise CommandError(f"Dokument ne postoji: {doc_id}.")
        try:
            with bind(actor_id=actor):
                rez = pouzdanost.upisi(dok)
        except ValueError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(self.style.SUCCESS(
            f"Pouzdanost za {doc_id}: {rez['ocenjeno']} ocenjeno, "
            f"{rez['obrisano']} staro obrisano."
        ))

    def _dosije(self, options):
        doc_id = options["dokument"]
        if not doc_id:
            raise CommandError("dosije traži --dokument <document_id>.")
        dok = LibriDocument.objects.filter(document_id=doc_id).first()
        if dok is None:
            raise CommandError(f"Dokument ne postoji: {doc_id}.")
        if options["llm"]:
            actor = options["actor"]
            if not actor.startswith("user:"):
                raise CommandError(
                    "--actor mora da počne sa 'user:' (čovek pokreće LLM analizu dosija).")
            with bind(actor_id=actor):
                self.stdout.write(dosije.sastavi(dok, llm=True))
        else:
            self.stdout.write(dosije.sastavi(dok))

    def _plan(self, options):
        actor = options["actor"]
        doc_id = options["dokument"]
        if not actor.startswith("user:"):
            raise CommandError(
                "--actor mora da počne sa 'user:' (čovek pokreće Libri tok)."
            )
        if not doc_id:
            raise CommandError("plan traži --dokument <document_id>.")
        dok = LibriDocument.objects.filter(document_id=doc_id).first()
        if dok is None:
            raise CommandError(f"Dokument ne postoji: {doc_id}.")
        try:
            with bind(actor_id=actor):
                rez = steps.pokreni(dok)
        except steps.LibriPlanError as e:
            raise CommandError(
                f"Tok zaustavljen na fazi {e.faza}: {e.razlog}") from e
        for f in rez["faze"]:
            detalji = ", ".join(f"{k}: {v}" for k, v in f["rezultat"].items())
            self.stdout.write(self.style.SUCCESS(f"  ✓ {f['naziv']} — {detalji}"))
        self.stdout.write("")
        self.stdout.write(rez["dosije"])

    def _pretrazi(self, options):
        upit = options["upit"]
        if not upit:
            raise CommandError("pretrazi traži --upit <tekst>.")
        rez = vektori.pretrazi(upit, top_k=options["top"],
                               document_id=options["dokument"] or None)
        if rez is None:
            self.stdout.write(self.style.WARNING(
                "Semantički model nije dostupan (offline) — pretraga nije izvršena."))
            return
        if not rez:
            self.stdout.write("Nema rezultata (nema vektora ili filter sve odseca).")
            return
        for blok, dist in rez:
            isecak = blok.text[:80].replace("\n", " ")
            self.stdout.write(
                f"  {dist:.3f}  {blok.document.document_id}#{blok.order} "
                f"[{blok.block_type}]  {isecak!r}")
