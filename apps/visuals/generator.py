"""Lik agenta — profilna slika i galerija. ADR-0018.

Agent koji radi umesto čoveka mora da ima lice, i to **isto lice** na svakoj
slici. Postupak je zato u dva koraka:

  1. **Portret** se pravi jednom, iz dosijea (ADR-0017), i postaje
     `VisualProfile.reference_asset` — sidro identiteta.
  2. **Svaka sledeća slika** nastaje izmenom portreta (`/images/edits`), pa je
     na njoj ista osoba u drugoj sceni.

Tri pravila koja se ne zaobilaze:

  - **Lice je sintetičko.** Nijedan prompt ne sme da imenuje stvarnu osobu;
    tvrda zabrana `REAL_PERSON_LIKENESS` (Canon §9.4 t.7) proverava se pre
    poziva provajdera, ne posle.
  - **Slika je označena kao AI.** `origin=generated`, model i hash prompta uz
    svaki fajl, plus zapis u `rights_note`.
  - **Trošak se knjiži** u `CostLedger` (bucket `media_generation`), po slici.

Tajne (ključ provajdera, pristup storage-u) su samo u `.env.prod`.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from api import audit
from apps.personas.models import Persona
from apps.visuals import storage
from apps.visuals.models import (
    AssetCollection,
    AssetCollectionItem,
    MediaAsset,
    VisualProfile,
)
from common import enums as E
from common import ids as I

GALLERY = "Galerija"
CAPABILITY_ACTION = "visual.generate"
#: Ono što slika nikada ne sme da prikaže. Provera ide nad tekstom koji je
#: uneo čovek (scena, opis izgleda) — ne nad našim sopstvenim šablonom, u kom
#: iste reči stoje kao zabrana („bez logotipa”). Oblici su srpski, pa se traži
#: koren reči, ne cela reč.
FORBIDDEN = re.compile(
    r"(logo\w*|brend\w*|zaštitn\w* znak\w*|watermark|vodeni žig\w*|lič\w+ kart\w+|"
    r"pasoš\w*|kreditn\w* kartic\w*|policij\w*|vojn\w*)", re.I)


class ImageError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class Result:
    asset: MediaAsset
    prompt: str
    model: str
    cost_eur_cents: int


def enabled() -> bool:
    return bool(getattr(settings, "IMAGE_ENABLED", False))


def credential_ref(persona: Persona | None = None) -> tuple[str | None, str]:
    """(referenca, izvor) — `persona` ako agent ima svoj ključ, inače `shared`."""
    base = getattr(settings, "IMAGE_CREDENTIALS", {}).get(settings.IMAGE_PROVIDER, "")
    if persona is not None and base.startswith("env:"):
        import os

        name = f"{base[4:]}_{persona.public_id.replace('-', '')}"
        if os.environ.get(name, "").strip():
            return f"env:{name}", "persona"
    return (base, "shared") if base else (None, "none")


# ---------------------------------------------------------------- opis lika


def appearance_of(persona: Persona) -> str:
    """Opis iz dosijea; ako ga nema, stari opis iz vizuelnog profila.

    Dosije ima prednost namerno: njega operater menja u konzoli, pa je on
    izvor istine za izgled (ADR-0017).
    """
    from apps.personas.org import dossier_of, position_of

    d = dossier_of(persona)
    if d is not None and d.appearance_prompt.strip():
        base = d.appearance_prompt.strip()
    elif d is not None and any((d.build, d.hair_color, d.eye_color)):
        bits = [x for x in (d.build, d.hair_color and f"{d.hair_color} kosa",
                            d.hair_style, d.eye_color and f"{d.eye_color} oči") if x]
        base = "Odrasla osoba, " + ", ".join(bits) + "."
    else:
        vp = VisualProfile.objects.filter(persona=persona).first()
        base = vp.style_prompt.strip() if vp else ""
    if not base:
        raise ImageError("VALIDATION_ERROR",
                         "Dosije nema opis izgleda — popuni ga pre slike.")
    pos = position_of(persona)
    if pos is not None:
        # Samo prvo slovo u malo: „B2B" i slične skraćenice ostaju kako jesu.
        naziv = pos.title[:1].lower() + pos.title[1:]
        base += f" Radi kao {naziv}."
    return base


def check_input(text: str) -> None:
    """Provera teksta koji je uneo čovek, pre nego što išta ode provajderu."""
    from apps.policy import guards

    hits = guards.prohibitions(CAPABILITY_ACTION, {"text": text}, text)
    if hits:
        raise ImageError("HARD_PROHIBITION", hits[0])
    if FORBIDDEN.search(text):
        raise ImageError("HARD_PROHIBITION", "REAL_WORLD_MARKS")


def portrait_prompt(persona: Persona) -> str:
    return (f"Fotorealističan poslovni portret izmišljene osobe. {appearance_of(persona)} "
            "Neutralna svetla pozadina, prirodno svetlo, pogled u objektiv, "
            "od ramena naviše. Bez teksta, bez logotipa, bez vodenog žiga. "
            "Osoba ne sme ličiti ni na jednu stvarnu, poznatu osobu.")


def scene_prompt(persona: Persona, scene: str) -> str:
    return (f"Ista osoba kao na priloženoj slici, nepromenjenog lica. {scene.strip()} "
            "Fotorealistično, prirodno svetlo. Bez teksta, bez logotipa, "
            "bez vodenog žiga.")


# ---------------------------------------------------------------- provajder


def _call(path: str, fields: dict, image: bytes | None, persona: Persona) -> bytes:
    """Poziv provajdera. Vraća bajtove slike (PNG)."""
    from apps.runtime.transport import CredentialMissing, resolve_secret

    ref, source = credential_ref(persona)
    if ref is None:
        raise ImageError("NO_CREDENTIAL_REF", settings.IMAGE_PROVIDER)
    try:
        key = resolve_secret(ref).strip()
    except CredentialMissing as e:
        raise ImageError("CREDENTIAL_MISSING", f"{ref} ({source})") from e
    url = settings.IMAGE_API_URL.rstrip("/") + path
    if image is None:
        body, ctype = json.dumps(fields).encode(), "application/json"
    else:
        body, ctype = _multipart(fields, image)
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:  # noqa: S310
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise ImageError(f"HTTP_{e.code}", e.read().decode(errors="replace")[:300]) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ImageError("NETWORK", str(e)[:200]) from e
    data = (payload.get("data") or [{}])[0].get("b64_json")
    if not data:
        raise ImageError("EMPTY_RESPONSE", json.dumps(payload)[:200])
    return base64.b64decode(data)


def _multipart(fields: dict, image: bytes) -> tuple[bytes, str]:
    boundary = "----personaos" + I.ulid_public_id(I.EntityKind.MEDIA_ASSET)[-16:]
    out = bytearray()
    for k, v in fields.items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                f"{v}\r\n").encode()
    out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
            "filename=\"reference.png\"\r\nContent-Type: image/png\r\n\r\n").encode()
    out += image + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------- upis


def _next_sequence(persona: Persona) -> int:
    """Sledeći redni broj — od najvećeg postojećeg, ne od broja slika.

    Brojanje bi posle uklanjanja slike (ADR-0018, dopuna) vratilo broj koji je
    već zauzet: obriši drugu od tri i brojanje daje 3, a `IMG-…-0003` postoji.
    Najveći + 1 je uvek slobodan.
    """
    from django.db.models import Max

    zadnji = MediaAsset.objects.filter(persona=persona).aggregate(
        m=Max("public_id"))["m"]
    return int(zadnji[-4:]) + 1 if zadnji else 1


def _cost(persona: Persona, now: datetime) -> int:
    """Knjiži trošak jedne slike. Vraća iznos u EUR centima (zaokruženo naviše)."""
    from apps.observability.models import CostLedger

    micro = int(getattr(settings, "IMAGE_PRICE_MICRO_EUR", 0))
    cents = -(-micro // 10_000) if micro else 0
    CostLedger.objects.create(
        persona=persona, cost_bucket=E.CostBucket.MEDIA_GENERATION.value,
        provider=settings.IMAGE_PROVIDER, quantity=1, unit="images",
        amount_eur_cents=cents, source_currency="EUR", source_amount_minor=cents,
        fx_rate=1, fx_date=now.date(), occurred_at=now,
        provider_ref=settings.IMAGE_MODEL)
    return cents


NOTE = ("Sintetička slika. Ne prikazuje stvarnu osobu. Objavljuje se uz oznaku "
        "da je AI (Canon §17).")
#: Slika koju je čovek napravio ručno (ChatGPT prozor) i otpremio (ADR-0018 dopuna).
MANUAL_MODEL = "ručno"
#: Najviše što se prima pri otpremanju — veće slike nam ne trebaju.
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
_MAGIC = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"))


def sniff_mime(data: bytes) -> str:
    """Tip se čita iz sadržaja, ne iz imena fajla."""
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ImageError("VALIDATION_ERROR", "Nije PNG, JPEG ni WebP.")


def _png_size(data: bytes) -> tuple[int | None, int | None]:
    if not data.startswith(_MAGIC[0][0]) or len(data) < 24:
        return None, None
    return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))


@transaction.atomic
def _store(persona: Persona, data: bytes, *, kind: str, prompt: str, now: datetime,
           actor: str, mime: str = "image/png", model: str = "") -> MediaAsset:
    digest = storage.sha256(data)
    existing = MediaAsset.objects.filter(persona=persona, sha256=digest).first()
    if existing is not None:
        return existing
    key = storage.key_for(persona.public_id, digest, mime)
    storage.put(data, key=key, mime=mime)
    w, h = _png_size(data)
    model = model or settings.IMAGE_MODEL
    asset = MediaAsset.objects.create(
        public_id=I.media_asset_public_id(persona.public_id, _next_sequence(persona)),
        persona=persona, kind=kind, storage_key=key, mime_type=mime,
        sha256=digest, width=w, height=h, origin="generated", generation_model=model,
        generation_prompt_hash=storage.sha256(prompt.encode()) if prompt else "",
        rights_note=NOTE)
    audit.record("visual.asset.created", persona=persona,
                 details={"asset": asset.public_id, "kind": kind, "actor": actor,
                          "model": model})
    return asset


def _guard_daily(persona: Persona, now: datetime) -> None:
    cap = int(getattr(settings, "IMAGES_PER_DAY", 20))
    used = MediaAsset.objects.filter(persona=persona, origin="generated",
                                     created_at__gte=now - timedelta(days=1)).count()
    if used >= cap:
        raise ImageError("THROTTLED", f"Dnevni plafon slika ({cap}) je dostignut.")


# ---------------------------------------------------------------- javne radnje


def reference_of(persona: Persona) -> MediaAsset | None:
    vp = VisualProfile.objects.filter(persona=persona).select_related(
        "reference_asset").first()
    return vp.reference_asset if vp else None


def make_portrait(persona: Persona, *, actor: str, now: datetime | None = None,
                  force: bool = False) -> Result:
    """Profilna slika i sidro identiteta. Bez `force` se ne pravi dvaput."""
    now = now or timezone.now()
    if not enabled():
        raise ImageError("IMAGE_DISABLED", "IMAGE_ENABLED=false")
    existing = reference_of(persona)
    if existing is not None and not force:
        return Result(existing, "", existing.generation_model, 0)
    _guard_daily(persona, now)
    check_input(appearance_of(persona))
    prompt = portrait_prompt(persona)
    data = _call("/generations", {"model": settings.IMAGE_MODEL, "prompt": prompt,
                                  "size": settings.IMAGE_SIZE_PORTRAIT,
                                  "quality": settings.IMAGE_QUALITY, "n": 1}, None, persona)
    asset = _store(persona, data, kind=E.AssetKind.FACE_REFERENCE.value, prompt=prompt,
                   now=now, actor=actor)
    vp, _ = VisualProfile.objects.get_or_create(
        persona=persona, defaults={"style_prompt": appearance_of(persona)})
    vp.reference_asset = asset
    vp.consistency_version += 1
    vp.save(update_fields=["reference_asset", "consistency_version", "updated_at"])
    return Result(asset, prompt, settings.IMAGE_MODEL, _cost(persona, now))


def make_photo(persona: Persona, scene: str, *, actor: str,
               now: datetime | None = None) -> Result:
    """Slika za objavu — isti lik, druga scena. Traži da portret već postoji."""
    now = now or timezone.now()
    if not enabled():
        raise ImageError("IMAGE_DISABLED", "IMAGE_ENABLED=false")
    if not scene.strip():
        raise ImageError("VALIDATION_ERROR", "Opiši scenu.")
    ref = reference_of(persona)
    if ref is None:
        raise ImageError("NO_REFERENCE", "Prvo napravi profilnu sliku.")
    _guard_daily(persona, now)
    check_input(scene)
    prompt = scene_prompt(persona, scene)
    data = _call("/edits", {"model": settings.IMAGE_MODEL, "prompt": prompt,
                            "size": settings.IMAGE_SIZE_SCENE,
                            "quality": settings.IMAGE_QUALITY, "n": 1},
                 storage.get(ref.storage_key), persona)
    asset = _store(persona, data, kind=E.AssetKind.PHOTO.value, prompt=prompt, now=now,
                   actor=actor)
    _to_gallery(persona, asset, scene)
    return Result(asset, prompt, settings.IMAGE_MODEL, _cost(persona, now))


def _to_gallery(persona: Persona, asset: MediaAsset, label: str) -> None:
    col, _ = AssetCollection.objects.get_or_create(
        persona=persona, name=GALLERY,
        defaults={"purpose": "Slike za objave", "is_public_pool": True})
    if not AssetCollectionItem.objects.filter(collection=col, asset=asset).exists():
        from django.db.models import Max

        # Mesto u galeriji se broji od poslednjeg, ne od količine: posle
        # uklanjanja slike (ADR-0018, dopuna) brojanje daje zauzeto mesto.
        zadnje = AssetCollectionItem.objects.filter(collection=col).aggregate(
            m=Max("position"))["m"] or 0
        AssetCollectionItem.objects.create(
            collection=col, asset=asset, position=zadnje + 1,
            labels=[label.strip()[:80]] if label.strip() else [])


def import_image(persona: Persona, data: bytes, *, actor: str, as_portrait: bool = False,
                 label: str = "", now: datetime | None = None) -> Result:
    """Upisuje sliku koju je čovek napravio ručno (ADR-0018, dopuna 24.09.).

    Ne zove nijedan provajder i ništa ne košta, pa ne traži `IMAGE_ENABLED` niti
    dnevni plafon. Sve ostalo je isto kao kod generisane slike: fajl u storage,
    zapis u bazi, oznaka da je sintetička, audit.
    """
    now = now or timezone.now()
    if not data:
        raise ImageError("VALIDATION_ERROR", "Prazan fajl.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageError("VALIDATION_ERROR",
                         f"Slika je veća od {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    mime = sniff_mime(data)
    kind = E.AssetKind.FACE_REFERENCE.value if as_portrait else E.AssetKind.PHOTO.value
    asset = _store(persona, data, kind=kind, prompt="", now=now, actor=actor, mime=mime,
                   model=MANUAL_MODEL)
    if as_portrait:
        vp, _ = VisualProfile.objects.get_or_create(persona=persona,
                                                    defaults={"style_prompt": ""})
        vp.reference_asset = asset
        vp.consistency_version += 1
        vp.save(update_fields=["reference_asset", "consistency_version", "updated_at"])
    else:
        _to_gallery(persona, asset, label)
    return Result(asset, "", MANUAL_MODEL, 0)


@transaction.atomic
def remove_asset(persona: Persona, asset: MediaAsset, *, actor: str) -> str:
    """Uklanja sliku — iz galerije, iz baze i iz storage-a. ADR-0018, dopuna.

    Lice ne može da proveri nijedna mašina: na koga slika liči vidi samo čovek
    (Canon §9.4 t.7). Zato mora da postoji i put unazad — dotad je konzola umela
    da otpremi sliku, ali ne i da je skloni.

    Uklanjanje profilne skida i sidro identiteta: nove slike scene se posle toga
    odbijaju sa `NO_REFERENCE`, dok se ne postavi nova profilna. Već napravljene
    slike ostaju kakve jesu — one su nastale od starog lica.
    """
    if asset.persona_id != persona.pk:
        raise ImageError("VALIDATION_ERROR",
                         f"{asset.public_id} nije slika persone {persona.public_id}.")
    bila_profilna = False
    vp = VisualProfile.objects.filter(persona=persona).first()
    if vp is not None and vp.reference_asset_id == asset.pk:
        bila_profilna = True
        vp.reference_asset = None
        vp.consistency_version += 1
        vp.save(update_fields=["reference_asset", "consistency_version", "updated_at"])
    public_id, key = asset.public_id, asset.storage_key
    AssetCollectionItem.objects.filter(asset=asset).delete()
    asset.delete()
    try:
        storage.drop(key)
    except storage.StorageError as e:
        # Zapis je već obrisan; fajl koji je ostao u storage-u nije dostupan ni
        # iz konzole ni iz koda, pa se posao ne ruši zbog njega — samo se zapiše.
        audit.record("visual.asset.orphan", persona=persona,
                     details={"asset": public_id, "key": key, "why": e.code})
    audit.record("visual.asset.removed", persona=persona,
                 details={"asset": public_id, "actor": actor,
                          "was_portrait": bila_profilna})
    return public_id


def gallery_of(persona: Persona, limit: int = 12) -> list[MediaAsset]:
    return list(MediaAsset.objects.filter(persona=persona,
                                          kind=E.AssetKind.PHOTO.value)
                .order_by("-created_at")[:limit])
