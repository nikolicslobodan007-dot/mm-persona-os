"""Lokalni sastavljač — deterministički tekst iz šablona. ADR-0009.

Nije model i ne pretvara se da jeste. Služi za tri stvari:
  - sistem radi od prvog dana bez API ključa i bez troška;
  - simulacija i testovi daju isti tekst za isti ulaz;
  - ceo tok (nacrt → odobrenje → kapija → adapter) može da se proveri pre
    nego što se izabere i plati pravi model.

Izbor varijante zavisi samo od hash-a teme, pa ista tema daje isti tekst,
a različite teme ne zvuče kao kopija jedna druge.
"""

from __future__ import annotations

import hashlib

from common import enums as E

_OPEN_SR = (
    "Danas razmišljam o temi: {topic}.",
    "Jedna stvar koja mi je ove nedelje zapala za oko, na temu „{topic}”.",
    "Kratko o temi „{topic}”, iz ugla onoga što radim svaki dan.",
    "Pitanje koje mi se stalno vraća: {topic}.",
)
_CLOSE_SR = (
    "Kako vi to rešavate u svom timu?",
    "Zanima me da li imate drugačije iskustvo.",
    "Ako vam je korisno, javite — napisaću i nastavak.",
    "Šta biste dodali?",
)
_OPEN_EN = (
    "Thinking today about: {topic}.",
    "One thing I noticed this week about {topic}.",
    "A short note on {topic}, from what I work on every day.",
    "A question that keeps coming back: {topic}.",
)
_CLOSE_EN = (
    "How does your team handle this?",
    "Curious whether your experience is different.",
    "If this is useful, let me know and I will write a follow-up.",
    "What would you add?",
)


def _pick(options: tuple[str, ...], key: str, salt: str) -> str:
    h = int(hashlib.sha256(f"{salt}:{key}".encode()).hexdigest(), 16)
    return options[h % len(options)]


def compose(purpose: E.LLMPurpose, brief: dict, prompt: str) -> str:
    topic = str(brief.get("topic") or "").strip() or "posao"
    angle = str(brief.get("angle") or "").strip()
    facts = [str(f).strip() for f in brief.get("facts", []) if str(f).strip()][:2]
    english = str(brief.get("language", "sr")).lower().startswith("en")
    opens, closes = (_OPEN_EN, _CLOSE_EN) if english else (_OPEN_SR, _CLOSE_SR)
    parts = [_pick(opens, topic, "open").format(topic=topic)]
    if angle:
        parts.append(angle.rstrip(".") + ".")
    for f in facts:
        parts.append(f.rstrip(".") + ".")
    if purpose == E.LLMPurpose.REPLY:
        return " ".join(parts[1:] or parts)
    parts.append(_pick(closes, topic, "close"))
    return " ".join(parts)
