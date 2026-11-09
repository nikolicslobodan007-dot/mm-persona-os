"""manage.py sakupi — iz linka/slike/klipa izvuci VEŠTINE (za korpus). Sakupljač.

    sakupi --url https://...                 # web stranica → veštine
    sakupi --slika https://.../meme.png      # slika sa veba (OCR) → veštine
    sakupi --fajl /putanja/screenshot.png    # lokalna slika (OCR) → veštine
    sakupi --klip-url https://youtu.be/...   # YouTube/video (ASR) → veštine
    sakupi --url ... --izlaz korpus/vestine/sakupljeno-X.json   # upiši JSON za uvoz
    sakupi --url ... --suvo                   # bez mreže i troška
    sakupi --klip-fajl ... --bez-filtera      # destiluj bez pokazivač pre-filtera

Ingest je isti kao Veritas (web/OCR/ASR), ali se iz teksta vade primenljivi
postupci, ne tvrdnje. Pre destilacije ide POKAZIVAČ PRE-FILTER (deterministički,
bez LLM-a): reklama/prazno se preskače (bez troška), a klip koji samo pokazuje na
resurs (link) se prati — destiluje se resurs, ne reklama. Rezultat je u formatu
korpusa {ime, koraci, napomene, pouzdanost}. Uvoz u bazu znanja je zaseban korak
(`vestina`), gde se određuje LICENCA — sakupljač je NE pogađa (ADR-0059:
podrazumevano NEPOZNATA). Daj TAČNO jedan ulaz.
"""

from __future__ import annotations

import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.memory.sakupljanje import destilator, ulaz
from apps.memory.veritas import pokazivac

_MAKS_TEKST = 12000  # ulaz u LLM — duže se seče (cena/tokeni)

_ULAZI = (("url", "web"), ("slika", "slika"), ("fajl", "fajl"),
          ("klip_url", "klip"), ("klip_fajl", "klip_fajl"))


def _url_iz_pokazivaca(pokazivaci):
    """Prvi link-pokazivač → normalizovan http(s) URL (ili None)."""
    for p in pokazivaci:
        if p["vrsta"] == "url":
            return p["vrednost"]
        if p["vrsta"] == "www":
            return "https://" + p["vrednost"]
        if p["vrsta"] == "github":
            return "https://github.com/" + p["vrednost"]
    return None


class Command(BaseCommand):
    help = "Sakupljač: iz linka/slike/klipa izvuci primenljive veštine (za korpus)."

    def add_arguments(self, p):
        p.add_argument("--url", help="URL web stranice.")
        p.add_argument("--slika", help="URL slike (OCR).")
        p.add_argument("--fajl", help="Putanja do lokalne slike (OCR).")
        p.add_argument("--klip-url", help="URL videa/audija (YouTube…, ASR).")
        p.add_argument("--klip-fajl",
                       help="Putanja do lokalnog video/audio fajla (ručno skinut YT).")
        p.add_argument("--maks", type=int, default=8, help="Najviše veština.")
        p.add_argument("--izlaz", help="Upiši veštine u ovaj .json (za kasniji `vestina` uvoz).")
        p.add_argument("--suvo", action="store_true", help="Bez mreže i troška (proba).")
        p.add_argument("--bez-filtera", action="store_true",
                       help="Preskoči pokazivač pre-filter (destiluj svaki ulaz).")

    def handle(self, *args, **o):
        dati = [(arg, vrsta) for arg, vrsta in _ULAZI if o.get(arg)]
        if len(dati) != 1:
            raise CommandError(
                "Daj TAČNO jedan ulaz: --url, --slika, --fajl, --klip-url ILI --klip-fajl.")
        arg, vrsta = dati[0]
        vrednost = o[arg]

        try:
            izvor = ulaz.procitaj(vrsta, vrednost, suvo=o["suvo"])
        except ulaz.UlazGreska as e:
            self.stderr.write(self.style.ERROR(f"ulaz pao: {e}"))
            return

        tekst = (izvor["tekst"] or "").strip()
        if not tekst:
            self.stdout.write("Prazan tekst iz izvora — nema šta da se destiluje.")
            return

        # --- Pokazivač pre-filter (deterministički, bez LLM-a) ---
        if not o.get("bez_filtera"):
            izvor, tekst = self._pre_filter(izvor, tekst, o)
            if tekst is None:
                return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"# izvor [{izvor['vrsta']}]: {izvor['naslov'][:80]} ({len(tekst)} znakova teksta)"))

        nap = (f"Sakupljeno iz {izvor['vrsta']}: {izvor['izvor']} — "
               "naš opis postupka, ne prepis. Licenca: PROVERITI pri uvozu.")
        llm = destilator.napravi_llm(o["suvo"])
        r = destilator.destiluj(tekst[:_MAKS_TEKST], naslov=izvor["naslov"], napomena=nap,
                                maks=o["maks"], llm=llm, suvo=o["suvo"])
        vestine = r["vestine"]

        cena = "suvo" if o["suvo"] else f"{r['etiketa']} · {r['cena']}¢"
        self.stdout.write(self.style.SUCCESS(f"# {len(vestine)} veština ({cena}):"))
        for v in vestine:
            self.stdout.write(f"— {v['ime']} (pouzdanost {v['pouzdanost']})")
            for k in v["koraci"]:
                self.stdout.write(f"   • {k}")

        if o.get("izlaz") and vestine:
            self._upisi(o["izlaz"], vestine, izvor["izvor"])

    def _pre_filter(self, izvor, tekst, o):
        """Pokazivač-detektor pre destilacije. Vraća (izvor, tekst) ili (izvor, None) za preskok.

        - preskoci / trazi_izvor → ne troši LLM (None);
        - prati_pokazivac → dohvati link pa destiluj resurs (zameni izvor/tekst);
        - analiziraj → nastavi sa originalnim tekstom.
        """
        odluka = pokazivac.analiziraj(tekst)
        self.stdout.write(f"# pokazivač: {odluka['preporuka']} — {odluka['obrazlozenje']}")

        if odluka["preporuka"] == "preskoci":
            self.stdout.write("Preskačem — nema sadržaja za veštinu (reklama/prazno).")
            return izvor, None

        if odluka["preporuka"] == "trazi_izvor":
            self.stdout.write(
                "Preskačem — pokazivač bez linka (pretraga izvora još nije uključena). "
                "Dodaj --bez-filtera da ipak destiluješ.")
            return izvor, None

        if odluka["preporuka"] == "prati_pokazivac":
            url = _url_iz_pokazivaca(odluka["pokazivaci"])
            if url:
                self.stdout.write(f"# pratim pokazivač → {url}")
                try:
                    izvor2 = ulaz.procitaj("web", url, suvo=o["suvo"])
                except ulaz.UlazGreska as e:
                    self.stdout.write(f"Pokazivač nedostupan ({e}) — destilujem originalni tekst.")
                    return izvor, tekst
                tekst2 = (izvor2["tekst"] or "").strip()
                if tekst2:
                    return izvor2, tekst2
                self.stdout.write("Resurs prazan — destilujem originalni tekst.")

        return izvor, tekst

    def _upisi(self, izlaz, vestine, izvor_uri):
        baza = getattr(settings, "BASE_DIR", os.getcwd())
        put = izlaz if os.path.isabs(izlaz) else os.path.join(baza, izlaz)
        os.makedirs(os.path.dirname(put) or ".", exist_ok=True)
        with open(put, "w", encoding="utf-8") as fh:
            json.dump(vestine, fh, ensure_ascii=False, indent=2)
        rel = os.path.relpath(put, baza)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"UPISANO {len(vestine)} veština → {rel}"))
        self.stdout.write(
            "Uvoz u korpus (postavi licencu!): python manage.py vestina "
            f"--datoteka {rel} --izvor {izvor_uri} --uri {izvor_uri} "
            "--licenca <KUTIJA> --naziv-licence <IME> --actor user:slobodan --commit")
