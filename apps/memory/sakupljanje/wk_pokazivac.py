"""WK — pokazivač-detektor (pre-filter pre destilacije).

Uvid od 30.10: mnogi FB klipovi NISU sami veština — oni su PROMO koji pokazuje na
resurs (GitHub repo, članak, link u biografiji, „comment X and I'll send it").
Destilovati takav transkript = destilovati reklamu. Zato pre destilacije agent
proceni ulaz i bira put:

    analiziraj(tekst) → {
      tip: 'sadrzaj' | 'pokazivac' | 'prazno',
      ima_postupak: bool,
      pokazivaci: [{vrsta, vrednost}],     # url / github / fraza
      preporuka: 'destiluj' | 'prati_pokazivac' | 'trazi_izvor' | 'preskoci',
      obrazlozenje: str,
    }

Logika (determinisička, bez mreže/LLM):
- Ako tekst ima SOPSTVENI postupak (koraci, redosledne reči) → `destiluj`
  (čak i ako uz to pominje neki URL — to je dodatni izvor, ne glavni).
- Inače, ako ima eksplicitan URL/GitHub repo → `prati_pokazivac` (dohvati ga).
- Inače, ako ima pokazivačke fraze bez linka („comment HOWTO", „link u bio") →
  `trazi_izvor` (potraži pomenuti resurs, npr. web pretragom).
- Inače → `preskoci` (nema upotrebljivog sadržaja).

Ovo je pre-filter za orkestraciju (`wk_sakupljanje.sakupi`): štedi destilaciju i
LLM pozive na reklamama, i usmerava agenta da prati pokazivač umesto da ga ignoriše.
"""

from __future__ import annotations

import re

# --- Prepoznavanje linkova --------------------------------------------------
# Eksplicitan http(s) URL.
_URL_RE = re.compile(r"https?://[^\s<>()\"']+", re.IGNORECASE)
# Bare github.com/owner/repo (bez scheme-a) — čest u opisima/transkriptima.
_GITHUB_RE = re.compile(r"\b(?:github\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", re.IGNORECASE)
# Bare www.domen (bez scheme-a).
_WWW_RE = re.compile(r"\bwww\.[^\s<>()\"']+", re.IGNORECASE)

# --- Pokazivačke fraze (poziv da se ode drugde) -----------------------------
_POKAZIVAC_FRAZE = [
    # engleski
    "comment ", "link in bio", "link in the bio", "dm me", "dm for", "check out",
    "check the link", "sign up", "subscribe", "free guide", "free repo",
    "i'll send you", "i will send you", "download it", "grab the",
    # srpski
    "komentariši", "komentarisi", "link u bio", "link u opisu", "poruka u inbox",
    "pošalji poruku", "posalji poruku", "poseti", "preuzmi", "prijavi se",
    "besplatan vodič", "besplatan vodic", "besplatan repo", "pogledaj link",
]

# --- Signali da tekst ima SOPSTVENI postupak --------------------------------
_REDOSLED_REČI = [
    "prvo", "zatim", "potom", "na kraju", "sledeći korak", "sledeci korak",
    "korak ", "redom", "first", "then", "next", "finally", "step ",
]
_NABRAJANJE_RE = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+\S")


def _nadji_pokazivace(tekst: str) -> list[dict]:
    """Vrati listu nađenih pokazivača bez duplikata, redom: url, github, www, fraza."""
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


def _ima_postupak(tekst: str) -> bool:
    """Heuristika: ima li tekst sopstveni postupak (koraci / redosledne reči)."""
    nizak = tekst.lower()
    broj_redosleda = sum(nizak.count(r) for r in _REDOSLED_REČI)
    broj_nabrajanja = len(_NABRAJANJE_RE.findall(tekst))
    # Dovoljno: bar 2 redosledne reči, ili bar 3 stavke nabrajanja.
    return broj_redosleda >= 2 or broj_nabrajanja >= 3


def analiziraj(tekst: str, *, min_duzina: int = 40) -> dict:
    """Proceni ulaz i preporuči put pre destilacije. Deterministički, bez mreže."""
    tekst = (tekst or "").strip()
    if len(tekst) < min_duzina:
        return {"tip": "prazno", "ima_postupak": False, "pokazivaci": [],
                "preporuka": "preskoci", "obrazlozenje": "premalo teksta"}

    pokazivaci = _nadji_pokazivace(tekst)
    ima_postupak = _ima_postupak(tekst)
    linkovi = [p for p in pokazivaci if p["vrsta"] in ("url", "github", "www")]
    fraze = [p for p in pokazivaci if p["vrsta"] == "fraza"]

    if ima_postupak:
        return {"tip": "sadrzaj", "ima_postupak": True, "pokazivaci": pokazivaci,
                "preporuka": "destiluj",
                "obrazlozenje": "tekst ima sopstveni postupak; destiluj direktno"
                + (" (uz dodatne izvore)" if linkovi else "")}
    if linkovi:
        meta = ", ".join(p["vrednost"] for p in linkovi[:3])
        return {"tip": "pokazivac", "ima_postupak": False, "pokazivaci": pokazivaci,
                "preporuka": "prati_pokazivac",
                "obrazlozenje": f"nema sopstveni postupak; prati link: {meta}"}
    if fraze:
        return {"tip": "pokazivac", "ima_postupak": False, "pokazivaci": pokazivaci,
                "preporuka": "trazi_izvor",
                "obrazlozenje": "pokazivačka fraza bez linka; potraži pomenuti resurs"}
    return {"tip": "sadrzaj", "ima_postupak": False, "pokazivaci": [],
            "preporuka": "preskoci",
            "obrazlozenje": "nema ni postupak ni pokazivač — verovatno bez vrednosti"}


if __name__ == "__main__":
    import json
    primeri = {
        "FB promo (klip)": ("A free GitHub guide that teaches you Claude Code in a "
                            "weekend. Ten modules, copy-paste templates. Free, MIT "
                            "licensed. Comment HOWTO and I'll send you the repo."),
        "Repo u tekstu": "Ceo kod je na github.com/luongnv89/claude-howto, MIT licenca.",
        "Pravi postupak": ("Prvo istraži primaoca. Zatim personalizuj uvod. "
                           "Na kraju daj jasan poziv na akciju."),
        "Reklama bez ičega": "Najbolji proizvod ikad! Kupi odmah! Ne propusti!",
    }
    for ime, t in primeri.items():
        r = analiziraj(t)
        print(f"[{ime}] → {r['preporuka']}  ({r['obrazlozenje']})")
        if r["pokazivaci"]:
            print("   pokazivaci:", json.dumps(r["pokazivaci"], ensure_ascii=False))
