"""Dvopismo (latinica + ćirilica) za determinističke Libri ekstraktore.

Deterministička osnova (tvrdnje 4a, entiteti 4b) imala je latinične regex-e, pa su
ćirilični izvori (javni web/mejl) davali 0. Ovde su dva pomoćnika koja otključavaju
ćirilicu BEZ gubitka poštenja: izlaz ostaje u ORIGINALNOM pismu (OBSERVED doslovni
isečci iz bloka), a ćirilica se obrađuje tako što:
  - `VELIKA` proširuje char-klase (veliko slovo, granica rečenice) ćiriličnim slovima;
  - `u_latinicu` transliteriše token u latinicu SAMO za proveru pokaznih reči
    (reuse postojećeg latiničnog vokabulara) — ne menja tekst koji se upisuje.
Srpska transliteracija je jednoznačna (č, ć, š, ž, đ, lj, nj, dž).
"""

from __future__ import annotations

#: Velika slova oba pisma — za upotrebu unutar regex char-klasa `[...]`.
VELIKA = "A-ZČĆŽŠĐАБВГДЂЕЖЗИЈКЛЉМНЊОПРСТЋУФХЦЧЏШ"

_CIR2LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "đ", "е": "e",
    "ж": "ž", "з": "z", "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj",
    "м": "m", "н": "n", "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s",
    "т": "t", "ћ": "ć", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "č",
    "џ": "dž", "ш": "š",
}
# Velika ćirilična slova → odgovarajuća latinica (Љ→Lj, Џ→Dž…).
for _k, _v in list(_CIR2LAT.items()):
    _CIR2LAT[_k.upper()] = _v.capitalize() if len(_v) > 1 else _v.upper()


def u_latinicu(s: str) -> str:
    """Transliteriši ćirilicu u latinicu (latinica prolazi nepromenjena)."""
    return "".join(_CIR2LAT.get(c, c) for c in (s or ""))
