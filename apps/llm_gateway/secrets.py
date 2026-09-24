"""Ključevi agenata — vrednost u fajlu, referenca u bazi. ADR-0026.

Do sada je svaki ključ ulazio kroz `.env.prod`, što znači `nano` i rebuild za
svakog agenta. Sa deset hiljada agenata i desetak provajdera to nije posao.

Ali ključ ne sme u bazu (Canon §14.3): `pg_dump` ide svake noći, kopije se
prave dnevno, a bazu čita sedam procesa — jedan ukraden dump bio bi svih
ključeva odjednom. Zato ovde:

  - vrednost se upisuje u **fajl sa pravima 0600**, u direktorijum koji nije
    deo slike i koji baza ne vidi;
  - u bazi ostaje samo `file:` referenca i **poslednja četiri znaka**, taman
    da čovek prepozna koji je ključ postavio;
  - vrednost se **nikad ne čita nazad** u konzolu, API ni log. Jedini koji je
    čita je gateway, u trenutku poziva.

Postavljanje i uklanjanje ključa su događaji koji idu u audit — bez vrednosti.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from api import audit
from apps.llm_gateway.models import AgentCredential
from apps.personas.models import Persona
from common import enums as E

#: Provajder je deo imena fajla, pa sme samo ono što je bezbedno u putanji.
PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
#: Najkraći ključ koji iko od provajdera izdaje je desetak znakova; ispod toga
#: je greška pri kucanju, ne ključ.
MIN_LEN = 12
MAX_LEN = 500


class SecretError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def secrets_dir() -> Path:
    return Path(getattr(settings, "AGENT_SECRETS_DIR", "/secrets"))


def _path(persona: Persona, provider: str) -> Path:
    return secrets_dir() / f"{provider}_{persona.public_id}.key"


def set_key(persona: Persona, provider: str, value: str, *, actor: str,
            label: str = "") -> AgentCredential:
    """Upisuje ključ u fajl, a u bazu samo referencu. Vrednost se ne vraća."""
    provider = (provider or "").strip().lower()
    value = (value or "").strip()
    if not PROVIDER_RE.match(provider):
        raise SecretError("VALIDATION_ERROR",
                          "Ime provajdera: mala slova, cifre, crta i donja crta.")
    if not (MIN_LEN <= len(value) <= MAX_LEN):
        raise SecretError("VALIDATION_ERROR",
                          f"Ključ mora imati između {MIN_LEN} i {MAX_LEN} znakova.")
    if any(c in value for c in "\n\r\t "):
        raise SecretError("VALIDATION_ERROR", "Ključ ne sme imati razmake ni prelome.")

    put = _path(persona, provider)
    try:
        put.parent.mkdir(parents=True, exist_ok=True)
        # Fajl se pravi već sa pravima 0600 — nikad ne postoji ni trenutak u
        # kom bi ga neko drugi mogao pročitati.
        fd = os.open(put, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value)
    except OSError as e:
        raise SecretError("INTERNAL", f"Ključ nije upisan: {e.strerror}") from e

    cred, _created = AgentCredential.objects.update_or_create(
        persona=persona, provider=provider,
        defaults={"credential_ref": f"file:{put}", "label": label[:120],
                  "fingerprint": value[-4:], "set_by": actor[:120],
                  "last_used_at": None})
    audit.record("llm.credential.set", persona=persona,
                 severity=E.AuditSeverity.WARNING,
                 details={"provider": provider, "actor": actor,
                          "fingerprint": cred.fingerprint})
    return cred


def drop_key(persona: Persona, provider: str, *, actor: str) -> bool:
    """Uklanja ključ: prvo fajl, pa red. Agent od tog trena nema taj provajder."""
    cred = AgentCredential.objects.filter(persona=persona, provider=provider).first()
    if cred is None:
        return False
    ref = cred.credential_ref
    if ref.startswith("file:"):
        try:
            Path(ref[5:]).unlink(missing_ok=True)
        except OSError:
            pass          # red se ipak briše; fajl bez reda je mrtav podatak
    cred.delete()
    audit.record("llm.credential.removed", persona=persona,
                 severity=E.AuditSeverity.WARNING,
                 details={"provider": provider, "actor": actor})
    return True


def ref_for(persona: Persona, provider: str) -> str | None:
    cred = AgentCredential.objects.filter(persona=persona, provider=provider).first()
    return cred.credential_ref if cred else None


def touch(persona: Persona, provider: str) -> None:
    """Beleži da je ključ upravo upotrebljen — da se vidi šta je živo."""
    AgentCredential.objects.filter(persona=persona, provider=provider).update(
        last_used_at=timezone.now())


def listing(persona: Persona) -> list[AgentCredential]:
    return list(AgentCredential.objects.filter(persona=persona).order_by("provider"))
