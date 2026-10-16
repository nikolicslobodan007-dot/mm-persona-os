"""Nacrt postaje dokument — stvaran fajl, ne poruka u ćaskanju. ADR-0103.

Do sada je agentov posao završavao kao `ContentItem.body`: tekst u bazi.
Čoveku koji taj posao naručuje treba fajl koji može da otvori, pošalje i
odštampa.

Posao ne radi naš kod nego tuđi, uzet ceo i nepromenjen:
`cli-anything-libreoffice` iz `HKUDS/CLI-Anything` (Apache-2.0), zakucan na
commit u `pyproject.toml`. Koristi se kao **biblioteka**, ne kao program —
nema pokretanja procesa, nema ljuske, nema novog prava za agenta.

Dve vrste formata, i razlika je bitna:

  - `odt`, `html`, `txt` — biblioteka ih piše sama, čist Python;
  - `docx`, `pdf` — biblioteka prvo napravi ODF, pa ga preda programu
    `libreoffice --headless`. **Bez LibreOffice-a u slici oni ne rade** i
    ovde se to kaže jasnom greškom, a ne tihim praznim fajlom.

Ključ u skladištu se računa iz posla (`id` nacrta, format, `content_hash`),
a NE iz otiska bajtova: ODF je ZIP i u sebe upisuje vreme pravljenja, pa isti
nacrt dva puta daje različite bajtove. Otisak bajtova ostaje u `sha256` reda,
jer to jeste checksum tog fajla.

Pravljenje dokumenta nema spoljašnji efekat: ništa ne izlazi iz sistema, kao
ni kod `content.draft`. Zato ne traži ni odobrenje ni novu dozvolu
(ADR-0024). Objava i slanje su i dalje odvojena stvar i prolaze kroz svoja
vrata.
"""

from __future__ import annotations

import os
import tempfile

from api import audit
from apps.visuals import storage
from apps.visuals.models import MediaAsset
from common import enums as E
from common import ids as I

#: ADR-0103 — format: (mime, traži li LibreOffice u slici).
FORMATI: dict[str, tuple[str, bool]] = {
    "odt": ("application/vnd.oasis.opendocument.text", False),
    "html": ("text/html", False),
    "txt": ("text/plain", False),
    "docx": ("application/vnd.openxmlformats-officedocument."
             "wordprocessingml.document", True),
    "pdf": ("application/pdf", True),
}

#: Naš naziv formata → naziv koji očekuje tuđa biblioteka.
_PRESET = {"odt": "odt", "html": "html", "txt": "text", "docx": "docx", "pdf": "pdf"}

#: Gornja granica veličine jednog dokumenta. Nije zaštita od napada nego
#: ograda protiv greške u petlji: tekst agenta je reda kilobajta.
MAX_BAJTOVA = 10 * 1024 * 1024

ORIGIN = "generated"
NAPOMENA = ("Dokument je sastavio AI agent iz sopstvenog nacrta. "
            "Pravljen bibliotekom cli-anything-libreoffice (Apache-2.0).")


class DokumentError(Exception):
    """Pravljenje dokumenta nije uspelo — razlog je u poruci."""


def _biblioteka():
    try:
        from cli_anything.libreoffice.core import document as lo_dokument
        from cli_anything.libreoffice.core import export as lo_izvoz
        from cli_anything.libreoffice.core import writer as lo_pisac
    except ImportError as e:  # pragma: no cover — zavisnost je u pyproject.toml
        raise DokumentError(
            "Biblioteka cli-anything-libreoffice nije instalirana u ovoj slici."
        ) from e
    return lo_dokument, lo_pisac, lo_izvoz


def _projekat(item, lo_dokument, lo_pisac) -> dict:
    """Naslov je naslov, prazan red deli pasuse. Ništa pametnije zasad."""
    projekat = lo_dokument.create_document(
        doc_type="writer", name=(item.title or "dokument")[:60])
    if item.title:
        lo_pisac.add_heading(projekat, text=item.title, level=1)
    for pasus in (item.body or "").split("\n\n"):
        pasus = pasus.strip()
        if pasus:
            lo_pisac.add_paragraph(projekat, text=pasus)
    return projekat


def napravi(item, *, oblik: str = "odt", actor: str = "") -> MediaAsset:
    """Pravi dokument od nacrta i vraća `MediaAsset` koji na njega pokazuje.

    Isti nacrt u istom formatu daje isti sadržaj, pa i isti ključ u
    skladištu; drugi poziv ne pravi drugi red nego vraća postojeći.
    """
    if oblik not in FORMATI:
        raise DokumentError(
            f"Nepoznat format: {oblik}. Postoje: {', '.join(sorted(FORMATI))}.")
    if not (item.body or "").strip():
        raise DokumentError("Nacrt je prazan — nema šta da se upiše u dokument.")

    mime, treba_lo = FORMATI[oblik]
    persona = item.persona

    # Ključ se računa iz POSLA, ne iz bajtova. ODF je ZIP, a ZIP u sebe
    # upisuje vreme pravljenja — isti nacrt dva puta daje različite bajtove i
    # različit otisak, pa bi otisak fajla pravio nov red pri svakom pozivu.
    # Izmereno testom `test_isti_nacrt_ne_pravi_drugi_red` (16.10.2026).
    logicki = storage.sha256(
        f"{item.id}:{oblik}:{item.content_hash}".encode())
    kljuc = storage.key_for(persona.public_id, logicki, mime)

    postojeci = MediaAsset.objects.filter(storage_key=kljuc).first()
    if postojeci is not None:
        return postojeci

    lo_dokument, lo_pisac, lo_izvoz = _biblioteka()
    projekat = _projekat(item, lo_dokument, lo_pisac)

    with tempfile.TemporaryDirectory() as privremeni:
        putanja = os.path.join(privremeni, f"dokument.{oblik}")
        try:
            lo_izvoz.export(projekat, putanja, preset=_PRESET[oblik], overwrite=True)
        except Exception as e:  # noqa: BLE001 — tuđa biblioteka, svoja hijerarhija
            if treba_lo:
                raise DokumentError(
                    f"Format {oblik} traži LibreOffice u slici, a njega nema "
                    f"({type(e).__name__}: {str(e)[:120]}). Formati koji rade bez "
                    f"njega: odt, html, txt."
                ) from e
            raise DokumentError(f"Izvoz nije uspeo: {str(e)[:200]}") from e
        with open(putanja, "rb") as f:
            podaci = f.read()

    if len(podaci) > MAX_BAJTOVA:
        raise DokumentError(
            f"Dokument je {len(podaci)} bajtova, granica je {MAX_BAJTOVA}.")

    storage.put(podaci, key=kljuc, mime=mime)
    asset = MediaAsset.objects.create(
        public_id=I.media_asset_public_id(persona.public_id,
                                          next_sequence(persona)),
        persona=persona, kind=E.AssetKind.DOCUMENT.value, storage_key=kljuc,
        mime_type=mime, sha256=storage.sha256(podaci), origin=ORIGIN,
        rights_note=NAPOMENA)
    audit.record("content.document.created", persona=persona,
                 details={"asset": asset.public_id, "oblik": oblik,
                          "sadrzaj": str(item.id), "bajtova": len(podaci),
                          "actor": actor})
    return asset


def next_sequence(persona):
    """Redni broj za `IMG-…` public_id. Isti postupak kao za slike.

    Canon §2.2 daje `MediaAsset` prefiks `IMG-` i kad je fajl dokument; vrstu
    razlikuje `kind`, ne ime. Prefiks se ne menja usput (ADR-0103).
    """
    from apps.visuals.generator import _next_sequence

    return _next_sequence(persona)
