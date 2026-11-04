"""Veritas klip — URL videa/audija → audio → transkript (Gateway TRANSCRIBE). ADR-0125.

Tok (slice 3): `yt-dlp` skine najbolji audio sa URL-a, `ffmpeg` ga svede na
16 kHz mono mp3 (Whisper ionako radi na 16 kHz, pa je fajl manji i staje u
Groq-ovu granicu), fajl ode u skladište kao `MediaAsset` (kind=AUDIO), pa
`gateway.transcribe` pozove Groq Whisper. Vraća transkript koji dalje ide u
`nalaz` (tri sloja: doslovno / implicirano / tehnika).

`--suvo`: bez mreže, bez skidanja, bez troška — vraća fiksni primer transkripta.

Granice: Groq prima do ~25 MB po fajlu (besplatni tier); 16 kHz mono mp3 na
48 kb/s je ~0,36 MB/min, pa ~30 min klipa staje. Duži klip → jasna greška,
ne tiho sečenje.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile

_MAKS_BAJTOVA = 24 * 1024 * 1024  # Groq free tier ~25 MB; ostavljamo rezervu
_DOZVOLJENE_SEME = ("http://", "https://")


class KlipGreska(Exception):
    def __init__(self, kod: str, detalj: str = ""):
        super().__init__(f"{kod}: {detalj}")
        self.kod, self.detalj = kod, detalj


def _alat(ime: str) -> str:
    put = shutil.which(ime)
    if not put:
        raise KlipGreska("ALAT_NEDOSTAJE", ime)
    return put


def _trajanje_ms(put_fajla: str) -> int:
    try:
        izlaz = subprocess.run(
            [_alat("ffprobe"), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", put_fajla],
            capture_output=True, text=True, timeout=60, check=True).stdout.strip()
        return int(round(float(izlaz) * 1000))
    except (subprocess.SubprocessError, ValueError):
        return 0


def _cookies_args() -> list[str]:
    """yt-dlp `--cookies <fajl>` ako postoji — YouTube sa servera traži autentifikaciju
    („Sign in to confirm you're not a bot"). Putanja: env YT_COOKIES_FILE ili
    <BASE_DIR>/secrets/yt-cookies.txt. Fajl je van git-a (.gitignore `secrets/`);
    korisnik ga izveze iz browsera (gde je ulogovan) i stavi na server."""
    put = os.environ.get("YT_COOKIES_FILE", "").strip()
    if not put:
        try:
            from django.conf import settings
            put = os.path.join(getattr(settings, "BASE_DIR", ""), "secrets", "yt-cookies.txt")
        except Exception:  # noqa: BLE001 — bez Django konteksta nema podrazumevane putanje
            put = ""
    return ["--cookies", put] if put and os.path.isfile(put) else []


def _konvertuj(ulaz: str, radni: str) -> tuple[str, int]:
    """Svedi dati audio/video fajl na 16 kHz mono mp3 (Whisper ulaz). (putanja, trajanje_ms)."""
    izlaz = os.path.join(radni, "audio.mp3")
    try:
        subprocess.run(
            [_alat("ffmpeg"), "-y", "-i", ulaz, "-ar", "16000", "-ac", "1",
             "-b:a", "48k", izlaz],
            capture_output=True, text=True, timeout=600, check=True)
    except subprocess.SubprocessError as e:
        raise KlipGreska("PRETVARANJE_PALO", str(e)[:300]) from e
    vel = os.path.getsize(izlaz)
    if vel > _MAKS_BAJTOVA:
        raise KlipGreska(
            "AUDIO_PREVELIK",
            f"{vel // (1024 * 1024)} MB > {_MAKS_BAJTOVA // (1024 * 1024)} MB — klip je predug")
    return izlaz, _trajanje_ms(izlaz)


def _skini_audio(url: str, radni: str) -> tuple[str, int]:
    """Skine audio sa URL-a i svede ga na 16 kHz mono mp3. Vrati (putanja, trajanje_ms)."""
    if not url.startswith(_DOZVOLJENE_SEME):
        raise KlipGreska("LOSE_URL", url[:80])
    sirovi = os.path.join(radni, "sirovo.%(ext)s")
    try:
        subprocess.run(
            [_alat("yt-dlp"), "-x", "--no-playlist", "--no-warnings",
             *_cookies_args(), "-o", sirovi, url],
            capture_output=True, text=True, timeout=600, check=True)
    except subprocess.TimeoutExpired as e:
        raise KlipGreska("SKIDANJE_ISTEKLO", url[:80]) from e
    except subprocess.CalledProcessError as e:
        raise KlipGreska("SKIDANJE_PALO", (e.stderr or "")[:300]) from e

    skinuti = [f for f in os.listdir(radni) if f.startswith("sirovo.")]
    if not skinuti:
        raise KlipGreska("NEMA_AUDIJA", url[:80])
    return _konvertuj(os.path.join(radni, skinuti[0]), radni)


def _primer_suvo(url: str) -> dict:
    return {
        "transkript": ("Ovo je probni transkript u suvom režimu. Građani treba da "
                       "znaju da je sve pod kontrolom i da nema razloga za brigu."),
        "izvor_url": izvor,
        "trajanje_ms": 12000,
        "asset_id": None,
        "provider": "suvo",
        "model": "suvo",
        "cena_centi": 0,
    }


def transkribuj(izvor: str, *, persona=None, suvo: bool = False, je_fajl: bool = False) -> dict:
    """URL ili lokalni fajl → transkript. Vraća dict sa transkriptom, izvorom i cenom.

    `je_fajl=True`: `izvor` je lokalni audio/video fajl (ne skida se) — ffmpeg ga
    svede i preda Whisper-u. Korisno kad YouTube blokira skidanje sa servera.
    """
    if suvo:
        return _primer_suvo(izvor)

    from apps.llm_gateway import gateway
    from apps.visuals import storage
    from apps.visuals.models import MediaAsset
    from common import enums as E

    radni = tempfile.mkdtemp(prefix="veritas-klip-")
    try:
        if je_fajl:
            if not os.path.isfile(izvor):
                raise KlipGreska("NEMA_FAJLA", izvor[:120])
            put_audio, trajanje_ms = _konvertuj(izvor, radni)
        else:
            put_audio, trajanje_ms = _skini_audio(izvor, radni)
        with open(put_audio, "rb") as fh:
            podaci = fh.read()
    finally:
        shutil.rmtree(radni, ignore_errors=True)

    sha = hashlib.sha256(podaci).hexdigest()
    mime = "audio/mpeg"
    kljuc = f"veritas/klip/{sha[:32]}.mp3"
    storage.put(podaci, key=kljuc, mime=mime)

    public_id = f"AUD-{sha[:12]}"
    asset, _ = MediaAsset.objects.get_or_create(
        storage_key=kljuc,
        defaults={
            "public_id": public_id,
            "kind": E.AssetKind.AUDIO.value,
            "mime_type": mime,
            "sha256": sha,
            "duration_ms": trajanje_ms,
            "origin": "system",
        },
    )

    g = gateway.transcribe(asset, persona=persona)
    return {
        "transkript": g.text,
        "izvor_url": url,
        "trajanje_ms": trajanje_ms,
        "asset_id": asset.public_id,
        "provider": g.provider,
        "model": g.model,
        "cena_centi": g.amount_eur_cents or 0,
    }
