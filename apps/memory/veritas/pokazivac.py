"""Veritas — pokazivač-detektor (pre-filter pre analize tvrdnji).

Mnogi klipovi/objave NISU same po sebi tvrdnja — one pokazuju na resurs
(članak, snimak, link, „pogledaj u opisu"). Analizirati takav tekst bez praćenja
pokazivača = suditi o reklami. Zato pre vađenja tvrdnji procenimo ulaz:

    analiziraj(tekst) → {
      tip: 'sadrzaj' | 'pokazivac' | 'prazno',
      ima_tvrdnje: bool,
      pokazivaci: [{vrsta, vrednost}],      # url / github / www / fraza
      preporuka: 'analiziraj' | 'prati_pokazivac' | 'trazi_izvor' | 'preskoci',
      obrazlozenje: str,
    }

Deterministički, bez mreže i bez LLM-a. Usmerava Veritasa da prati pokazivač
umesto da ga ignoriše, i štedi LLM pozive na praznom/promo tekstu.
Nasleđeno iz nacrta `feat/sakupljanje-gateway` (wk_pokazivac), preneto u paket.
"""

from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://[^\s<>()\"']+", re.IGNORECASE)
_GITHUB_RE = re.compile(r"\b(?:github\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", re.IGNORECASE)
_WWW_RE = re.compile(r"\bwww\.[^\s<>()\"']+", re.IGNORECASE)

_POKAZIVAC_FRAZE = [
    "comment ", "link in bio", "link in the bio", "dm me", "dm for", "check out",
    "check the link", "sign up", "subscribe", "full video", "watch the full",
    "source in", "više u opisu", "vise u opisu", "link u bio", "link u opisu",
    "pogledaj link", "ceo snimak", "cela izjava", "pogledaj original", "izvor u",
]

_REDOSLED_RECI = [
    "prvo", "zatim", "potom", "na kraju", "tvrdi", "navodi", "kaže", "kaze",
    "izjavio", "rekao", "objavljeno", "prema", "izvor", "podatak",
]


def _nadji_pokazivace(tekst: str) -> list[dict]:
    nadjeni: list[dict] = []
    videno: set[str] = set()

    def dodaj(vrsta: str, vrednost: str):
        kljuc = f"{vrsta}:{vrednost.lower().rstrip('/.,')}"
        if kljuc not in videno:
            videno.add(kljuc)
            nadjeni.append({"vrsta": vrsta, "vrednost": vrednost.rstrip(".,)")})

    for m in _GITHUB_RE.finditer(tekst):
        dodaj("github", m.group(1))
    for m in _URL_RE.finditer(tekst):
        dodaj("url", m.group(0))
    for m in _WWW_RE.finditer(tekst):
        dodaj("www", m.group(0))
    nizak = tekst.lower()
    for fr in _POKAZIVAC_FRAZE:
        if fr in nizak:
            dodaj("fraza", fr.strip())
    return nadjeni


def _ima_tvrdnje(tekst: str) -> bool:
    """Heuristika: ima li tekst sopstvenu tvrdnju (rečenice sa navođenjem/podatkom)."""
    nizak = tekst.lower()
    broj = sum(nizak.count(r) for r in _REDOSLED_RECI)
    ima_broj = bool(re.search(r"\d", tekst))
    recenice = [s for s in re.split(r"[.!?]\s", tekst) if len(s.strip()) > 20]
    return broj >= 1 or (ima_broj and len(recenice) >= 1) or len(recenice) >= 2


def analiziraj(tekst: str, *, min_duzina: int = 30) -> dict:
    """Proceni ulaz i preporuči put pre vađenja tvrdnji. Determinističko, bez mreže."""
    tekst = (tekst or "").strip()
    if len(tekst) < min_duzina:
        return {"tip": "prazno", "ima_tvrdnje": False, "pokazivaci": [],
                "preporuka": "preskoci", "obrazlozenje": "premalo teksta"}

    pokazivaci = _nadji_pokazivace(tekst)
    ima = _ima_tvrdnje(tekst)
    linkovi = [p for p in pokazivaci if p["vrsta"] in ("url", "github", "www")]
    fraze = [p for p in pokazivaci if p["vrsta"] == "fraza"]

    if ima:
        obr = "tekst nosi sopstvene tvrdnje; analiziraj direktno"
        return {"tip": "sadrzaj", "ima_tvrdnje": True, "pokazivaci": pokazivaci,
                "preporuka": "analiziraj",
                "obrazlozenje": obr + (" (uz dodatne izvore)" if linkovi else "")}
    if linkovi:
        meta = ", ".join(p["vrednost"] for p in linkovi[:3])
        return {"tip": "pokazivac", "ima_tvrdnje": False, "pokazivaci": pokazivaci,
                "preporuka": "prati_pokazivac",
                "obrazlozenje": f"nema sopstvenu tvrdnju; prati izvor: {meta}"}
    if fraze:
        return {"tip": "pokazivac", "ima_tvrdnje": False, "pokazivaci": pokazivaci,
                "preporuka": "trazi_izvor",
                "obrazlozenje": "pokazivačka fraza bez linka; potraži pomenuti izvor"}
    return {"tip": "sadrzaj", "ima_tvrdnje": False, "pokazivaci": [],
            "preporuka": "preskoci",
            "obrazlozenje": "ni tvrdnja ni pokazivač — verovatno bez sadržaja za proveru"}
