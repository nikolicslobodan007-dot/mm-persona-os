"""Veritas slika — URL slike → OCR → tekst. Slice 3.1.

Za memeove i screenshotove sa ugoranim tekstom (npr. crveni „Aca Srbin" post):
skine sliku (UA zbog Cloudflare-a, SSRF brana preko Libri `uvoz_web`), Tesseract
izvuče tekst (srpski ćirilica+latinica+engleski), fajl ode u skladište (MediaAsset,
kind=PHOTO). Dalje tekst ide u `izlaz` → nalaz (tri sloja) i opc. verdikt.

`--suvo`: bez mreže i troška — vraća fiksni primer teksta.
"""

from __future__ import annotations

import hashlib
import io
import urllib.error
import urllib.request

_DOZVOLJENE_SEME = ("http://", "https://")
_MAKS_BAJTOVA = 15 * 1024 * 1024
_JEZIK = "srp+srp_latn+eng"
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


def _ocr(podaci: bytes) -> tuple[str, str]:
    """Vrati (tekst, mime). Otvara sliku (PIL), čita Tesseract-om."""
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
    try:
        tekst = pytesseract.image_to_string(img, lang=_JEZIK)
    except pytesseract.TesseractError:
        tekst = pytesseract.image_to_string(img)  # rezerva: podrazumevani jezik
    return tekst, mime


def _primer_suvo(url: str) -> dict:
    return {
        "tekst": ("Kaže Aca Srbin sledeće i potpuno je u pravu: postali smo "
                  "polukriminalna država za tri dana. Stvari se mrdaju na bolje!"),
        "izvor_url": url, "asset_id": None,
    }


def procitaj(url: str, *, suvo: bool = False) -> dict:
    """URL slike → {tekst, izvor_url, asset_id}. Bez `suvo`: skine, OCR, upiše MediaAsset."""
    if suvo:
        return _primer_suvo(url)

    from apps.visuals import storage
    from apps.visuals.models import MediaAsset
    from common import enums as E

    podaci = _skini(url)
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
            "origin": "system",
        },
    )
    return {"tekst": tekst.strip(), "izvor_url": url, "asset_id": asset.public_id}
