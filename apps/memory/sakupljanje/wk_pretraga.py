"""WK — pretraga izvora (za granu `trazi_izvor` pametnih vrata).

Kad pokazivač-detektor kaže „trazi_izvor" (promo bez linka, npr. „comment HOWTO
and I'll send you the repo"), agent mora da NAĐE pomenuti resurs. „Ramena
džinova": koristimo gotovu OSS pretragu (`ddgs`, bez API ključa), ne pišemo
sopstveni pretraživač.

Deterministički (testira se bez mreže):
- `napravi_upit(tekst)` — iz promo teksta napravi upit (skida pokazivačke fraze,
  uzima nosive reči); i proceni da li je GitHub-orijentisan.
- rangiranje rezultata — ako tekst pominje repo/github, favorizuj github.com;
  preskoči same društvene mreže (facebook/instagram — to je promo, ne resurs).

Živo (van proxy-ja — PC/server, kao whisper/trafilatura):
- `trazi_izvor(tekst, trazilac=None)` — `trazilac(upit, maks) -> [url]`;
  podrazumevano `ddgs`. Ubrizgaj lažni za test. Vraća najbolji URL ili None.
"""

from __future__ import annotations

import re

import wk_pokazivac as POK

# Domeni koji su obično sam promo, ne resurs.
_PROMO_DOMENI = ("facebook.com", "instagram.com", "tiktok.com", "youtube.com/shorts",
                 "x.com", "twitter.com", "fb.watch", "lnkd.in")
# Reči koje ukazuju da tražimo GitHub repo.
_GITHUB_ZNACI = ("github", "repo", "repository", "open source", "open-source", "mit")


def napravi_upit(tekst: str, *, maks_reci: int = 12) -> str:
    """Od promo teksta napravi upit za pretragu (skini pokazivačke fraze/šum)."""
    t = (tekst or "").strip()
    nizak = t.lower()
    for fr in POK._POKAZIVAC_FRAZE:
        nizak = nizak.replace(fr, " ")
    # izbaci interpunkciju (zadrži slova/cifre/razmak/crtice)
    nizak = re.sub(r"[^\w\s-]", " ", nizak, flags=re.UNICODE)
    reci = [w for w in nizak.split() if len(w) > 2]
    return " ".join(reci[:maks_reci]).strip()


def _github_orijentisan(tekst: str) -> bool:
    nizak = (tekst or "").lower()
    return any(z in nizak for z in _GITHUB_ZNACI)


def _ddgs_trazilac(upit: str, maks: int) -> list[str]:
    """Podrazumevani živi pretraživač (ddgs). Van proxy-ja. Greška → prazno."""
    try:
        from ddgs import DDGS
        return [r.get("href") for r in DDGS().text(upit, max_results=maks) if r.get("href")]
    except Exception as e:
        print("ddgs nedostupan/greška:", e)
        return []


def rangiraj(urlovi: list[str], *, github_orijentisan: bool) -> str | None:
    """Izaberi najbolji URL: preskoči promo-domene; po potrebi favorizuj github.com."""
    kandidati = [u for u in urlovi if u and not any(d in u.lower() for d in _PROMO_DOMENI)]
    if not kandidati:
        return None
    if github_orijentisan:
        gh = [u for u in kandidati if "github.com" in u.lower()]
        if gh:
            return gh[0]
    return kandidati[0]


def trazi_izvor(tekst: str, *, trazilac=None, maks: int = 6) -> str | None:
    """Promo tekst → najbolji URL resursa (ili None). `trazilac` ubrizgan za test."""
    upit = napravi_upit(tekst)
    if not upit:
        return None
    trazi = trazilac or _ddgs_trazilac
    urlovi = trazi(upit, maks)
    return rangiraj(urlovi, github_orijentisan=_github_orijentisan(tekst))


if __name__ == "__main__":
    promo = ("A free GitHub guide that teaches you Claude Code in a weekend. Ten "
             "modules, copy-paste templates. Free, MIT licensed. Comment HOWTO and "
             "I'll send you the repo.")
    print("upit:", napravi_upit(promo))
    print("github-orijentisan:", _github_orijentisan(promo))
    # Lažni pretraživač (bez mreže): FB promo + pravi repo.
    def lazni(u, m):
        return ["https://facebook.com/watch/123",
                "https://github.com/luongnv89/claude-howto",
                "https://neki-blog.rs/claude"]
    print("izabrano:", trazi_izvor(promo, trazilac=lazni))
