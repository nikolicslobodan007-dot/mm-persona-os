"""Zlatni skup za merenje semantičke pretrage pravila. ADR-0120; Canon §21.

Isti princip kao `golden_vestine.py` za veštine, ali za pravila Pravopisa
(`KnowledgeFact`, predikat `pravopis.pravilo`): srpski upit koji bi urednik
ili agent stvarno postavio → tačka(e) koje su tačan odgovor.

Razlika u odnosu na veštine: jedna TEMA Pravopisa se prostire na više tačaka
(npr. „Велико слово" je т.10–40, interpunkcija zareza т.185–191). Zato tačan
odgovor nije jedan broj nego SKUP prihvatljivih tačaka — odeljak kome upit
pripada. `pravila_eval` meri gde u poretku završi PRVA prihvatljiva tačka.
Teme su biranе da budu jasno razdvojene (pismo, veliko slovo, transkripcija po
jezicima, interpunkcija, skraćenice…) — da merenje meri da li model povuče
pravu temu u vrh, a ne da kažnjava razliku dve skoro iste tačke iste teme.

Za razliku od veština (engleski nazivi → srpski upit, pa leksičko pada preko
jezika), ovde su i upit i pravilo na srpskom — leksičko ima više šanse. Zato
su neki upiti namerno PARAFRAZA (zapeta↔zarez, slova↔pismo), da se vidi koliko
semantika dodaje preko golog poklapanja korena (ADR-0033).

Prihvatljive tačke su date kao raspon stvarnih tačaka odeljka; neke tačke iz
raspona ne postoje posebno (uklopljene u susednu pri OCR-u), što ne smeta —
dovoljno je da BAR JEDNA prihvatljiva tačka postoji i da se nađe visoko.
"""

from __future__ import annotations


def _r(od: int, do: int) -> tuple[int, ...]:
    return tuple(range(od, do + 1))


#: (srpski upit, prihvatljive tačke — odeljak Pravopisa kome upit pripada)
PAROVI: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("koja pisma se koriste u srpskom jeziku, ćirilica i latinica", _r(1, 8)),
    ("kada se piše veliko početno slovo", _r(10, 40)),
    ("kada se reči pišu spojeno a kada odvojeno", _r(43, 64)),
    ("razlika između ijekavskog i ekavskog izgovora", _r(65, 68)),
    ("jednačenje suglasnika po zvučnosti", (75, 77, 78, 79)),
    ("nepostojano a u promeni reči", _r(92, 94)),
    ("opšta načela prilagođenog pisanja stranih imena", _r(101, 104)),
    ("kako se izgovorno prenose engleska imena na srpski", _r(113, 120)),
    ("prenošenje ruskih imena i prezimena", _r(154, 157)),
    ("transkripcija francuskih imena", _r(160, 164)),
    ("kada se u rečenici stavlja zapeta", _r(185, 191)),
    ("kako se koriste navodnici", _r(208, 211)),
    ("kako se pišu skraćenice", _r(224, 229)),
    ("rastavljanje reči na kraju reda", _r(230, 235)),
    ("kombinovanje pravopisnih znakova interpunkcije", (236,)),
)
