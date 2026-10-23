"""Komanda `libri` — sloj znanja nad dokumentima (ADR-0031).

Radnje:
  uvezi        — PDF → LKP blokovi (sloj 2). Čovek uvozi (ADR-0074): `--actor`
                 mora da počne sa `user:`; posao ide unutar `bind(actor_id=...)`.
  reindeksiraj — napravi/osveži semantičke vektore blokova (sloj 3). Bez novog
                 materijala, pa ne traži `--actor`.
  pretrazi     — semantička pretraga blokova po prirodnom jeziku (sloj 3).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api.context import bind
from apps.libri import vektori
from apps.libri.models import Block
from apps.libri.uvoz import UvozError, uvezi


class Command(BaseCommand):
    help = "Sloj znanja: libri uvezi | reindeksiraj | pretrazi ..."

    def add_arguments(self, parser):
        parser.add_argument("radnja", choices=["uvezi", "reindeksiraj", "pretrazi"],
                            help="uvezi | reindeksiraj | pretrazi")
        parser.add_argument("--iz", default="", help="Putanja do PDF-a (uvezi).")
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

    def handle(self, *args, **options):
        radnja = options["radnja"]
        if radnja == "uvezi":
            self._uvezi(options)
        elif radnja == "reindeksiraj":
            self._reindeksiraj(options)
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

    def _reindeksiraj(self, options):
        blokovi = Block.objects.all()
        if options["dokument"]:
            blokovi = blokovi.filter(document__document_id=options["dokument"])
        rez = vektori.embeduj(blokovi)
        self.stdout.write(self.style.SUCCESS(
            f"Reindeksirano: {rez['upisano']} upisano, "
            f"{rez['preskoceno']} preskočeno."
        ))

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
