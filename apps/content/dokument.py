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
import re
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


#: ADR-0148 — naslov je često sirov nalog („Napiši dubinski članak … o …");
#: skida se instrukcioni uvod da u dokumentu stoji čist naslov teme.
_UVOD = re.compile(r"^(napi[\u0161s]i|napisati|napravi|sastavi|izradi|pripremi)"
                   r"\b.*?\bo\s+", re.IGNORECASE)


def _cist_naslov(sirov: str) -> str:
    """Od sirovog naloga napravi kratak, čitljiv naslov dokumenta (ADR-0148)."""
    t = (sirov or "").strip()
    m = _UVOD.search(t)
    if m:
        t = t[m.end():]
    # Jezgro teme: iseci na prvom zarezu, zagradi ili „oslanjajući".
    t = re.split(r"[,(]|\boslanjaj", t, maxsplit=1)[0].strip(" .:-\u2014\t").strip()
    if not t:
        t = (sirov or "dokument").strip()
    return (t[0].upper() + t[1:] if t else t)[:120]


def _blokovi(telo: str) -> list[tuple[str, str]]:
    """Telo → lista (vrsta, tekst): „h" za podnaslov, „p" za pasus (ADR-0148).

    Kratka samostalna linija bez završne interpunkcije, sa telom posle, je
    podnaslov; sve ostalo je pasus. `##` markdown se takođe prepoznaje.
    """
    out: list[tuple[str, str]] = []
    for blok in (telo or "").split("\n\n"):
        blok = blok.strip()
        if not blok:
            continue
        prva, _, ostatak = blok.partition("\n")
        prva, ostatak = prva.strip(), ostatak.strip()
        podnaslov = (ostatak and len(prva) <= 70
                     and not prva.endswith((".", "!", "?", ":", "\u201c"))
                     and not prva.startswith(("\u2014", "- ", "* ")))
        if podnaslov or prva.startswith("#"):
            out.append(("h", prva.lstrip("# ").strip()))
            if ostatak:
                out.append(("p", ostatak))
        else:
            out.append(("p", blok))
    return out


def _projekat(item, lo_dokument, lo_pisac) -> dict:
    """Čist naslov (heading 1), podnaslovi (heading 2), pasusi (ADR-0148)."""
    naslov = _cist_naslov(item.title)
    projekat = lo_dokument.create_document(doc_type="writer", name=naslov[:60])
    if naslov:
        lo_pisac.add_heading(projekat, text=naslov, level=1)
    for vrsta, tekst in _blokovi(item.body or ""):
        if vrsta == "h":
            lo_pisac.add_heading(projekat, text=tekst, level=2)
        else:
            lo_pisac.add_paragraph(projekat, text=tekst)
    return projekat


def kljuc_za(item, oblik: str) -> str:
    """Ključ u skladištu za (nacrt, format). ADR-0103 tačka 6.

    Računa se iz posla, ne iz bajtova, pa je isti pre i posle pravljenja
    fajla — zato i služi kao veza između nacrta i dokumenta, dok model tu
    vezu nema (ADR-0104).
    """
    mime, _ = FORMATI[oblik]
    logicki = storage.sha256(f"{item.id}:{oblik}:{item.content_hash}".encode())
    return storage.key_for(item.persona.public_id, logicki, mime)


def postojeci(item, oblik: str = "odt") -> MediaAsset | None:
    """Dokument koji za ovaj nacrt već postoji, ili `None`."""
    if oblik not in FORMATI:
        return None
    return MediaAsset.objects.filter(storage_key=kljuc_za(item, oblik)).first()


def postojeci_za(items, oblik: str = "odt") -> dict[str, MediaAsset]:
    """Isto, ali za spisak nacrta i jednim upitom — za konzolu."""
    if oblik not in FORMATI:
        return {}
    po_kljucu = {kljuc_za(i, oblik): str(i.id) for i in items}
    nadjeni = MediaAsset.objects.filter(storage_key__in=list(po_kljucu))
    return {po_kljucu[a.storage_key]: a for a in nadjeni}


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

    # Ključ se računa iz POSLA, ne iz bajtova (vidi `kljuc_za`).
    kljuc = kljuc_za(item, oblik)
    vec_postoji = MediaAsset.objects.filter(storage_key=kljuc).first()
    if vec_postoji is not None:
        return vec_postoji

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
