"""Veritas slika — URL/fajl slike → OCR → tekst. Slice 3.1.

Za memeove i screenshotove sa ugoranim tekstom (npr. crveni „Aca Srbin" post):
uzme sliku (URL: skine uz UA + SSRF branu; ili lokalni fajl), Tesseract izvuče
tekst (srpski latinica+ćirilica+engleski), fajl ode u skladište (MediaAsset).

Pretprocesiranje: beli tekst na obojenoj podlozi (čest meme) Tesseract na sirovoj
slici pročita kao prazno. Zato probamo više varijanti (grayscale + prag/invert) i
uzmemo onu sa najviše teksta — radi i za taman-na-svetlom i za svetao-na-boji.

`--suvo`: bez mreže i troška — vraća fiksni primer teksta.
"""

from __future__ import annotations

import hashlib
import io
import os
import urllib.error
import urllib.request

_DOZVOLJENE_SEME = ("http://", "https://")
_MAKS_BAJTOVA = 15 * 1024 * 1024
_JEZIK = "srp_latn+srp+eng"
_PRAG = 140
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_PIL_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}
_MIME_EKST = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


class SlikaGreska(Exception):
    def __init__(self, kod: str, detalj: str = ""):
        super().__init__(f"{kod}: {detalj}")
        self.kod, self.detalj = kod, detalj


def _skini(url: str) -> bytes:
    if not url.startswith(_DOZVOLJENE_SEME):
        raise SlikaGreska("LOSE_URL", url[:80])
    from apps.libri import uvoz_web
    try:
        uvoz_web.proveri_bezbedan(url)
    except Exception as e:  # noqa: BLE001 — SSRF brana sme da odbije
        raise SlikaGreska("NEBEZBEDAN_URL", str(e)[:120]) from e
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            podaci = r.read(_MAKS_BAJTOVA + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SlikaGreska("SKIDANJE_PALO", str(e)[:120]) from e
    if len(podaci) > _MAKS_BAJTOVA:
        raise SlikaGreska("SLIKA_PREVELIKA", f"> {_MAKS_BAJTOVA // (1024 * 1024)} MB")
    return podaci


def _ucitaj_fajl(putanja: str) -> bytes:
    if not os.path.isfile(putanja):
        raise SlikaGreska("NEMA_FAJLA", putanja[:120])
    with open(putanja, "rb") as fh:
        podaci = fh.read(_MAKS_BAJTOVA + 1)
    if len(podaci) > _MAKS_BAJTOVA:
        raise SlikaGreska("SLIKA_PREVELIKA", f"> {_MAKS_BAJTOVA // (1024 * 1024)} MB")
    return podaci


def _varijante(img):
    """Varijante slike za OCR: originalni sivi ton, pa prag+invert (svetao tekst na boji)."""
    from PIL import ImageOps

    g = img.convert("L")
    yield g                                                 # taman tekst na svetlom
    svetlo = g.point(lambda p: 255 if p > _PRAG else 0)
    yield ImageOps.invert(svetlo)                           # svetao tekst na tamnom/u boji
    yield g.point(lambda p: 0 if p > _PRAG else 255)        # alternativna binarizacija


def _ocr(podaci: bytes) -> tuple[str, str]:
    """Vrati (tekst, mime). Probaj više varijanti slike, uzmi onu sa najviše teksta."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        raise SlikaGreska("ZAVISNOST_NEDOSTAJE", str(e)) from e
    try:
        img = Image.open(io.BytesIO(podaci))
        img.load()
    except Exception as e:  # noqa: BLE001 — nije validna slika
        raise SlikaGreska("NIJE_SLIKA", str(e)[:120]) from e
    mime = _PIL_MIME.get(img.format or "", "image/png")

    najbolji = ""
    for v in _varijante(img):
        try:
            tekst = pytesseract.image_to_string(v, lang=_JEZIK)
        except pytesseract.TesseractError:
            tekst = pytesseract.image_to_string(v)  # rezerva: podrazumevani jezik
        if len(tekst.strip()) > len(najbolji.strip()):
            najbolji = tekst
    return najbolji, mime


def _primer_suvo(izvor: str) -> dict:
    return {
        "tekst": ("Kaže Aca Srbin sledeće i potpuno je u pravu: postali smo "
                  "polukriminalna država za tri dana. Stvari se mrdaju na bolje!"),
        "izvor_url": izvor, "asset_id": None,
    }


def procitaj(izvor: str, *, suvo: bool = False, je_fajl: bool = False) -> dict:
    """Slika (URL ili lokalni fajl) → {tekst, izvor_url, asset_id}.

    `je_fajl=True`: `izvor` je putanja do lokalne slike (ne skida se).
    """
    if suvo:
        return _primer_suvo(izvor)

    from apps.visuals import storage
    from apps.visuals.models import MediaAsset
    from common import enums as E

    podaci = _ucitaj_fajl(izvor) if je_fajl else _skini(izvor)
    tekst, mime = _ocr(podaci)

    sha = hashlib.sha256(podaci).hexdigest()
    kljuc = f"veritas/slika/{sha[:32]}{_MIME_EKST.get(mime, '.png')}"
    storage.put(podaci, key=kljuc, mime=mime)
    asset, _ = MediaAsset.objects.get_or_create(
        storage_key=kljuc,
        defaults={
            "public_id": f"IMG-{sha[:12]}",
            "kind": E.AssetKind.PHOTO.value,
            "mime_type": mime,
            "sha256": sha,
            "origin": "user_owned" if je_fajl else "system",
        },
    )
    return {"tekst": tekst.strip(), "izvor_url": izvor, "asset_id": asset.public_id}
