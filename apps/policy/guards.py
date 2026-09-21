"""Tvrde zabrane. Canon §9.4 — nisu pravila koja se mogu isključiti.

    hits = prohibitions(action_type, payload, intent)

Sedam zabrana iz `capabilities.yaml → hard_prohibitions`. Provera je
namerno konzervativna: bolje je da čovek pregleda lažnu uzbunu nego da
planer probije zabranu. Svaki pogodak je DENY + SEV1 incident + pad
poverenja na L0 + SUSPENDED persona (Canon §9.4–9.5).

Dva izvora signala:
  1. eksplicitne zastavice u payload-u (`identity.real_person_impersonation`,
     `media.real_person_likeness`, `recipients_count`…) — planer ili adapter
     ih postavljaju kad znaju;
  2. tekst (intent + sadržaj) — obrasci na srpskom i engleskom za ono što
     zastavica može da propusti.
"""

from __future__ import annotations

import re
from typing import Any

from apps.memory.embeddings import normalize

#: Masovne neželjene poruke — iznad ovoliko primalaca odjednom je zabrana.
BULK_RECIPIENTS = 20

_TEXT_RULES: dict[str, tuple[str, ...]] = {
    "IDENTITY_IMPERSONATION": (
        r"\b(ja sam|i am) (prava|stvarna|stvarni|pravi|a real|real) (osoba|covek|person|human)",
        r"\bnisam (ai|bot|vestacka)",
        r"\bi am not (an ai|a bot|artificial)",
        r"\bpredstavi (se )?kao (prava|stvarna) osoba",
        r"\bverified human\b",
        r"\blazno predstavljanje\b",
    ),
    "DISCLOSURE_CONCEALMENT": (
        r"\b(sakrij|ukloni|izbrisi|obrisi|remove|hide) (ai )?(oznaku|label|disclosure)",
        r"\bbez (ai )?oznake\b",
        r"\bda ne (primete|znaju) da je (ai|bot)",
        r"\bwithout (the )?(ai )?(label|disclosure)\b",
    ),
    "GOVERNMENT_IDENTIFIERS": (
        r"\b\d{13}\b",  # JMBG
        r"\b(jmbg|broj licne karte|broj pasosa|passport number|lazni dokument|fake id)\b",
    ),
    "PLATFORM_EVASION": (
        r"\b(captcha|recaptcha|hcaptcha|turnstile)\b.*\b(zaobidji|resi|bypass|solve|preskoci)",
        r"\b(zaobidji|bypass|solve|resi|preskoci)\b.*\b(captcha|recaptcha|hcaptcha|turnstile)",
        r"\b(stealth|undetected|anti.?detect|fingerprint spoof|patchright)\b",
        r"\b(zaobidji|izbegni|evade|bypass) (ban|blokadu|zabranu|rate limit|anti.?bot)",
        r"\bnovi nalog posle (bana|zabrane)\b",
    ),
    "SENSITIVE_DATA_SOLICITATION": (
        r"\b(posalji|posaljite|dostavi|unesi|send|share)\b.{0,40}\b(jmbg|lozink|password|"
        r"broj kartice|card number|cvv|pin|iban|broj racuna|zdravstven|dijagnoz)",
    ),
}
_COMPILED = {k: [re.compile(p) for p in v] for k, v in _TEXT_RULES.items()}


def _text(payload: dict[str, Any], intent: str) -> str:
    parts = [intent]
    for key in ("text", "body", "subject", "title", "bio", "caption", "content"):
        v = payload.get(key)
        if isinstance(v, str):
            parts.append(v)
    return normalize(" ".join(parts))


def prohibitions(action_type: str, payload: dict[str, Any], intent: str = "") -> list[str]:
    """Lista pogođenih zabrana (ID-jevi iz capabilities.yaml), bez duplikata."""
    hits: list[str] = []
    flags = payload.get("flags") or {}

    def add(pid: str) -> None:
        if pid not in hits:
            hits.append(pid)

    if flags.get("identity.real_person_impersonation") or flags.get("verification_claim"):
        add("IDENTITY_IMPERSONATION")
    if flags.get("remove_ai_disclosure") or payload.get("disclosure") is False:
        add("DISCLOSURE_CONCEALMENT")
    if flags.get("government_id"):
        add("GOVERNMENT_IDENTIFIERS")
    if flags.get("captcha_bypass") or flags.get("anti_bot_evasion") or flags.get("ban_evasion"):
        add("PLATFORM_EVASION")
    if flags.get("media.real_person_likeness"):
        add("REAL_PERSON_LIKENESS")
    recipients = payload.get("recipients_count") or len(payload.get("recipients") or [])
    if recipients > BULK_RECIPIENTS and action_type in ("mail.send", "channel.comment.create"):
        add("BULK_UNSOLICITED")

    text = _text(payload, intent)
    for pid, patterns in _COMPILED.items():
        if any(p.search(text) for p in patterns):
            add(pid)
    return hits
